"""用户评价提交 12 步 FSM（Phase 9.3）

入口：teacher_detail [📝 写评价] → callback review:start:<teacher_id>
本 phase 仅按钮入口（teacher_id 已知）；Step A 选老师留给 9.5。

流程：
    校验老师 active + 限频 + 必关频道
    → Step B 上传约课截图 → Step C 上传手势照片
    → Step 1 评级 → Step 2-7 六维评分 → Step 8 综合 → Step 9 过程描述
    → 确认页（含 11 个修改跳回按钮）→ submit
    → DB create_teacher_review + add_user_tag(评论型用户)

每步发 /cancel 中止。
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from bot.database import (
    get_teacher,
    get_teacher_by_name,
    create_teacher_review,
    count_recent_user_reviews,
    count_recent_user_teacher_reviews,
    add_user_tag,
    compute_reimbursement_amount,
    get_config,
    get_user_total_points,
    get_user_review_stats,
    list_user_reviews_paged,
    count_user_reviews,
    get_teachers_by_ids,
    parse_review_score,
    REVIEW_DIMENSIONS,
    REVIEW_RATINGS,
    REVIEW_SCORE_QUICK_BUTTONS_FOR_DIM,
    REVIEW_SCORE_QUICK_BUTTONS_FOR_OVERALL,
    REVIEW_SUMMARY_MIN_LEN,
    REVIEW_SUMMARY_MAX_LEN,
    REVIEW_RATE_LIMIT_PER_TEACHER_24H,
    REVIEW_RATE_LIMIT_PER_USER_DAY,
    REVIEW_RATE_LIMIT_PER_USER_60S,
)
from bot.keyboards.user_kb import (
    review_cancel_kb,
    review_cancelled_kb,
    review_subscribe_links_kb,
    review_rating_kb,
    review_reimbursement_choice_kb,
    review_score_kb,
    review_summary_skip_cancel_kb,
    review_confirm_kb,
    user_reviews_home_kb,
)
from bot.states.teacher_states import (
    ReviewSubmitStates,
    UserReviewsHomeStates,
    WriteReviewLookupStates,
)
from bot.utils.required_channels import check_user_subscribed

logger = logging.getLogger(__name__)

router = Router(name="review_submit")


# 6 维 + 综合 的 (dim_key, FSM state, score_column, label) 元数据
# 顺序遵循 spec §2.3 评分内容
_SCORE_FLOW: list[dict] = [
    {"key": "humanphoto",  "state": ReviewSubmitStates.waiting_score_humanphoto,
     "column": "score_humanphoto", "label": "🎨 人照评分（照片真实度）"},
    {"key": "appearance",  "state": ReviewSubmitStates.waiting_score_appearance,
     "column": "score_appearance", "label": "颜值评分"},
    {"key": "body",        "state": ReviewSubmitStates.waiting_score_body,
     "column": "score_body", "label": "身材评分"},
    {"key": "service",     "state": ReviewSubmitStates.waiting_score_service,
     "column": "score_service", "label": "服务评分"},
    {"key": "attitude",    "state": ReviewSubmitStates.waiting_score_attitude,
     "column": "score_attitude", "label": "态度评分"},
    {"key": "environment", "state": ReviewSubmitStates.waiting_score_environment,
     "column": "score_environment", "label": "环境评分"},
]
_STEP_BY_KEY: dict[str, dict] = {s["key"]: s for s in _SCORE_FLOW}


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
    # status == "ok" — start_review_flow 已设好 CardReviewStates.card；渲染卡片
    from bot.handlers.review_card import render_card
    await render_card(message, state, via_edit=False)


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

    # status == "ok" — 卡片渲染
    from bot.handlers.review_card import render_card
    await render_card(callback.message, state, via_edit=True)
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


@router.message(F.text == "/cancel", ReviewSubmitStates())
async def cmd_cancel(message: types.Message, state: FSMContext):
    text, kb = await _cancel_with_kb(state)
    await message.answer(text, reply_markup=kb)


# ============ Step 1：媒体组（约课截图 + 手势照片合并） ============
#
# 用户连发 2 张图（媒体组或一张一张）：
#   第 1 张 → booking_screenshot_file_id
#   第 2 张 → gesture_photo_file_id
# 收齐 2 张后自动进入 Step 2 评级。

import asyncio as _asyncio
_EVIDENCE_REPLY_TASKS: dict[int, "_asyncio.Task"] = {}


@router.message(ReviewSubmitStates.waiting_evidence_media, F.photo)
async def step_evidence_media(message: types.Message, state: FSMContext):
    """收图：累加，前 2 张分别作为约课截图 / 手势照片"""
    data = await state.get_data()
    files: list = list(data.get("_evidence_files") or [])
    if len(files) >= 2:
        if message.media_group_id is None:
            await message.reply("⚠️ 已收到 2 张证据照片，请耐心等待跳到 Step 2。")
        return  # 媒体组多余张数静默忽略
    files.append(message.photo[-1].file_id)
    await state.update_data(_evidence_files=files)

    # 收齐 2 张 → 进 Step 2
    if len(files) >= 2:
        # 清除可能还在 schedule 的 debounce task
        old = _EVIDENCE_REPLY_TASKS.pop(message.chat.id, None)
        if old and not old.done():
            old.cancel()
        await state.update_data(
            booking_screenshot_file_id=files[0],
            gesture_photo_file_id=files[1],
        )
        if data.get("jump_back"):
            await state.update_data(jump_back=False)
            await message.reply("✅ 2 张证据照片已收到。")
            await _enter_confirm(message, state)
            return
        await message.reply("✅ 2 张证据照片已收到。")
        await _enter_rating(message, state)
        return

    # 还差 1 张
    if message.media_group_id is None:
        # 单张上传 → 立即提示
        await message.reply(f"✅ 已收到第 {len(files)}/2 张，请继续上传剩余照片。")
        return

    # 媒体组中间张 → debounce 后提示（避免 N 张图刷屏）
    chat_id = message.chat.id
    old = _EVIDENCE_REPLY_TASKS.get(chat_id)
    if old and not old.done():
        old.cancel()
    bot_ref = message.bot

    async def _debounced_reply():
        try:
            await _asyncio.sleep(0.6)
            d = await state.get_data()
            cur_files = d.get("_evidence_files") or []
            n = len(cur_files)
            if n >= 2:
                return
            await bot_ref.send_message(
                chat_id=chat_id,
                text=f"✅ 已收到 {n}/2 张，请继续上传剩余照片。",
            )
        except _asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            _EVIDENCE_REPLY_TASKS.pop(chat_id, None)

    _EVIDENCE_REPLY_TASKS[chat_id] = _asyncio.create_task(_debounced_reply())


@router.message(ReviewSubmitStates.waiting_evidence_media)
async def step_evidence_invalid(message: types.Message):
    text = (message.text or "").strip()
    if text == "/cancel":
        # /cancel 走 cmd_cancel 的全局 handler，这里防御性 echo
        return
    await message.reply("❌ 请发送图片（约课截图 + 手势照片 共 2 张，支持媒体组）。")


# ============ Step 2：评级（按钮 + 文本均可） ============

async def _enter_rating(msg_or_cb, state: FSMContext, *, via_edit: bool = False):
    """Step 2 评级；若 state.data 中已存在 rating（主页预选）则跳过此步直接进 Step 3"""
    data = await state.get_data()
    pre = data.get("rating")
    if pre and pre in {r["key"] for r in REVIEW_RATINGS} and not data.get("jump_back"):
        # 主页已预选 → 静默直跳 Step 3
        label = next(r["label"] for r in REVIEW_RATINGS if r["key"] == pre)
        try:
            await _extract_msg(msg_or_cb).answer(
                f"⏭ 已使用主页预选评级 = {label}，自动进入 Step 3。"
            )
        except Exception:
            pass
        await _enter_score_step(
            _extract_msg(msg_or_cb), state, "humanphoto", via_edit=False,
        )
        return
    await state.set_state(ReviewSubmitStates.waiting_rating)
    text = (
        "[Step 2/10] 评级（必填）\n\n"
        "请选择对老师的整体印象（也可直接输入文字「好评 / 中评 / 差评」）："
    )
    await _show(msg_or_cb, text, review_rating_kb(), via_edit=via_edit)


async def _accept_rating(msg_or_cb, state: FSMContext, rating_key: str, *, via_edit: bool):
    """评级被选定（按钮或文本）→ 落数据，进入下一步或回确认页"""
    await state.update_data(rating=rating_key)
    label = next(r["label"] for r in REVIEW_RATINGS if r["key"] == rating_key)
    data = await state.get_data()
    if data.get("jump_back"):
        await state.update_data(jump_back=False)
        await _ack(msg_or_cb, f"✅ 评级 = {label}")
        await _enter_confirm(_extract_msg(msg_or_cb), state, via_edit=via_edit)
        return
    await _ack(msg_or_cb, f"✅ 评级 = {label}")
    await _enter_score_step(_extract_msg(msg_or_cb), state, "humanphoto", via_edit=via_edit)


@router.callback_query(F.data.startswith("review:rating:"), ReviewSubmitStates.waiting_rating)
async def cb_rating(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("参数错误", show_alert=True)
        return
    rating_key = parts[2]
    valid = {r["key"] for r in REVIEW_RATINGS}
    if rating_key not in valid:
        await callback.answer("非法评级", show_alert=True)
        return
    await _accept_rating(callback, state, rating_key, via_edit=True)


@router.message(ReviewSubmitStates.waiting_rating)
async def msg_rating(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel(message, state)
    norm = text.lstrip("👍😐👎").strip()
    rating_key = None
    for r in REVIEW_RATINGS:
        if norm == r["label"] or text == r["label"] or text == f"{r['emoji']} {r['label']}":
            rating_key = r["key"]
            break
    if rating_key is None:
        valid = " / ".join(r["label"] for r in REVIEW_RATINGS)
        await message.reply(f"❌ 评级需输入：{valid}（或点上方按钮）")
        return
    await _accept_rating(message, state, rating_key, via_edit=False)


# ============ Step 3-8：6 维评分（文本输入，无按钮） ============

async def _enter_score_step(msg, state: FSMContext, dim_key: str, *, via_edit: bool = False):
    step = _STEP_BY_KEY[dim_key]
    await state.set_state(step["state"])
    # 6 维顺序对应 Step 3-8（评级是 Step 2）
    step_num = next(i for i, s in enumerate(_SCORE_FLOW, start=3) if s["key"] == dim_key)
    text = (
        f"[Step {step_num}/10] {step['label']}（必填）\n\n"
        "请**直接输入数字**打分 0.0 - 10.0（最多 1 位小数）。"
    )
    await _show(msg, text, review_cancel_kb(), via_edit=via_edit)


@router.message(StateFilter(
    ReviewSubmitStates.waiting_score_humanphoto,
    ReviewSubmitStates.waiting_score_appearance,
    ReviewSubmitStates.waiting_score_body,
    ReviewSubmitStates.waiting_score_service,
    ReviewSubmitStates.waiting_score_attitude,
    ReviewSubmitStates.waiting_score_environment,
))
async def msg_dim_score(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel(message, state)
    score = parse_review_score(text)
    if score is None:
        await message.reply("❌ 请输入 0-10 的数字（最多 1 位小数）。")
        return
    cur_state = await state.get_state()
    dim_key: Optional[str] = None
    for s in _SCORE_FLOW:
        if cur_state == s["state"].state:
            dim_key = s["key"]
            break
    if dim_key is None:
        return
    await _record_score(message, state, dim_key, score, via_edit=False)


def _compute_overall_avg(data: dict) -> float:
    """从 state.data 取 6 维分数算均值；返回保留 1 位小数。

    任一维度缺失时（不应该发生）回退到 0.0。
    """
    try:
        vals = [float(data.get(s["column"])) for s in _SCORE_FLOW]
    except (TypeError, ValueError):
        return 0.0
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 1)


async def _record_score(
    msg_or_cb, state: FSMContext, dim_key: str, score: float, *, via_edit: bool,
):
    column = _STEP_BY_KEY[dim_key]["column"]
    await state.update_data(**{column: score})
    data = await state.get_data()
    if data.get("jump_back"):
        await state.update_data(jump_back=False)
        # 跳回模式：单维改完即回确认页；同时重新计算 overall
        overall = _compute_overall_avg(await state.get_data())
        await state.update_data(overall_score=overall)
        await _ack(msg_or_cb, f"✅ 已更新「{_STEP_BY_KEY[dim_key]['label']}」= {score}（综合自动 = {overall}）")
        await _enter_confirm(_extract_msg(msg_or_cb), state, via_edit=via_edit)
        return
    idx = next(i for i, s in enumerate(_SCORE_FLOW) if s["key"] == dim_key)
    if idx + 1 < len(_SCORE_FLOW):
        next_key = _SCORE_FLOW[idx + 1]["key"]
        await _ack(msg_or_cb, f"✅ {_STEP_BY_KEY[dim_key]['label']} = {score}")
        await _enter_score_step(_extract_msg(msg_or_cb), state, next_key, via_edit=via_edit)
    else:
        # 6 维全部完成 → 综合 = 平均；直接进 Step 9 过程描述
        overall = _compute_overall_avg(await state.get_data())
        await state.update_data(overall_score=overall)
        await _ack(
            msg_or_cb,
            f"✅ {_STEP_BY_KEY[dim_key]['label']} = {score}\n"
            f"📊 综合评分（自动取 6 维平均）= {overall}"
        )
        await _enter_summary(_extract_msg(msg_or_cb), state, via_edit=via_edit)


# 综合评分自动计算（_compute_overall_avg）；不再有 user-facing 输入步


# ============ Step 9：过程描述（必填） ============

async def _enter_summary(msg, state: FSMContext, *, via_edit: bool = False):
    await state.set_state(ReviewSubmitStates.waiting_summary)
    text = (
        f"[Step 9/10] 📝 过程描述（**必填**，{REVIEW_SUMMARY_MIN_LEN}-{REVIEW_SUMMARY_MAX_LEN} 字）\n\n"
        "请用一句话描述整体感受 / 过程，会显示在评论区。"
    )
    await _show(msg, text, review_cancel_kb(), via_edit=via_edit)


@router.message(ReviewSubmitStates.waiting_summary)
async def msg_summary(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel(message, state)
    if not text:
        await message.reply("❌ 过程描述必填，请输入文字。")
        return
    if len(text) < REVIEW_SUMMARY_MIN_LEN or len(text) > REVIEW_SUMMARY_MAX_LEN:
        await message.reply(
            f"❌ 字数需在 {REVIEW_SUMMARY_MIN_LEN}-{REVIEW_SUMMARY_MAX_LEN} 之间，当前 {len(text)} 字。"
        )
        return
    await state.update_data(summary=text)
    data = await state.get_data()
    if data.get("jump_back"):
        await state.update_data(jump_back=False)
        await _enter_confirm(message, state)
        return
    await _enter_reimbursement_step(message, state, via_edit=False)


# ============ 报销意愿（条件可见）============


async def _enter_reimbursement_step(
    msg, state: FSMContext, *, via_edit: bool = False,
):
    """检查是否满足报销资格 + 功能开关状态

    资格：user.total_points >= reimbursement_min_points (config，默认 5)
         AND compute_reimbursement_amount(teacher.price) > 0

    功能 OFF：满足资格也不显示选择步骤（静默），但在 state.data 写
        _reimburse_silent_queue=1 标记，审核通过时仍创建 status='queued' 记录
        （admin 在「报销名单」可查看；不进 pending 审批队列）。
    功能 ON：满足资格 → 显示询问；不满足 → 跳过。

    user_id 来源（私聊）：msg.chat.id（与用户 user_id 相同；callback.message 时
    msg.from_user 是 bot，不能用）。
    """
    data = await state.get_data()
    teacher_id = int(data.get("teacher_id"))
    teacher = await get_teacher(teacher_id)
    amount = compute_reimbursement_amount(teacher.get("price") if teacher else None)

    min_pts_raw = await get_config("reimbursement_min_points")
    try:
        min_pts = int(min_pts_raw) if min_pts_raw else 5
    except (TypeError, ValueError):
        min_pts = 5

    user_id = msg.chat.id if msg.chat else 0
    points = await get_user_total_points(int(user_id))

    feature_enabled = (await get_config("reimbursement_feature_enabled")) == "1"

    if amount <= 0 or points < min_pts:
        # 不满足资格：直接进确认页（request_reimbursement=0 不创建任何记录）
        await state.update_data(request_reimbursement=0, _reimburse_amount=0)
        await _enter_confirm(msg, state, via_edit=via_edit)
        return

    if not feature_enabled:
        # 功能关闭：满足资格 → 静默录入（request_reimbursement=2 → status='queued'）
        await state.update_data(
            request_reimbursement=2,
            _reimburse_amount=amount,
        )
        await _enter_confirm(msg, state, via_edit=via_edit)
        return

    await state.set_state(ReviewSubmitStates.waiting_reimbursement_choice)
    await state.update_data(_reimburse_amount=amount)
    text = (
        "💰 报销申请\n"
        "━━━━━━━━━━━━━━━\n"
        f"你当前积分：{points}（门槛 {min_pts}）\n"
        f"本次可申请报销：{amount} 元（基于老师价位）\n"
        "━━━━━━━━━━━━━━━\n\n"
        "是否对本条评价申请报销？\n"
        "（评价审核通过后由超管二次审核）"
    )
    await _show(msg, text, review_reimbursement_choice_kb(amount), via_edit=via_edit)


@router.callback_query(
    F.data == "review:reimburse_yes",
    ReviewSubmitStates.waiting_reimbursement_choice,
)
async def cb_review_reimburse_yes(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(request_reimbursement=1)
    await _enter_confirm(callback.message, state, via_edit=True)
    await callback.answer("已勾选申请报销")


@router.callback_query(
    F.data == "review:reimburse_no",
    ReviewSubmitStates.waiting_reimbursement_choice,
)
async def cb_review_reimburse_no(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(request_reimbursement=0)
    await _enter_confirm(callback.message, state, via_edit=True)
    await callback.answer("已选择不申请")


# ============ 确认页 ============

async def _enter_confirm(msg, state: FSMContext, *, via_edit: bool = False):
    await state.set_state(ReviewSubmitStates.waiting_confirm)
    data = await state.get_data()
    teacher = await get_teacher(int(data["teacher_id"]))
    teacher_name = teacher["display_name"] if teacher else f"#{data['teacher_id']}"

    rating_meta = {r["key"]: r for r in REVIEW_RATINGS}.get(data.get("rating"), {})
    rating_str = (
        f"{rating_meta.get('emoji', '')} {rating_meta.get('label', data.get('rating', '?'))}"
    )
    overall = data.get("overall_score", "?")
    lines = [
        "📋 你的报告预览：",
        "━━━━━━━━━━━━━━━",
        f"老师：{teacher_name}",
        f"📸 约课截图：{'✅ 已上传' if data.get('booking_screenshot_file_id') else '❌ 缺'}",
        f"✋ 现场手势：{'✅ 已上传' if data.get('gesture_photo_file_id') else '❌ 缺'}",
        "",
        f"评级：{rating_str} · 🎯 综合 {overall}（自动 = 6 维平均）",
        "",
        f"🎨 人照：{data.get('score_humanphoto', '?')}",
        f"颜值：{data.get('score_appearance', '?')}",
        f"身材：{data.get('score_body', '?')}",
        f"服务：{data.get('score_service', '?')}",
        f"态度：{data.get('score_attitude', '?')}",
        f"环境：{data.get('score_environment', '?')}",
    ]
    if data.get("summary"):
        lines.append("")
        lines.append(f"📝 过程：{data['summary']}")
    # 报销申请状态
    req_reimb = int(data.get("request_reimbursement") or 0)
    reimb_amount = int(data.get("_reimburse_amount") or 0)
    # req=2 = 功能关闭静默录入 → 不向用户显示报销相关信息
    if reimb_amount > 0 and req_reimb in (0, 1):
        lines.append("")
        if req_reimb == 1:
            lines.append(f"💰 报销申请：✅ 是，{reimb_amount} 元（待超管审核）")
        else:
            lines.append("💰 报销申请：❌ 否")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("确认无误点 [✅ 提交审核]，或修改某项。")

    await _show(msg, "\n".join(lines), review_confirm_kb(), via_edit=via_edit)


# ============ 修改某项跳回 ============

_EDIT_DESTINATION: dict[str, dict] = {
    "evidence":    {"state": ReviewSubmitStates.waiting_evidence_media,
                    "prompt": "请重新上传 2 张证据照片（约课截图 + 手势照片，支持媒体组）。",
                    "kind": "photo"},
    "rating":      {"state": ReviewSubmitStates.waiting_rating,
                    "prompt": "请重新输入评级（好评 / 中评 / 差评）：",
                    "kind": "rating"},
    "humanphoto":  {"state": ReviewSubmitStates.waiting_score_humanphoto,
                    "prompt": "请重新输入 🎨 人照评分（0-10）：",
                    "kind": "score", "dim_key": "humanphoto"},
    "appearance":  {"state": ReviewSubmitStates.waiting_score_appearance,
                    "prompt": "请重新输入颜值评分（0-10）：",
                    "kind": "score", "dim_key": "appearance"},
    "body":        {"state": ReviewSubmitStates.waiting_score_body,
                    "prompt": "请重新输入身材评分（0-10）：",
                    "kind": "score", "dim_key": "body"},
    "service":     {"state": ReviewSubmitStates.waiting_score_service,
                    "prompt": "请重新输入服务评分（0-10）：",
                    "kind": "score", "dim_key": "service"},
    "attitude":    {"state": ReviewSubmitStates.waiting_score_attitude,
                    "prompt": "请重新输入态度评分（0-10）：",
                    "kind": "score", "dim_key": "attitude"},
    "environment": {"state": ReviewSubmitStates.waiting_score_environment,
                    "prompt": "请重新输入环境评分（0-10）：",
                    "kind": "score", "dim_key": "environment"},
    # 综合评分自动 = 6 维平均，无独立编辑项
    "summary":     {"state": ReviewSubmitStates.waiting_summary,
                    "prompt": "请重新输入过程描述（必填）：",
                    "kind": "summary"},
}


@router.callback_query(F.data.startswith("review:edit:"), ReviewSubmitStates.waiting_confirm)
async def cb_review_edit(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) != 3 or parts[2] not in _EDIT_DESTINATION:
        await callback.answer("参数错误", show_alert=True)
        return
    dest = _EDIT_DESTINATION[parts[2]]
    if parts[2] == "evidence":
        await state.update_data(_evidence_files=[])
    await state.set_state(dest["state"])
    await state.update_data(jump_back=True)
    # 评级跳回时用按钮键盘；其它（证据/评分/总结）用 cancel 键盘
    kb = review_rating_kb() if dest["kind"] == "rating" else review_cancel_kb()
    await callback.message.edit_text(dest["prompt"], reply_markup=kb)
    await callback.answer()


# ============ 提交 ============

@router.callback_query(F.data == "review:submit", ReviewSubmitStates.waiting_confirm)
async def cb_review_submit(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    teacher_id = data.get("teacher_id")
    user_id = callback.from_user.id

    # 数据完整性
    for f in ("teacher_id", "booking_screenshot_file_id", "gesture_photo_file_id",
              "rating", "overall_score"):
        if data.get(f) is None:
            await callback.answer(f"缺字段：{f}，请补全", show_alert=True)
            return
    for d in REVIEW_DIMENSIONS:
        if data.get(d["column"]) is None:
            await callback.answer(f"缺评分：{d['label']}", show_alert=True)
            return

    # 提交前再做一次限频（防止用户停留确认页过久）
    limit_msg = await _check_rate_limit(user_id, int(teacher_id))
    if limit_msg:
        await state.clear()
        await callback.message.edit_text(f"❌ {limit_msg}")
        await callback.answer(limit_msg, show_alert=True)
        return

    review_data = {
        "teacher_id": int(teacher_id),
        "user_id": user_id,
        "booking_screenshot_file_id": data["booking_screenshot_file_id"],
        "gesture_photo_file_id": data["gesture_photo_file_id"],
        "rating": data["rating"],
        "score_humanphoto": data["score_humanphoto"],
        "score_appearance": data["score_appearance"],
        "score_body": data["score_body"],
        "score_service": data["score_service"],
        "score_attitude": data["score_attitude"],
        "score_environment": data["score_environment"],
        "overall_score": data["overall_score"],
        "summary": data.get("summary"),
        "request_reimbursement": int(data.get("request_reimbursement") or 0),
    }
    review_id = await create_teacher_review(review_data)
    if review_id is None:
        await callback.answer("⚠️ 提交失败，请稍后再试", show_alert=True)
        return

    # 评价者画像 +"评论型用户"
    try:
        await add_user_tag(user_id, "评论型用户", score_delta=1, source="review")
    except Exception as e:
        logger.warning("add_user_tag 失败 user=%s: %s", user_id, e)

    # Phase 9.4.3：推送给所有超管（不阻塞用户响应；失败仅 logger）
    try:
        import asyncio as _asyncio
        from bot.utils.rreview_notify import notify_super_admins_new_review
        _asyncio.create_task(
            notify_super_admins_new_review(callback.bot, review_id)
        )
    except Exception as e:
        logger.warning("notify_super_admins schedule 失败 review=%s: %s", review_id, e)

    await state.clear()
    await callback.message.edit_text(
        f"✅ 评价 #{review_id} 已提交，等待管理员审核。\n"
        "通常 24 小时内有结果，审核结果会私聊通知你。"
    )
    await callback.answer("已提交")


# ============ 限频 ============

async def _check_rate_limit(user_id: int, teacher_id: int) -> Optional[str]:
    """检查 3 项限频；返回 None 表示通过，否则返回中文拒绝原因"""
    # 60s 内已提交 1 条
    n_60s = await count_recent_user_reviews(user_id, 60)
    if n_60s >= REVIEW_RATE_LIMIT_PER_USER_60S:
        return "提交太频繁，请 1 分钟后再试"
    # 24h 内对同老师 ≥ 3 条
    n_teacher = await count_recent_user_teacher_reviews(user_id, teacher_id, 86400)
    if n_teacher >= REVIEW_RATE_LIMIT_PER_TEACHER_24H:
        return f"今天该老师已超出限制（{REVIEW_RATE_LIMIT_PER_TEACHER_24H} 条/24h）"
    # 24h 全平台 ≥ 10 条
    n_day = await count_recent_user_reviews(user_id, 86400)
    if n_day >= REVIEW_RATE_LIMIT_PER_USER_DAY:
        return f"今天已超出全平台限制（{REVIEW_RATE_LIMIT_PER_USER_DAY} 条/24h）"
    return None


# ============ 内部辅助 ============

def _extract_msg(msg_or_cb) -> types.Message:
    if isinstance(msg_or_cb, types.CallbackQuery):
        return msg_or_cb.message
    return msg_or_cb


async def _ack(msg_or_cb, text: str):
    """对当前事件做 ack：callback 用 answer，message 用 reply"""
    if isinstance(msg_or_cb, types.CallbackQuery):
        try:
            await msg_or_cb.answer(text)
        except Exception:
            pass
    elif isinstance(msg_or_cb, types.Message):
        try:
            await msg_or_cb.reply(text)
        except Exception:
            pass


async def _show(msg, text: str, kb, *, via_edit: bool):
    if via_edit:
        try:
            await msg.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await msg.answer(text, reply_markup=kb)
