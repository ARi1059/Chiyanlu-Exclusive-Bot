"""卡片驱动评价 FSM（2026-05-18 Phase 2）

中心「评价卡片」展示老师 + 已填 / 未填字段；用户任选字段按钮进入填写子状态，
填完返回卡片。无强制顺序。

主要差异 vs ReviewSubmitStates 线性 FSM：
- 状态机：CardReviewStates.card (idle) + 9 个 editing_X 子状态
- 任意点 [✓ 字段] 进入对应 editing_X；填完返回卡片
- 提交时 2 选 1：[😟 匿名提交] / [😎 默认提交]
- 提交后走现有报销询问逻辑 → 落库 → 通知超管

主要复用：
- bot.handlers.review_submit._check_rate_limit / _compute_overall_avg
- bot.utils.required_channels.check_user_subscribed
- bot.database.compute_reimbursement_amount / get_config / get_user_total_points
"""
from __future__ import annotations

import asyncio as _asyncio
import logging
from typing import Optional

from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from bot.database import (
    add_user_tag,
    compute_reimbursement_amount,
    count_recent_user_reviews,
    count_recent_user_teacher_reviews,
    create_teacher_review,
    get_config,
    get_teacher,
    get_user_total_points,
    parse_review_score,
    REVIEW_DIMENSIONS,
    REVIEW_RATINGS,
    REVIEW_SUMMARY_MAX_LEN,
    REVIEW_SUMMARY_MIN_LEN,
    REVIEW_RATE_LIMIT_PER_TEACHER_24H,
    REVIEW_RATE_LIMIT_PER_USER_60S,
    REVIEW_RATE_LIMIT_PER_USER_DAY,
)
from bot.keyboards.user_kb import (
    review_card_edit_cancel_kb,
    review_card_kb,
    review_card_rating_kb,
    review_card_reimburse_kb,
    review_cancelled_kb,
    review_subscribe_links_kb,
)
from bot.states.teacher_states import CardReviewStates
from bot.utils.required_channels import check_user_subscribed

logger = logging.getLogger(__name__)

router = Router(name="review_card")


# 6 维 dim_key → (FSM state, score 列, label)
_DIM_META: dict[str, dict] = {
    "humanphoto":  {"state": CardReviewStates.editing_humanphoto,
                    "column": "score_humanphoto", "label": "🎨 人照"},
    "appearance":  {"state": CardReviewStates.editing_appearance,
                    "column": "score_appearance", "label": "💅 颜值"},
    "body":        {"state": CardReviewStates.editing_body,
                    "column": "score_body",       "label": "💃 身材"},
    "service":     {"state": CardReviewStates.editing_service,
                    "column": "score_service",    "label": "🛎 服务"},
    "attitude":    {"state": CardReviewStates.editing_attitude,
                    "column": "score_attitude",   "label": "😊 态度"},
    "environment": {"state": CardReviewStates.editing_environment,
                    "column": "score_environment", "label": "🏠 环境"},
}
_EDITING_DIM_STATES: list = [v["state"] for v in _DIM_META.values()]
_DIM_BY_STATE: dict[str, str] = {v["state"].state: k for k, v in _DIM_META.items()}


# ============ 卡片渲染 ============


def _compute_overall_avg(data: dict) -> float:
    """从 state.data 取 6 维分数算均值；返回保留 1 位小数"""
    cols = [meta["column"] for meta in _DIM_META.values()]
    try:
        vals = [float(data.get(c)) for c in cols if data.get(c) is not None]
    except (TypeError, ValueError):
        return 0.0
    if len(vals) != len(cols):
        return 0.0
    return round(sum(vals) / len(vals), 1)


async def _build_card_text(state: FSMContext) -> str:
    data = await state.get_data()
    teacher_id = int(data.get("teacher_id") or 0)
    teacher = await get_teacher(teacher_id) if teacher_id else None
    tname = teacher["display_name"] if teacher else f"#{teacher_id}"
    rating_meta = {r["key"]: r for r in REVIEW_RATINGS}

    booking = data.get("booking_screenshot_file_id")
    gesture = data.get("gesture_photo_file_id")
    evidence_count = sum(1 for v in (booking, gesture) if v)

    rating_key = data.get("rating")
    if rating_key and rating_key in rating_meta:
        r_meta = rating_meta[rating_key]
        rating_str = f"{r_meta['emoji']} {r_meta['label']}"
    else:
        rating_str = "（未填）"

    def _dim(key: str) -> str:
        col = _DIM_META[key]["column"]
        v = data.get(col)
        return f"{float(v):.1f}" if v is not None else "（未填）"

    summary = data.get("summary") or "（未填）"
    if isinstance(summary, str) and len(summary) > 40:
        summary = summary[:40] + "…"

    overall = _compute_overall_avg(data)
    overall_str = f"{overall:.1f}（6 维平均）" if overall > 0 else "（待 6 维齐全后自动计算）"

    anon = int(data.get("anonymous") or 0)
    anon_str = "😟 匿名" if anon == 1 else "😎 默认（显示用户）"

    lines = [
        "📋 评价卡片（点按钮逐项填写，无顺序要求）",
        "━━━━━━━━━━━━━━━",
        f"老师：{tname}",
        f"🖼 出击证明：{evidence_count}/2 张" + ("（约课截图 + 现场手势）" if evidence_count < 2 else " ✅"),
        f"⭐ 评级：{rating_str}",
        "",
        "📊 6 维评分（0-10）：",
        f"  🎨 人照：{_dim('humanphoto')}     💅 颜值：{_dim('appearance')}",
        f"  💃 身材：{_dim('body')}     🛎 服务：{_dim('service')}",
        f"  😊 态度：{_dim('attitude')}     🏠 环境：{_dim('environment')}",
        f"🎯 综合：{overall_str}",
        "",
        f"📝 过程描述：{summary}",
        "",
        f"提交模式：{anon_str}（点 [😟匿名] 或 [😎默认] 即提交）",
        "━━━━━━━━━━━━━━━",
        "💡 字段标 ✓ 表示已填；全填齐后才能提交。",
    ]
    return "\n".join(lines)


async def render_card(
    target_msg: types.Message, state: FSMContext, *, via_edit: bool = True,
):
    """渲染卡片视图（设置状态 + 编辑 / 发送消息）"""
    await state.set_state(CardReviewStates.card)
    text = await _build_card_text(state)
    data = await state.get_data()
    kb = review_card_kb(data)
    try:
        if via_edit:
            await target_msg.edit_text(text, reply_markup=kb)
        else:
            await target_msg.answer(text, reply_markup=kb)
    except Exception:
        try:
            await target_msg.answer(text, reply_markup=kb)
        except Exception as e:
            logger.warning("render_card 失败: %s", e)


# ============ 入口 ============


async def _check_rate_limit(user_id: int, teacher_id: int) -> Optional[str]:
    n_60s = await count_recent_user_reviews(user_id, 60)
    if n_60s >= REVIEW_RATE_LIMIT_PER_USER_60S:
        return "提交太频繁，请 1 分钟后再试"
    n_teacher = await count_recent_user_teacher_reviews(user_id, teacher_id, 86400)
    if n_teacher >= REVIEW_RATE_LIMIT_PER_TEACHER_24H:
        return f"今天该老师已超出限制（{REVIEW_RATE_LIMIT_PER_TEACHER_24H} 条/24h）"
    n_day = await count_recent_user_reviews(user_id, 86400)
    if n_day >= REVIEW_RATE_LIMIT_PER_USER_DAY:
        return f"今天已超出全平台限制（{REVIEW_RATE_LIMIT_PER_USER_DAY} 条/24h）"
    return None


async def start_card_review(
    bot,
    user_id: int,
    teacher_id: int,
    state: FSMContext,
    *,
    pre_rating: Optional[str] = None,
) -> tuple[str, Optional[dict]]:
    """卡片入口校验 + state 初始化（不发消息；调用方拿到 "ok" 后调 render_card）

    返回 ("ok"|"not_found"|"inactive"|"rate_limited"|"need_subscribe", extra)
    """
    teacher = await get_teacher(teacher_id)
    if not teacher:
        return "not_found", None
    if not teacher.get("is_active"):
        return "inactive", None

    limit_msg = await _check_rate_limit(user_id, teacher_id)
    if limit_msg:
        return "rate_limited", {"reason": limit_msg}

    ok, missing = await check_user_subscribed(bot, user_id)
    if not ok:
        return "need_subscribe", {"missing": missing}

    await state.set_state(CardReviewStates.card)
    init: dict = {"teacher_id": teacher_id, "anonymous": 0}
    if pre_rating and pre_rating in {r["key"] for r in REVIEW_RATINGS}:
        init["rating"] = pre_rating
    await state.set_data(init)
    return "ok", {"teacher": teacher}


# ============ 取消 ============


async def _cancel(state: FSMContext) -> tuple[str, "types.InlineKeyboardMarkup | None"]:
    data = await state.get_data()
    tid = data.get("teacher_id")
    await state.clear()
    try:
        tid_int = int(tid) if tid is not None else None
    except (TypeError, ValueError):
        tid_int = None
    return "❌ 已取消评价。", review_cancelled_kb(tid_int)


@router.callback_query(F.data == "card:cancel", StateFilter(
    CardReviewStates.card,
    CardReviewStates.editing_evidence,
    CardReviewStates.editing_rating,
    CardReviewStates.editing_humanphoto,
    CardReviewStates.editing_appearance,
    CardReviewStates.editing_body,
    CardReviewStates.editing_service,
    CardReviewStates.editing_attitude,
    CardReviewStates.editing_environment,
    CardReviewStates.editing_summary,
    CardReviewStates.waiting_reimbursement_choice,
))
async def cb_card_cancel(callback: types.CallbackQuery, state: FSMContext):
    text, kb = await _cancel(state)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer("已取消")


@router.message(F.text == "/cancel", StateFilter(
    CardReviewStates.card,
    CardReviewStates.editing_evidence,
    CardReviewStates.editing_rating,
    CardReviewStates.editing_humanphoto,
    CardReviewStates.editing_appearance,
    CardReviewStates.editing_body,
    CardReviewStates.editing_service,
    CardReviewStates.editing_attitude,
    CardReviewStates.editing_environment,
    CardReviewStates.editing_summary,
    CardReviewStates.waiting_reimbursement_choice,
))
async def msg_card_cancel(message: types.Message, state: FSMContext):
    text, kb = await _cancel(state)
    await message.answer(text, reply_markup=kb)


# ============ 字段进入子状态 ============


@router.callback_query(F.data.startswith("card:edit:"), CardReviewStates.card)
async def cb_card_edit(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split(":", 2)[-1]

    if field == "evidence":
        await state.set_state(CardReviewStates.editing_evidence)
        await state.update_data(_evidence_files=[])
        await callback.message.edit_text(
            "🖼 上传 2 张证据照片（约课截图 + 现场手势）。\n"
            "可一起作为媒体组发送，也可一张一张发；前 2 张被采纳，多余忽略。\n\n"
            "完成后会自动返回卡片。",
            reply_markup=review_card_edit_cancel_kb(),
        )
        await callback.answer()
        return

    if field == "rating":
        await state.set_state(CardReviewStates.editing_rating)
        await callback.message.edit_text(
            "⭐ 选择对老师的整体印象：",
            reply_markup=review_card_rating_kb(),
        )
        await callback.answer()
        return

    if field in _DIM_META:
        meta = _DIM_META[field]
        await state.set_state(meta["state"])
        await callback.message.edit_text(
            f"{meta['label']}：请直接输入数字打分 0.0 - 10.0（最多 1 位小数）。\n\n"
            "完成后会自动返回卡片。",
            reply_markup=review_card_edit_cancel_kb(),
        )
        await callback.answer()
        return

    if field == "summary":
        await state.set_state(CardReviewStates.editing_summary)
        await callback.message.edit_text(
            f"📝 过程描述（{REVIEW_SUMMARY_MIN_LEN}-{REVIEW_SUMMARY_MAX_LEN} 字）。\n\n"
            "请用一句话描述整体感受 / 过程，会显示在评论区。\n"
            "完成后会自动返回卡片。",
            reply_markup=review_card_edit_cancel_kb(),
        )
        await callback.answer()
        return

    await callback.answer("未知字段", show_alert=True)


@router.callback_query(F.data == "card:back", StateFilter(
    CardReviewStates.editing_evidence,
    CardReviewStates.editing_rating,
    CardReviewStates.editing_humanphoto,
    CardReviewStates.editing_appearance,
    CardReviewStates.editing_body,
    CardReviewStates.editing_service,
    CardReviewStates.editing_attitude,
    CardReviewStates.editing_environment,
    CardReviewStates.editing_summary,
))
async def cb_card_back(callback: types.CallbackQuery, state: FSMContext):
    await render_card(callback.message, state, via_edit=True)
    await callback.answer()


# ============ Evidence 子状态：媒体组照片 ============


_EVIDENCE_REPLY_TASKS: dict[int, "_asyncio.Task"] = {}


@router.message(CardReviewStates.editing_evidence, F.photo)
async def msg_card_evidence(message: types.Message, state: FSMContext):
    data = await state.get_data()
    files: list = list(data.get("_evidence_files") or [])
    if len(files) >= 2:
        if message.media_group_id is None:
            await message.reply("⚠️ 已收到 2 张，请稍候自动返回卡片。")
        return
    files.append(message.photo[-1].file_id)
    await state.update_data(_evidence_files=files)

    if len(files) >= 2:
        old = _EVIDENCE_REPLY_TASKS.pop(message.chat.id, None)
        if old and not old.done():
            old.cancel()
        await state.update_data(
            booking_screenshot_file_id=files[0],
            gesture_photo_file_id=files[1],
            _evidence_files=[],
        )
        await message.reply("✅ 2 张证据照片已收到，返回卡片。")
        await render_card(message, state, via_edit=False)
        return

    if message.media_group_id is None:
        await message.reply(f"✅ 已收到 {len(files)}/2 张，继续上传剩余照片。")
        return

    # 媒体组 debounce 提示
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
                text=f"✅ 已收到 {n}/2 张，继续上传剩余照片。",
            )
        except _asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            _EVIDENCE_REPLY_TASKS.pop(chat_id, None)

    _EVIDENCE_REPLY_TASKS[chat_id] = _asyncio.create_task(_debounced_reply())


@router.message(CardReviewStates.editing_evidence)
async def msg_card_evidence_invalid(message: types.Message):
    text = (message.text or "").strip()
    if text == "/cancel":
        return  # 全局 cancel handler 接住
    await message.reply("❌ 请发送图片（约课截图 + 现场手势 共 2 张）。")


# ============ Rating 子状态 ============


@router.callback_query(
    F.data.startswith("card:rating:"), CardReviewStates.editing_rating,
)
async def cb_card_rating(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    key = parts[-1] if len(parts) == 3 else ""
    if key not in {r["key"] for r in REVIEW_RATINGS}:
        await callback.answer("参数错误", show_alert=True)
        return
    await state.update_data(rating=key)
    await render_card(callback.message, state, via_edit=True)
    label = next(r["label"] for r in REVIEW_RATINGS if r["key"] == key)
    await callback.answer(f"已设置：{label}")


# ============ 6 维评分子状态：文本输入 ============


@router.message(StateFilter(*_EDITING_DIM_STATES))
async def msg_card_dim_score(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return  # 全局 cancel handler
    score = parse_review_score(text)
    if score is None:
        await message.reply("❌ 请输入 0-10 的数字（最多 1 位小数）。")
        return
    cur = await state.get_state()
    dim_key = _DIM_BY_STATE.get(cur)
    if not dim_key:
        return
    column = _DIM_META[dim_key]["column"]
    await state.update_data(**{column: score})
    await message.reply(f"✅ {_DIM_META[dim_key]['label']} = {score:.1f}，返回卡片。")
    await render_card(message, state, via_edit=False)


# ============ Summary 子状态：文本输入 ============


@router.message(CardReviewStates.editing_summary, F.text)
async def msg_card_summary(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return
    if not text:
        await message.reply("❌ 过程描述必填，请输入文字。")
        return
    if len(text) < REVIEW_SUMMARY_MIN_LEN or len(text) > REVIEW_SUMMARY_MAX_LEN:
        await message.reply(
            f"❌ 字数需在 {REVIEW_SUMMARY_MIN_LEN}-{REVIEW_SUMMARY_MAX_LEN} 之间，当前 {len(text)} 字。"
        )
        return
    await state.update_data(summary=text)
    await message.reply("✅ 过程描述已保存，返回卡片。")
    await render_card(message, state, via_edit=False)


# ============ 提交 ============


def _missing_fields(data: dict) -> list[str]:
    """返回未填字段的中文标签列表（按出现顺序）"""
    missing: list[str] = []
    if not data.get("booking_screenshot_file_id") or not data.get("gesture_photo_file_id"):
        missing.append("🖼 出击证明")
    if not data.get("rating"):
        missing.append("⭐ 评级")
    for key, meta in _DIM_META.items():
        if data.get(meta["column"]) is None:
            missing.append(meta["label"])
    if not data.get("summary"):
        missing.append("📝 过程描述")
    return missing


@router.callback_query(
    F.data.startswith("card:submit:"), CardReviewStates.card,
)
async def cb_card_submit(callback: types.CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[-1]  # "anon" | "default"
    if mode not in {"anon", "default"}:
        await callback.answer("参数错误", show_alert=True)
        return
    data = await state.get_data()
    miss = _missing_fields(data)
    if miss:
        await callback.answer(
            "⚠️ 还有未填项：\n" + "、".join(miss) + "\n请补齐后再提交",
            show_alert=True,
        )
        return
    await state.update_data(anonymous=(1 if mode == "anon" else 0))
    await _enter_reimburse_or_submit(callback.message, state, via_edit=True)
    await callback.answer("已记录提交模式")


async def _enter_reimburse_or_submit(
    msg: types.Message, state: FSMContext, *, via_edit: bool,
):
    """检查报销资格 + 功能开关；满足则进 waiting_reimbursement_choice，否则直接落库"""
    data = await state.get_data()
    teacher_id = int(data.get("teacher_id") or 0)
    teacher = await get_teacher(teacher_id)
    amount = compute_reimbursement_amount(teacher.get("price") if teacher else None)

    # 2026-05：统一使用 get_reimbursement_min_points helper
    from bot.database import get_reimbursement_min_points
    min_pts = await get_reimbursement_min_points()

    user_id = msg.chat.id if msg.chat else 0
    points = await get_user_total_points(int(user_id))

    feature_enabled = (await get_config("reimbursement_feature_enabled")) == "1"

    # min_pts == 0 → 不启用门槛（任意积分都视为达标）
    if amount <= 0 or (min_pts > 0 and points < min_pts):
        # UX-5.4：feature_enabled 时显式告知用户为什么没看到报销选项；
        # feature OFF 时保持静默（避免暗示用户可申请）。
        if feature_enabled:
            try:
                from bot.utils.reimburse_notify import (
                    format_reimburse_ineligibility_hint,
                )
                hint = format_reimburse_ineligibility_hint(
                    amount=amount, points=points, min_pts=min_pts,
                )
                await msg.answer(hint)
            except Exception as e:
                logger.warning(
                    "[UX-5.4] reimburse ineligibility hint send failed: %s", e,
                )
        await state.update_data(request_reimbursement=0, _reimburse_amount=0)
        await _finalize_submit(msg, state, via_edit=via_edit)
        return

    if not feature_enabled:
        # 功能关闭：满足资格 → 静默录入（request_reimbursement=2 → status='queued'）
        await state.update_data(request_reimbursement=2, _reimburse_amount=amount)
        await _finalize_submit(msg, state, via_edit=via_edit)
        return

    await state.set_state(CardReviewStates.waiting_reimbursement_choice)
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
    try:
        if via_edit:
            await msg.edit_text(text, reply_markup=review_card_reimburse_kb(amount))
        else:
            await msg.answer(text, reply_markup=review_card_reimburse_kb(amount))
    except Exception:
        await msg.answer(text, reply_markup=review_card_reimburse_kb(amount))


async def _render_card_reimburse_subreq_gate(
    callback: types.CallbackQuery,
    missing: list[dict],
) -> None:
    """卡片 FSM 路径：渲染报销准入拦截页。"""
    from bot.keyboards.admin_kb import reimburse_subreq_user_gate_kb
    lines = ["💰 报销资格校验", "", "申请报销前，请先加入以下频道 / 群组："]
    for i, it in enumerate(missing, start=1):
        name = it.get("display_name") or str(it.get("chat_id"))
        lines.append(f"{i}. {name}")
    lines.append("")
    lines.append("完成后点击下方按钮重新检查。")
    text = "\n".join(lines)
    try:
        await callback.message.edit_text(
            text,
            reply_markup=reimburse_subreq_user_gate_kb(missing, context="card"),
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=reimburse_subreq_user_gate_kb(missing, context="card"),
        )


@router.callback_query(
    F.data == "card:reimburse:yes",
    CardReviewStates.waiting_reimbursement_choice,
)
async def cb_card_reimburse_yes(callback: types.CallbackQuery, state: FSMContext):
    # 报销准入校验：仅在用户勾选「✅ 申请报销」时触发
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    ok, missing = await check_user_subscribed_for_reimburse(
        callback.bot, callback.from_user.id,
    )
    if not ok:
        await _render_card_reimburse_subreq_gate(callback, missing)
        await callback.answer()
        return
    await state.update_data(request_reimbursement=1)
    await _finalize_submit(callback.message, state, via_edit=True)
    await callback.answer("已勾选申请报销")


@router.callback_query(
    F.data == "card:reimburse:no",
    CardReviewStates.waiting_reimbursement_choice,
)
async def cb_card_reimburse_no(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(request_reimbursement=0)
    await _finalize_submit(callback.message, state, via_edit=True)
    await callback.answer("已选择不申请")


# ============ 报销准入拦截页 callbacks（卡片 FSM 路径） ============

@router.callback_query(
    F.data == "reimburse:subreq:recheck:card",
    CardReviewStates.waiting_reimbursement_choice,
)
async def cb_reimburse_subreq_recheck_card(
    callback: types.CallbackQuery, state: FSMContext,
):
    """卡片 FSM 路径：重新检查。"""
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    ok, missing = await check_user_subscribed_for_reimburse(
        callback.bot, callback.from_user.id,
    )
    if not ok:
        await _render_card_reimburse_subreq_gate(callback, missing)
        await callback.answer("仍有未加入的频道 / 群组", show_alert=True)
        return
    await state.update_data(request_reimbursement=1)
    await _finalize_submit(callback.message, state, via_edit=True)
    await callback.answer("✅ 已通过校验，已勾选申请报销")


@router.callback_query(
    F.data == "reimburse:subreq:back:card",
    CardReviewStates.waiting_reimbursement_choice,
)
async def cb_reimburse_subreq_back_card(
    callback: types.CallbackQuery, state: FSMContext,
):
    """卡片 FSM 路径：从拦截页返回 → 视为不申请。"""
    await state.update_data(request_reimbursement=0)
    await _finalize_submit(callback.message, state, via_edit=True)
    await callback.answer("已选择不申请报销")


async def _finalize_submit(
    msg: types.Message, state: FSMContext, *, via_edit: bool,
):
    """落库 + 通知超管 + 清状态"""
    data = await state.get_data()
    user_id = msg.chat.id if msg.chat else 0
    teacher_id = int(data.get("teacher_id") or 0)

    # 提交前再做一次限频
    limit_msg = await _check_rate_limit(int(user_id), teacher_id)
    if limit_msg:
        await state.clear()
        try:
            await msg.edit_text(f"❌ {limit_msg}")
        except Exception:
            await msg.answer(f"❌ {limit_msg}")
        return

    overall = _compute_overall_avg(data)
    review_data = {
        "teacher_id": teacher_id,
        "user_id": int(user_id),
        "booking_screenshot_file_id": data["booking_screenshot_file_id"],
        "gesture_photo_file_id": data["gesture_photo_file_id"],
        "rating": data["rating"],
        "score_humanphoto": data["score_humanphoto"],
        "score_appearance": data["score_appearance"],
        "score_body": data["score_body"],
        "score_service": data["score_service"],
        "score_attitude": data["score_attitude"],
        "score_environment": data["score_environment"],
        "overall_score": overall,
        "summary": data.get("summary"),
        "request_reimbursement": int(data.get("request_reimbursement") or 0),
        "anonymous": int(data.get("anonymous") or 0),
    }
    review_id = await create_teacher_review(review_data)
    if review_id is None:
        try:
            await msg.edit_text("⚠️ 提交失败，请稍后重试。")
        except Exception:
            await msg.answer("⚠️ 提交失败，请稍后重试。")
        return

    # 评价者画像 + 通知超管
    try:
        await add_user_tag(int(user_id), "评论型用户", score_delta=1, source="review")
    except Exception as e:
        logger.warning("add_user_tag 失败 user=%s: %s", user_id, e)

    try:
        from bot.utils.rreview_notify import notify_super_admins_new_review
        _asyncio.create_task(
            notify_super_admins_new_review(msg.bot, review_id)
        )
    except Exception as e:
        logger.warning("notify_super_admins schedule 失败 review=%s: %s", review_id, e)

    await state.clear()
    anon = int(review_data.get("anonymous") or 0)
    anon_note = "（已选匿名提交，最终发布时将隐藏你的用户名）" if anon else ""
    text = (
        f"✅ 评价 #{review_id} 已提交，等待管理员审核。\n"
        f"通常 24 小时内有结果，审核结果会私聊通知你。{anon_note}"
    )
    try:
        if via_edit:
            await msg.edit_text(text)
        else:
            await msg.answer(text)
    except Exception:
        await msg.answer(text)
