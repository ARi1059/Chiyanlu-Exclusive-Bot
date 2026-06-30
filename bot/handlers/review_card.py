"""卡片驱动评价 FSM（2026-05-18 Phase 2）

中心「评价卡片」展示老师 + 已填 / 未填字段；用户任选字段按钮进入填写子状态，
填完返回卡片。无强制顺序。

主要差异 vs 旧线性 FSM（已于 2026-05-20 Sprint 7 §9.1 第 3 批清理）：
- 状态机：CardReviewStates.card (idle) + 9 个 editing_X 子状态
- 任意点 [✓ 字段] 进入对应 editing_X；填完返回卡片
- 提交时 2 选 1：[😟 匿名提交] / [😎 默认提交]
- 提交后走现有报销询问逻辑 → 落库 → 通知超管

主要复用：
- bot.utils.required_channels.check_user_subscribed
- bot.utils.reimburse_eligibility.is_user_reimburse_eligible_for_review
  （内部聚合 compute_reimbursement_amount / get_config /
   get_user_total_points / get_reimbursement_min_points 等 helper）
- bot.utils.reimburse_notify.format_reimburse_ineligibility_hint
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
    count_recent_user_reviews,
    count_recent_user_teacher_reviews,
    create_teacher_review,
    derive_rating,
    get_teacher,
    parse_review_score,
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
    review_cancelled_kb,
    review_intent_kb,
    review_intent_subreq_fail_kb,
)
from bot.states.teacher_states import CardReviewStates
from bot.utils.required_channels import check_user_subscribed
from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint

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


def _evidence_required_count(data: dict) -> int:
    """证据照片需提供的总数：参与报销=2（约课截图 + 现场手势），否则=1。

    request_reimbursement 由 start_card_review 内的资格预判 + intent 选择
    阶段决定；卡片渲染 + 上传步 + _missing_fields 均按此值动态。
    """
    return 2 if int(data.get("request_reimbursement") or 0) == 1 else 1


def _total_required_fields(data: dict) -> int:
    """评价卡片总必填项数：evidence(1) + 6 维 + summary(1) = 8
    （2026-06-30：评级改由综合分自动判定，不再是手填项，从 9 减为 8）。
    """
    return 8


async def _build_card_text(state: FSMContext) -> str:
    data = await state.get_data()
    teacher_id = int(data.get("teacher_id") or 0)
    teacher = await get_teacher(teacher_id) if teacher_id else None
    tname = teacher["display_name"] if teacher else f"#{teacher_id}"
    rating_meta = {r["key"]: r for r in REVIEW_RATINGS}

    booking = data.get("booking_screenshot_file_id")
    gesture = data.get("gesture_photo_file_id")
    req_total = _evidence_required_count(data)
    if req_total == 2:
        evidence_count = sum(1 for v in (booking, gesture) if v)
        evidence_label = (
            f"🖼 出击证明：{evidence_count}/2 张"
            + ("（约课截图 + 现场手势）" if evidence_count < 2 else " ✅")
        )
    else:
        evidence_count = 1 if booking else 0
        evidence_label = (
            f"🖼 约课记录：{evidence_count}/1 张"
            + ("（约课截图）" if evidence_count < 1 else " ✅")
        )

    def _dim(key: str) -> str:
        col = _DIM_META[key]["column"]
        v = data.get(col)
        return f"{float(v):.1f}" if v is not None else "（未填）"

    summary = data.get("summary") or "（未填）"
    if isinstance(summary, str) and len(summary) > 40:
        summary = summary[:40] + "…"

    overall = _compute_overall_avg(data)
    overall_str = f"{overall:.1f}（6 维平均）" if overall > 0 else "（待 6 维齐全后自动计算）"

    # 2026-06-30：评级不再手填，按 6 维综合分自动判定（6 维齐全后显示）。
    if overall > 0:
        r_meta = rating_meta[derive_rating(overall)]
        rating_str = f"{r_meta['emoji']} {r_meta['label']}（按综合分自动）"
    else:
        rating_str = "（6 维齐全后按综合分自动判定）"

    # UX-8.1：进度计数（已完成 N/9 + 可提交标记）
    missing = _missing_fields(data)
    total_fields = _total_required_fields(data)
    filled_count = total_fields - len(missing)
    if not missing:
        progress_line = f"📊 进度：已完成 {filled_count}/{total_fields} · ✅ 可提交"
    else:
        progress_line = (
            f"📊 进度：已完成 {filled_count}/{total_fields} · "
            f"还差 {len(missing)} 项"
        )

    # 2026-05-21：卡片头部显示当前报销路径，避免用户混淆
    reimburse_flag = int(data.get("request_reimbursement") or 0)
    reimburse_banner = (
        "💰 报销路径：✅ 参与（需上传现场手势照）"
        if reimburse_flag == 1
        else "📝 普通评价路径（不参与报销）"
    )

    lines = [
        "📋 评价卡片（点按钮逐项填写，无顺序要求）",
        progress_line,
        reimburse_banner,
        "━━━━━━━━━━━━━━━",
        f"老师：{tname}",
        evidence_label,
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
        "提交后将以你的（半匿名）留名展示；点 [✅ 提交] 完成。",
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
    # UX-8.1：把缺项数量传给 keyboard，提交按钮文案动态化
    missing_count = len(_missing_fields(data))
    kb = review_card_kb(data, missing_count=missing_count)
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
) -> tuple[str, Optional[dict]]:
    """卡片入口校验 + state 初始化 + 报销资格预判（2026-05-21）。

    返回 ("ok"|"not_found"|"inactive"|"rate_limited"|"need_subscribe", extra)
        - ok：state 已设置：eligible 用户 → CardReviewStates.choosing_reimburse_intent；
              否则 → CardReviewStates.card（同时已 update_data 写入 request_reimbursement=0）。
              extra = {"teacher": dict, "needs_intent": bool, "eligibility": dict}
              调用方应使用 [render_card_or_intent] 自动按 state 渲染。

    设计：报销资格预判提到选老师之后立即做（在所有校验通过、state 写入之后）；
    eligible（feature_on + 价位在范围 + 积分够 + 月池有余）→ 让用户显式选择
    是否参与；ineligible → 直接进卡片，状态机内不再问报销，提交成功页据
    state.data["_reimburse_eligibility_info"] 附加 ineligibility hint。
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

    # 资格预判：feature / 价位 / 积分 / 月池四项一并判
    eligible, info = await is_user_reimburse_eligible_for_review(
        int(user_id), teacher.get("price"),
    )

    init: dict = {
        "teacher_id": teacher_id,
        "anonymous": 0,
        "_reimburse_eligibility_info": info,
    }
    # 2026-06-30：评级由综合分自动判定，取消 pre_rating 预选（不再写入 init["rating"]）。

    if eligible:
        # 资格通过 → 进 intent 状态，由用户决定是否参与；request_reimbursement
        # 暂不写入（等用户选 yes/no 时再写），保持 None 区别于 "已主动选 no"
        await state.set_state(CardReviewStates.choosing_reimburse_intent)
        await state.set_data(init)
        return "ok", {"teacher": teacher, "needs_intent": True, "eligibility": info}

    # 不符合资格 → 直接进卡片；request_reimbursement=0 落定，submit 不再问
    init["request_reimbursement"] = 0
    await state.set_state(CardReviewStates.card)
    await state.set_data(init)
    return "ok", {"teacher": teacher, "needs_intent": False, "eligibility": info}


# ============ 报销意愿前置 intent（2026-05-21） ============


async def _build_intent_text(state: FSMContext) -> str:
    """渲染 intent 选择屏文案：当前积分 + 老师价位 + 预计报销金额。"""
    data = await state.get_data()
    info = data.get("_reimburse_eligibility_info") or {}
    teacher_id = int(data.get("teacher_id") or 0)
    teacher = await get_teacher(teacher_id) if teacher_id else None
    tname = teacher["display_name"] if teacher else f"#{teacher_id}"
    amount = int(info.get("amount") or 0)
    points = int(info.get("points") or 0)
    min_pts = int(info.get("min_pts") or 0)
    pool_remaining = int(info.get("pool_remaining") or -1)

    pool_line = (
        f"本月剩余池：{pool_remaining} 元" if pool_remaining >= 0 else "月池：不限"
    )

    return (
        "💰 是否参与报销？\n"
        "━━━━━━━━━━━━━━━\n"
        f"老师：{tname}\n"
        f"预计可申请报销：{amount} 元\n"
        f"当前积分：{points}（门槛 {min_pts if min_pts > 0 else '不启用'}）\n"
        f"{pool_line}\n"
        "━━━━━━━━━━━━━━━\n\n"
        "选「参与」需上传现场手势照；选「不参与」仅需约课截图。\n"
        "（审核通过后进入超管二次审核）"
    )


async def render_intent_screen(
    target_msg: types.Message, state: FSMContext, *, via_edit: bool = True,
):
    """渲染评价前置 intent 选择屏。state 必须已置 choosing_reimburse_intent。"""
    data = await state.get_data()
    info = data.get("_reimburse_eligibility_info") or {}
    amount = int(info.get("amount") or 0)
    text = await _build_intent_text(state)
    kb = review_intent_kb(amount)
    try:
        if via_edit:
            await target_msg.edit_text(text, reply_markup=kb)
        else:
            await target_msg.answer(text, reply_markup=kb)
    except Exception:
        try:
            await target_msg.answer(text, reply_markup=kb)
        except Exception as e:
            logger.warning("render_intent_screen 失败: %s", e)


async def render_card_or_intent(
    target_msg: types.Message, state: FSMContext, *, via_edit: bool = True,
):
    """根据当前 state 自动渲染 intent 屏或卡片屏。

    所有评价 FSM 入口（[📝 写评价] / deep link / 老师详情页）调用方都应使用
    本 dispatcher，而不是直接调 [render_card]——后者只用于编辑字段后返回卡片
    那一类内部流程。
    """
    cur_state = await state.get_state()
    if cur_state == CardReviewStates.choosing_reimburse_intent.state:
        await render_intent_screen(target_msg, state, via_edit=via_edit)
    else:
        await render_card(target_msg, state, via_edit=via_edit)


async def _render_intent_subreq_gate(
    callback: types.CallbackQuery, missing: list[dict],
):
    """intent=yes 时必关订阅未达 → 显示订阅链接 + 回退选择。"""
    lines = ["💰 报销准入校验", "", "申请报销前请先关注以下频道 / 群组："]
    for i, it in enumerate(missing, start=1):
        name = it.get("display_name") or str(it.get("chat_id"))
        lines.append(f"{i}. {name}")
    lines.append("")
    lines.append("已加入后点 [🔄 已加入，重新检查]；或选 [改为不参与，继续评价]。")
    text = "\n".join(lines)
    kb = review_intent_subreq_fail_kb(missing)
    try:
        await callback.message.edit_text(text, reply_markup=kb,
                                          disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=kb,
                                       disable_web_page_preview=True)


@router.callback_query(
    F.data == "card:intent:yes",
    CardReviewStates.choosing_reimburse_intent,
)
async def cb_card_intent_yes(callback: types.CallbackQuery, state: FSMContext):
    """用户选「参与报销」→ 必关订阅校验 → 通过则置 req=1 + 进卡片。"""
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    ok, missing = await check_user_subscribed_for_reimburse(
        callback.bot, callback.from_user.id,
    )
    if not ok:
        await _render_intent_subreq_gate(callback, missing)
        await callback.answer()
        return
    await state.update_data(request_reimbursement=1)
    await state.set_state(CardReviewStates.card)
    await render_card(callback.message, state, via_edit=True)
    await callback.answer("已选择参与报销")


@router.callback_query(
    F.data == "card:intent:no",
    CardReviewStates.choosing_reimburse_intent,
)
async def cb_card_intent_no(callback: types.CallbackQuery, state: FSMContext):
    """用户选「不参与」→ req=0 + 进卡片。"""
    await state.update_data(request_reimbursement=0)
    await state.set_state(CardReviewStates.card)
    await render_card(callback.message, state, via_edit=True)
    await callback.answer("已选择不参与，按普通评价继续")


@router.callback_query(
    F.data == "card:intent:retry",
    CardReviewStates.choosing_reimburse_intent,
)
async def cb_card_intent_retry(callback: types.CallbackQuery, state: FSMContext):
    """订阅 fallback 屏：用户已加入频道 → 重新校验。"""
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    ok, missing = await check_user_subscribed_for_reimburse(
        callback.bot, callback.from_user.id,
    )
    if not ok:
        await _render_intent_subreq_gate(callback, missing)
        await callback.answer("仍有未关注的频道 / 群组", show_alert=True)
        return
    await state.update_data(request_reimbursement=1)
    await state.set_state(CardReviewStates.card)
    await render_card(callback.message, state, via_edit=True)
    await callback.answer("✅ 校验通过，已勾选参与报销")


@router.callback_query(
    F.data == "card:intent:fallback",
    CardReviewStates.choosing_reimburse_intent,
)
async def cb_card_intent_fallback(callback: types.CallbackQuery, state: FSMContext):
    """订阅 fallback 屏：用户放弃报销 → 按普通评价继续，req=0。"""
    await state.update_data(request_reimbursement=0)
    await state.set_state(CardReviewStates.card)
    await render_card(callback.message, state, via_edit=True)
    await callback.answer("已切换为不参与，继续评价")


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
    CardReviewStates.choosing_reimburse_intent,
    CardReviewStates.card,
    CardReviewStates.editing_evidence,
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
    CardReviewStates.choosing_reimburse_intent,
    CardReviewStates.card,
    CardReviewStates.editing_evidence,
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
        data = await state.get_data()
        req_total = _evidence_required_count(data)
        if req_total == 2:
            prompt = (
                "🖼 上传 2 张证据照片（约课截图 + 现场手势）。\n"
                "可一起作为媒体组发送，也可一张一张发；前 2 张被采纳，多余忽略。\n\n"
                "完成后会自动返回卡片。"
            )
        else:
            prompt = (
                "🖼 上传 1 张约课截图。\n"
                "完成后会自动返回卡片。\n\n"
                "（不参与报销路径，无需现场手势照）"
            )
        await callback.message.edit_text(
            prompt,
            reply_markup=review_card_edit_cancel_kb(),
        )
        await callback.answer()
        return

    # 2026-06-30：评级不再手选（由综合分自动判定），card:field:rating 入口已移除。

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
    req_total = _evidence_required_count(data)
    files: list = list(data.get("_evidence_files") or [])
    if len(files) >= req_total:
        if message.media_group_id is None:
            await message.reply(f"⚠️ 已收到 {req_total} 张，请稍候自动返回卡片。")
        return
    files.append(message.photo[-1].file_id)
    await state.update_data(_evidence_files=files)

    if len(files) >= req_total:
        old = _EVIDENCE_REPLY_TASKS.pop(message.chat.id, None)
        if old and not old.done():
            old.cancel()
        update_kw = {
            "booking_screenshot_file_id": files[0],
            "_evidence_files": [],
        }
        # 仅参与报销路径（req_total==2）才落 gesture_photo；普通评价保持 None
        if req_total == 2:
            update_kw["gesture_photo_file_id"] = files[1]
        else:
            update_kw["gesture_photo_file_id"] = None
        await state.update_data(**update_kw)
        await message.reply(f"✅ {req_total} 张证据照片已收到，返回卡片。")
        await render_card(message, state, via_edit=False)
        return

    if message.media_group_id is None:
        await message.reply(f"✅ 已收到 {len(files)}/{req_total} 张，继续上传剩余照片。")
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
            if n >= req_total:
                return
            await bot_ref.send_message(
                chat_id=chat_id,
                text=f"✅ 已收到 {n}/{req_total} 张，继续上传剩余照片。",
            )
        except _asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            _EVIDENCE_REPLY_TASKS.pop(chat_id, None)

    _EVIDENCE_REPLY_TASKS[chat_id] = _asyncio.create_task(_debounced_reply())


@router.message(CardReviewStates.editing_evidence)
async def msg_card_evidence_invalid(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return  # 全局 cancel handler 接住
    data = await state.get_data()
    req_total = _evidence_required_count(data)
    if req_total == 2:
        await message.reply("❌ 请发送图片（约课截图 + 现场手势 共 2 张）。")
    else:
        await message.reply("❌ 请发送约课截图（1 张）。")


# 2026-06-30：评级子状态（editing_rating + card:rating: 选择）已移除——
# 评级由 6 维综合分自动判定（derive_rating），无需手选步骤。


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
    """返回未填字段的中文标签列表（按出现顺序）。

    2026-05-21：evidence 必填判定按 request_reimbursement 区分：
        - req=1：约课截图 + 现场手势 都得有 → 标签「🖼 出击证明」
        - req=0：仅约课截图必填 → 标签「🖼 约课记录」
    """
    missing: list[str] = []
    if int(data.get("request_reimbursement") or 0) == 1:
        if not data.get("booking_screenshot_file_id") or not data.get("gesture_photo_file_id"):
            missing.append("🖼 出击证明")
    else:
        if not data.get("booking_screenshot_file_id"):
            missing.append("🖼 约课记录")
    # 2026-06-30：评级不再手填，由 6 维综合分自动判定（derive_rating），从必填项移除。
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
        # UX-8.1：alert 改为聚焦"第一个未填项"，减少用户认知负担；
        # 余下未填项数量在卡片顶部进度行已可见。
        await callback.answer(
            f"⚠️ 先填「{miss[0]}」（还差 {len(miss)} 项）",
            show_alert=True,
        )
        return
    # 2026-06：取消匿名提交——一律实名（半匿名留名）。旧消息里的 card:submit:anon 也落 0。
    await state.update_data(anonymous=0)
    await _enter_reimburse_or_submit(callback.message, state, via_edit=True)
    await callback.answer("已提交")


async def _enter_reimburse_or_submit(
    msg: types.Message, state: FSMContext, *, via_edit: bool,
):
    """提交时的防御性 re-check + 落库（2026-05-21）。

    报销意愿已在 start_card_review → intent 状态里前置完成；本函数只做：
        1. 防御性 re-check：若 req=1 但用户在写评价期间积分掉了 / 池子用完了 /
           功能被关了 → 降级到 req=0，更新 _reimburse_eligibility_info；
        2. 调 _finalize_submit 完成落库 + 通知。

    旧的"submit 时刻问报销选择"逻辑已迁出；feature OFF + 资格满足的
    queued 路径同步取消（如功能关闭，前置预判即视为 ineligible，
    request_reimbursement 落为 0 + 在提交成功页提示）。
    """
    data = await state.get_data()
    req = int(data.get("request_reimbursement") or 0)
    if req == 1:
        # 防御性 re-check：写评价过程中状态可能变化
        teacher_id = int(data.get("teacher_id") or 0)
        teacher = await get_teacher(teacher_id) if teacher_id else None
        user_id = msg.chat.id if msg.chat else 0
        eligible, info = await is_user_reimburse_eligible_for_review(
            int(user_id), teacher.get("price") if teacher else None,
        )
        if not eligible:
            logger.info(
                "[review_card] 提交时报销资格失效 user=%s teacher=%s reason=%s",
                user_id, teacher_id, info.get("reason"),
            )
            await state.update_data(
                request_reimbursement=0,
                _reimburse_eligibility_info=info,
                # 现场手势照不再生效（普通评价路径），清零避免误存
                gesture_photo_file_id=None,
            )
    await _finalize_submit(msg, state, via_edit=via_edit)


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
    """落库 + 通知超管 + 清状态 + 提交成功页附 ineligibility hint（2026-05-21）"""
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
        # 2026-05-21：req=0 路径下 gesture_photo 为 None，DB 列已可空
        "gesture_photo_file_id": data.get("gesture_photo_file_id"),
        "rating": derive_rating(overall),  # 2026-06-30：按综合分自动判定，不再手填
        "score_humanphoto": data["score_humanphoto"],
        "score_appearance": data["score_appearance"],
        "score_body": data["score_body"],
        "score_service": data["score_service"],
        "score_attitude": data["score_attitude"],
        "score_environment": data["score_environment"],
        "overall_score": overall,
        "summary": data.get("summary"),
        "request_reimbursement": int(data.get("request_reimbursement") or 0),
        "anonymous": 0,  # 2026-06：取消匿名提交，一律实名落库
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

    # 2026-05-21：req=0 且预判 ineligible 时拼附 hint 到提交成功页尾
    req = int(review_data.get("request_reimbursement") or 0)
    ineligibility_hint: Optional[str] = None
    if req == 0:
        info = data.get("_reimburse_eligibility_info") or {}
        reason = info.get("reason")
        # 仅在 user 不是"主动选 no"的情况下提示——
        # 但我们没记录 user 是否主动选 no；用 reason 是否非 None 判：
        # eligible 用户主动选 no 的话 reason=None，不提示（避免劝退式打扰）；
        # 资格不符的用户 reason 必有值 → 提示对应原因。
        if reason:
            try:
                ineligibility_hint = format_reimburse_ineligibility_hint(
                    amount=int(info.get("amount") or 0),
                    points=int(info.get("points") or 0),
                    min_pts=int(info.get("min_pts") or 0),
                    reason=reason,
                    pool_remaining=info.get("pool_remaining"),
                )
            except Exception as e:
                logger.warning("format ineligibility hint 失败: %s", e)

    await state.clear()
    text_parts = [
        f"✅ 评价 #{review_id} 已提交，等待管理员审核。",
        "通常 24 小时内有结果，审核结果会私聊通知你。",
    ]
    if ineligibility_hint:
        text_parts.append("")
        text_parts.append(ineligibility_hint)
    text = "\n".join(text_parts)
    try:
        if via_edit:
            await msg.edit_text(text)
        else:
            await msg.answer(text)
    except Exception:
        await msg.answer(text)
