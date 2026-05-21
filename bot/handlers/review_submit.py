"""用户评价提交入口（卡片驱动 FSM 重定向 + 个人评价主页 + /start write_<tid> 直达）

历史：旧线性 ReviewSubmitStates FSM 已于 2026-05-20 Sprint 7 §9.1 第 3 批
dead code 删除中清理。本文件仅保留：

    - start_review_flow(...)：[📝 写评价] 入口，重定向到 review_card.start_card_review
    - cb_review_start：teacher_detail [📝 写评价] callback 入口
    - 个人评价主页相关 handler（user:write_review / user:reviews:* / cb_reviews_*）
    - WriteReviewLookupStates FSM（艺名查老师 → 进卡片）
    - 通用取消 cb_review_cancel
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext

from bot.database import (
    get_teacher_by_name,
    get_user_review_stats,
    list_user_reviews_paged,
    count_user_reviews,
    get_teachers_by_ids,
    REVIEW_RATINGS,
)
from bot.keyboards.user_kb import (
    review_cancel_kb,
    review_cancelled_kb,
    review_subscribe_links_kb,
    user_reviews_home_kb,
)
from bot.states.teacher_states import (
    UserReviewsHomeStates,
    WriteReviewLookupStates,
)
from bot.utils.required_channels import check_user_subscribed

logger = logging.getLogger(__name__)

router = Router(name="review_submit")


# ============ 入口 ============

async def start_review_flow(
    bot,
    chat_id: int,
    user_id: int,
    teacher_id: int,
    state: FSMContext,
    *,
    edit_msg: Optional[types.Message] = None,
    pre_rating: Optional[str] = None,
) -> tuple[str, Optional[dict]]:
    """[📝 写评价] 入口（2026-05-18 起重定向到卡片驱动 FSM）

    返回 ("ok"|"not_found"|"inactive"|"rate_limited"|"need_subscribe", extra)
        - ok：state 已设置 CardReviewStates.card；extra={"teacher": dict}
              调用方需自己调用 render_card(target_msg, state, via_edit=...)
        - rate_limited：extra={"reason": str}
        - need_subscribe：extra={"missing": list[dict]}
        - not_found / inactive：extra=None
    """
    from bot.handlers.review_card import start_card_review
    return await start_card_review(
        bot, user_id, teacher_id, state, pre_rating=pre_rating,
    )


# ============ 主菜单 [📝 写评价]：个人评价主页（2026-05-18） ============

REVIEWS_HOME_PAGE_SIZE = 5

_STATUS_LABEL_HOME: dict[str, str] = {
    "pending":  "⏳ 未审核",
    "approved": "✅ 已审核",
    "rejected": "❌ 已驳回",
}
_RATING_BY_KEY: dict[str, dict] = {r["key"]: r for r in REVIEW_RATINGS}


def _percent(n: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{(n * 100 // total)}%"


async def _render_reviews_home(
    target_msg: types.Message,
    state: FSMContext,
    *,
    user_id: int,
    via_edit: bool = True,
):
    """渲染个人评价主页：根据 state.data 中的 filter / page 取数据 + 编辑消息"""
    data = await state.get_data()
    status_filter = data.get("status_filter") or None
    rating_filter = data.get("rating_filter") or None
    page = int(data.get("page") or 0)
    pre_rating = data.get("pre_rating") or None  # 兼容旧字段

    # 取 stats
    stats = await get_user_review_stats(user_id)
    status_count = stats["status"]
    rating_count = stats["rating_approved"]
    total_all = stats["total"]
    approved_total = status_count.get("approved", 0)

    # 取过滤后的总数 + 当前页
    total_filtered = await count_user_reviews(user_id, status_filter, rating_filter)
    total_pages = max(1, (total_filtered + REVIEWS_HOME_PAGE_SIZE - 1) // REVIEWS_HOME_PAGE_SIZE)
    if page >= total_pages:
        page = total_pages - 1
    if page < 0:
        page = 0
    offset = page * REVIEWS_HOME_PAGE_SIZE
    rows = await list_user_reviews_paged(
        user_id, status_filter, rating_filter,
        limit=REVIEWS_HOME_PAGE_SIZE, offset=offset,
    )

    # 批量反查老师名
    teacher_ids = [int(r["teacher_id"]) for r in rows if r.get("teacher_id")]
    teachers_map = await get_teachers_by_ids(list(set(teacher_ids))) if teacher_ids else {}

    # 文案
    lines: list[str] = [
        "📝 个人评价主页",
        "━━━━━━━━━━━━━━━",
        f"状态：未审核 {status_count.get('pending', 0)}"
        f" / 已审核 {approved_total}"
        f" / 已驳回 {status_count.get('rejected', 0)}",
        f"评级（仅已审核）：👍 {rating_count.get('positive', 0)}"
        f" ({_percent(rating_count.get('positive', 0), approved_total)})"
        f" / 😐 {rating_count.get('neutral', 0)}"
        f" ({_percent(rating_count.get('neutral', 0), approved_total)})"
        f" / 👎 {rating_count.get('negative', 0)}"
        f" ({_percent(rating_count.get('negative', 0), approved_total)})",
        f"累计提交：{total_all} 笔",
        "━━━━━━━━━━━━━━━",
    ]
    # 当前过滤摘要
    fragments: list[str] = []
    if status_filter:
        fragments.append(_STATUS_LABEL_HOME.get(status_filter, status_filter))
    if rating_filter:
        r_meta = _RATING_BY_KEY.get(rating_filter, {})
        fragments.append(f"{r_meta.get('emoji', '')} {r_meta.get('label', rating_filter)}")
    if fragments:
        lines.append(f"🔎 当前筛选：{' + '.join(fragments)}（共 {total_filtered} 条）")
    else:
        lines.append(f"📋 全部评价（共 {total_filtered} 条）")
    lines.append("")

    if rows:
        for idx, r in enumerate(rows, start=offset + 1):
            t = teachers_map.get(int(r["teacher_id"]))
            tname = t["display_name"] if t else f"#{r['teacher_id']}"
            st = _STATUS_LABEL_HOME.get(r["status"], r["status"])
            rt_meta = _RATING_BY_KEY.get(r.get("rating") or "", {})
            rt = f"{rt_meta.get('emoji', '')}{rt_meta.get('label', '?')}" if rt_meta else "?"
            overall = r.get("overall_score")
            overall_txt = f"  综合 {overall:.1f}" if isinstance(overall, (int, float)) else ""
            lines.append(f"{idx}. #{r['id']} {tname}  {rt}{overall_txt}  {st}")
            created = (r.get("created_at") or "")[:16]
            if created:
                lines.append(f"   📅 {created}")
            if r["status"] == "rejected" and r.get("reject_reason"):
                lines.append(f"   驳回：{r['reject_reason'][:30]}")
    else:
        lines.append("（暂无记录，点击下方 [🤖 写车评] 提交首条评价）")

    lines.append("")
    if pre_rating:
        pr_meta = _RATING_BY_KEY.get(pre_rating, {})
        lines.append(
            f"💡 已预选评级：{pr_meta.get('emoji', '')}{pr_meta.get('label', '?')}"
            "（点 [🤖 写车评] 跳过评级直接打分；再点同一评级可清除）"
        )
    else:
        lines.append("💡 点 👍/😐/👎 选中评级 → [🤖 写车评] 可跳过 Step 2 评级。")

    text = "\n".join(lines)
    kb = user_reviews_home_kb(
        status_filter=status_filter,
        rating_filter=rating_filter,
        page=page,
        total_pages=total_pages,
    )
    try:
        if via_edit:
            await target_msg.edit_text(text, reply_markup=kb)
        else:
            await target_msg.answer(text, reply_markup=kb)
    except Exception:
        try:
            await target_msg.answer(text, reply_markup=kb)
        except Exception:
            pass


@router.callback_query(F.data == "user:write_review")
async def cb_user_write_review_entry(callback: types.CallbackQuery, state: FSMContext):
    """[📝 写评价] 主菜单入口 → 个人评价主页"""
    await state.clear()
    await state.set_state(UserReviewsHomeStates.viewing)
    await state.set_data({
        "status_filter": None,
        "rating_filter": None,
        "page": 0,
        "pre_rating": None,
    })
    await _render_reviews_home(
        callback.message, state,
        user_id=callback.from_user.id, via_edit=True,
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith("user:reviews:filter:status:"),
    UserReviewsHomeStates.viewing,
)
async def cb_reviews_filter_status(callback: types.CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[-1]
    if key == "clear":
        await state.update_data(status_filter=None, page=0)
    elif key in {"pending", "approved", "rejected"}:
        await state.update_data(status_filter=key, page=0)
    else:
        await callback.answer("参数错误", show_alert=True)
        return
    await _render_reviews_home(
        callback.message, state, user_id=callback.from_user.id, via_edit=True,
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith("user:reviews:filter:rating:"),
    UserReviewsHomeStates.viewing,
)
async def cb_reviews_filter_rating(callback: types.CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[-1]
    if key == "clear":
        await state.update_data(rating_filter=None, pre_rating=None, page=0)
    elif key in {"positive", "neutral", "negative"}:
        # rating 兼作预选评级
        await state.update_data(rating_filter=key, pre_rating=key, page=0)
    else:
        await callback.answer("参数错误", show_alert=True)
        return
    await _render_reviews_home(
        callback.message, state, user_id=callback.from_user.id, via_edit=True,
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith("user:reviews:page:"),
    UserReviewsHomeStates.viewing,
)
async def cb_reviews_page(callback: types.CallbackQuery, state: FSMContext):
    try:
        page = int(callback.data.split(":")[-1])
        page = max(0, page)
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    await state.update_data(page=page)
    await _render_reviews_home(
        callback.message, state, user_id=callback.from_user.id, via_edit=True,
    )
    await callback.answer()


@router.callback_query(
    F.data == "user:reviews:write",
    UserReviewsHomeStates.viewing,
)
async def cb_reviews_write(callback: types.CallbackQuery, state: FSMContext):
    """[🤖 写车评] → 转入艺名输入；保留 pre_rating（如有）作为评级预选"""
    data = await state.get_data()
    pre_rating = data.get("pre_rating") or None
    await state.set_state(WriteReviewLookupStates.waiting_teacher_name)
    await state.set_data({"pre_rating": pre_rating} if pre_rating else {})

    hint = ""
    if pre_rating:
        r_meta = _RATING_BY_KEY.get(pre_rating, {})
        hint = (
            f"\n\n💡 已预选评级：{r_meta.get('emoji', '')}{r_meta.get('label', '?')}"
            "（Step 2 评级会自动跳过）"
        )
    text = (
        "📝 写评价 - 输入老师艺名\n\n"
        "请直接输入要评价的老师**艺名**（精确匹配，不区分大小写）。\n\n"
        "📌 如「丁小夏」、「乔儿」等\n"
        "🔍 如果你不记得艺名，可以先到 [📚 今天能约谁] / [⭐ 我的收藏]\n"
        "    找到老师 → 详情页底部 [📝 写评价] 也能进入此流程。"
        f"{hint}\n\n"
        "任意时刻发 /cancel 退出。"
    )
    try:
        await callback.message.edit_text(text, reply_markup=review_cancel_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=review_cancel_kb())
    await callback.answer()


@router.message(F.text == "/cancel", UserReviewsHomeStates())
async def cmd_cancel_reviews_home(message: types.Message, state: FSMContext):
    """主页 /cancel = 直接关闭 → 返回主菜单提示"""
    await state.clear()
    await message.answer(
        "❌ 已关闭个人评价主页。",
        reply_markup=review_cancelled_kb(),
    )


@router.message(WriteReviewLookupStates.waiting_teacher_name, F.text)
async def on_write_review_teacher_name(message: types.Message, state: FSMContext):
    """接收艺名 → 精确查找 → 通过则进入 ReviewSubmit FSM；失败则 alert + 留在原状态"""
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer(
            "❌ 已取消写评价。",
            reply_markup=review_cancelled_kb(),
        )
        return
    if not text or len(text) > 60:
        await message.reply("❌ 艺名不能为空或过长，请重新输入（≤ 60 字）。")
        return
    teacher = await get_teacher_by_name(text)
    if not teacher:
        await message.reply(
            f"⚠️ 没找到艺名为「{text}」的老师。\n"
            "请检查拼写后重发；或 /cancel 退出。"
        )
        return
    user_id = message.from_user.id if message.from_user else 0
    teacher_id = int(teacher["user_id"])
    pre_rating = (await state.get_data()).get("pre_rating")
    status, extra = await start_review_flow(
        message.bot, message.chat.id, user_id, teacher_id, state,
        pre_rating=pre_rating,
    )
    if status == "not_found":
        await state.clear()
        await message.reply("⚠️ 该老师不存在或已被删除。")
        return
    if status == "inactive":
        await state.clear()
        await message.reply(f"⚠️ 老师「{teacher['display_name']}」已停用，无法提交评价。")
        return
    if status == "rate_limited":
        await state.clear()
        await message.reply(f"⚠️ {extra['reason']}")
        return
    if status == "need_subscribe":
        lines = ["⚠️ 提交评价前请先加入：\n"]
        for it in extra["missing"]:
            lines.append(f"📺 {it['display_name']}")
        lines.append("\n加入后回到主菜单重新点 [📝 写评价]。")
        await state.clear()
        await message.answer(
            "\n".join(lines),
            reply_markup=review_subscribe_links_kb(extra["missing"]),
            disable_web_page_preview=True,
        )
        return
    # status == "ok" — start_review_flow 已设好 state（intent 或 card）；
    # 用 dispatcher 自动根据 state 渲染 intent 屏或卡片屏（2026-05-21）
    from bot.handlers.review_card import render_card_or_intent
    await render_card_or_intent(message, state, via_edit=False)


@router.message(F.text == "/cancel", WriteReviewLookupStates())
async def cmd_cancel_write_review_lookup(message: types.Message, state: FSMContext):
    await state.clear()
    # 此状态下尚未选老师，kb 不传 teacher_id
    await message.answer(
        "❌ 已取消写评价。",
        reply_markup=review_cancelled_kb(),
    )


# ============ 老师详情页 [📝 写评价] callback ============

@router.callback_query(F.data.startswith("review:start:"))
async def cb_review_start(callback: types.CallbackQuery, state: FSMContext):
    """[📝 写评价] callback 入口（老师详情页按钮）

    校验顺序：teacher active → 限频 → 必关频道。
    通过后进入 Step B（上传约课截图）。
    """
    try:
        teacher_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    user_id = callback.from_user.id

    status, extra = await start_review_flow(
        callback.bot, callback.message.chat.id, user_id, teacher_id, state,
    )
    if status == "not_found":
        await callback.answer("该老师不存在", show_alert=True)
        return
    if status == "inactive":
        await callback.answer("该老师已停用，无法提交评价", show_alert=True)
        return
    if status == "rate_limited":
        await callback.answer(extra["reason"], show_alert=True)
        return
    if status == "need_subscribe":
        lines = ["⚠️ 提交评价前请先加入：\n"]
        for it in extra["missing"]:
            lines.append(f"📺 {it['display_name']}")
        lines.append("\n加入后回到老师详情页重新点 [📝 写评价]。")
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=review_subscribe_links_kb(extra["missing"]),
            disable_web_page_preview=True,
        )
        await callback.answer()
        return

    # status == "ok" — 由 dispatcher 决定渲染 intent 屏还是卡片屏（2026-05-21）
    from bot.handlers.review_card import render_card_or_intent
    await render_card_or_intent(callback.message, state, via_edit=True)
    await callback.answer()


# ============ 通用取消 ============

async def _cancel_with_kb(state: FSMContext) -> tuple[str, "InlineKeyboardMarkup | None"]:
    """读 teacher_id（如有）→ 清 state → 返回 (文案, kb)"""
    data = await state.get_data()
    tid = data.get("teacher_id")
    await state.clear()
    try:
        tid_int = int(tid) if tid is not None else None
    except (TypeError, ValueError):
        tid_int = None
    text = "❌ 已取消评价。"
    return text, review_cancelled_kb(tid_int)


@router.callback_query(F.data == "review:cancel")
async def cb_review_cancel(callback: types.CallbackQuery, state: FSMContext):
    text, kb = await _cancel_with_kb(state)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer("已取消")


