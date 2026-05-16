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
from aiogram.fsm.context import FSMContext

from bot.database import (
    get_teacher,
    create_teacher_review,
    count_recent_user_reviews,
    count_recent_user_teacher_reviews,
    add_user_tag,
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
    review_subscribe_links_kb,
    review_rating_kb,
    review_score_kb,
    review_summary_skip_cancel_kb,
    review_confirm_kb,
)
from bot.states.teacher_states import ReviewSubmitStates
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
) -> tuple[str, Optional[dict]]:
    """[📝 写评价] 入口的核心逻辑（callback / deep link 共用）

    返回 ("ok"|"not_found"|"inactive"|"rate_limited"|"need_subscribe", extra)
        - ok：state 已设置 waiting_booking_screenshot；extra={"teacher": dict}
        - rate_limited：extra={"reason": str}
        - need_subscribe：extra={"missing": list[dict]}
        - not_found / inactive：extra=None

    调用方负责按返回值渲染对应文案 / 键盘。
    edit_msg 为可选目标消息：若提供，文案直接 edit_text 替换；
    否则调用方需自己 send_message。
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

    await state.set_state(ReviewSubmitStates.waiting_booking_screenshot)
    await state.set_data({"teacher_id": teacher_id})
    return "ok", {"teacher": teacher}


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

    # status == "ok"
    teacher = extra["teacher"]
    await callback.message.edit_text(
        f"📝 为「{teacher['display_name']}」写评价\n\n"
        "[Step B/12] 上传约课记录截图（必填）\n\n"
        "请发送你和该老师的约课记录截图（一张图片）。\n"
        "仅作为审核证据，不会公开展示。\n\n"
        "任意时刻发 /cancel 中止。",
        reply_markup=review_cancel_kb(),
    )
    await callback.answer()


# ============ 通用取消 ============

@router.callback_query(F.data == "review:cancel")
async def cb_review_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ 已取消评价。回到老师详情页可重新点 [📝 写评价]。"
    )
    await callback.answer("已取消")


@router.message(F.text == "/cancel", ReviewSubmitStates())
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ 已取消评价。回到老师详情页可重新点 [📝 写评价]。")


# ============ Step B：约课截图 ============

@router.message(ReviewSubmitStates.waiting_booking_screenshot, F.photo)
async def step_booking_photo(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(booking_screenshot_file_id=file_id)
    data = await state.get_data()
    if data.get("jump_back"):
        await state.update_data(jump_back=False)
        await _enter_confirm(message, state)
        return
    await state.set_state(ReviewSubmitStates.waiting_gesture_photo)
    await message.answer(
        "✅ 约课截图已收到。\n\n"
        "[Step C/12] 上传现场手势照片（必填）\n\n"
        "请发送你在见到老师后的现场手势照片（如比心 / 竖大拇指 / 伸 3 根手指等）。\n"
        "仅作为审核证据，不会公开展示。",
        reply_markup=review_cancel_kb(),
    )


@router.message(ReviewSubmitStates.waiting_booking_screenshot)
async def step_booking_invalid(message: types.Message):
    await message.reply("❌ 请发送一张图片（不接受文字 / 视频 / 文件）。")


# ============ Step C：手势照片 ============

@router.message(ReviewSubmitStates.waiting_gesture_photo, F.photo)
async def step_gesture_photo(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(gesture_photo_file_id=file_id)
    data = await state.get_data()
    if data.get("jump_back"):
        await state.update_data(jump_back=False)
        await _enter_confirm(message, state)
        return
    await _enter_rating(message, state)


@router.message(ReviewSubmitStates.waiting_gesture_photo)
async def step_gesture_invalid(message: types.Message):
    await message.reply("❌ 请发送一张图片（不接受文字 / 视频 / 文件）。")


# ============ Step 1：评级 ============

async def _enter_rating(msg_or_cb, state: FSMContext, *, via_edit: bool = False):
    await state.set_state(ReviewSubmitStates.waiting_rating)
    text = (
        "[Step 1/9] 评级（必填）\n\n"
        "请选择你对老师的整体印象："
    )
    await _show(msg_or_cb, text, review_rating_kb(), via_edit=via_edit)


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
    await state.update_data(rating=rating_key)
    data = await state.get_data()
    if data.get("jump_back"):
        await state.update_data(jump_back=False)
        await _enter_confirm(callback.message, state, via_edit=True)
        await callback.answer("已更新评级")
        return
    await _enter_score_step(callback.message, state, "humanphoto", via_edit=True)
    await callback.answer()


# ============ Step 2-7：6 维评分（共用入口） ============

async def _enter_score_step(msg, state: FSMContext, dim_key: str, *, via_edit: bool = False):
    step = _STEP_BY_KEY[dim_key]
    await state.set_state(step["state"])
    step_num = next(i for i, s in enumerate(_SCORE_FLOW, start=2) if s["key"] == dim_key)
    text = (
        f"[Step {step_num}/9] {step['label']}（必填）\n\n"
        "请打分 0.0 - 10.0（最多 1 位小数）。\n"
        "可点下方快捷按钮，或直接回复数字。"
    )
    await _show(msg, text, review_score_kb(dim_key, REVIEW_SCORE_QUICK_BUTTONS_FOR_DIM),
                via_edit=via_edit)


@router.callback_query(F.data.startswith("review:score:"))
async def cb_score_button(callback: types.CallbackQuery, state: FSMContext):
    """快捷数字按钮 callback：review:score:<dim_key>:<value>

    dim_key ∈ {humanphoto, appearance, body, service, attitude, environment, overall}
    """
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    dim_key, raw_val = parts[2], parts[3]
    score = parse_review_score(raw_val)
    if score is None:
        await callback.answer("评分非法", show_alert=True)
        return
    cur = await state.get_state()
    if dim_key == "overall":
        if cur != ReviewSubmitStates.waiting_overall_score.state:
            await callback.answer("当前不在综合评分步骤", show_alert=True)
            return
        await _record_overall(callback, state, score, via_edit=True)
    elif dim_key in _STEP_BY_KEY:
        if cur != _STEP_BY_KEY[dim_key]["state"].state:
            await callback.answer("当前不在该评分步骤", show_alert=True)
            return
        await _record_score(callback, state, dim_key, score, via_edit=True)
    else:
        await callback.answer("未知维度", show_alert=True)


@router.message(
    ReviewSubmitStates.waiting_score_humanphoto,
    ReviewSubmitStates.waiting_score_appearance,
    ReviewSubmitStates.waiting_score_body,
    ReviewSubmitStates.waiting_score_service,
    ReviewSubmitStates.waiting_score_attitude,
    ReviewSubmitStates.waiting_score_environment,
)
async def msg_dim_score(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel(message, state)
    score = parse_review_score(text)
    if score is None:
        await message.reply(
            "❌ 请输入 0-10 的数字（最多 1 位小数），或点上方快捷按钮。"
        )
        return
    # 找到当前状态对应的 dim_key
    cur_state = await state.get_state()
    dim_key: Optional[str] = None
    for s in _SCORE_FLOW:
        if cur_state == s["state"].state:
            dim_key = s["key"]
            break
    if dim_key is None:
        return
    await _record_score(message, state, dim_key, score, via_edit=False)


async def _record_score(
    msg_or_cb, state: FSMContext, dim_key: str, score: float, *, via_edit: bool,
):
    column = _STEP_BY_KEY[dim_key]["column"]
    await state.update_data(**{column: score})
    data = await state.get_data()
    if data.get("jump_back"):
        await state.update_data(jump_back=False)
        await _ack(msg_or_cb, f"✅ 已更新「{_STEP_BY_KEY[dim_key]['label']}」= {score}")
        await _enter_confirm(_extract_msg(msg_or_cb), state, via_edit=via_edit)
        return
    # 下一个维度 or 综合
    idx = next(i for i, s in enumerate(_SCORE_FLOW) if s["key"] == dim_key)
    if idx + 1 < len(_SCORE_FLOW):
        next_key = _SCORE_FLOW[idx + 1]["key"]
        await _ack(msg_or_cb, f"✅ {_STEP_BY_KEY[dim_key]['label']} = {score}")
        await _enter_score_step(_extract_msg(msg_or_cb), state, next_key, via_edit=via_edit)
    else:
        # 转 Step 8 综合评分
        await _ack(msg_or_cb, f"✅ {_STEP_BY_KEY[dim_key]['label']} = {score}")
        await _enter_overall(_extract_msg(msg_or_cb), state, via_edit=via_edit)


# ============ Step 8：综合评分 ============

async def _enter_overall(msg, state: FSMContext, *, via_edit: bool = False):
    await state.set_state(ReviewSubmitStates.waiting_overall_score)
    text = (
        "[Step 8/9] 🎯 综合评分（必填）\n\n"
        "请打个综合分 0.0 - 10.0（与 6 维平均可有差异，不强制一致）。\n"
        "可点下方快捷按钮，或直接回复数字。"
    )
    await _show(msg, text, review_score_kb("overall", REVIEW_SCORE_QUICK_BUTTONS_FOR_OVERALL),
                via_edit=via_edit)


@router.message(ReviewSubmitStates.waiting_overall_score)
async def msg_overall(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel(message, state)
    score = parse_review_score(text)
    if score is None:
        await message.reply(
            "❌ 请输入 0-10 的数字（最多 1 位小数），或点上方快捷按钮。"
        )
        return
    await _record_overall(message, state, score, via_edit=False)


# review:score:overall:<value> 复用 cb_score_button → 走到这里
async def _record_overall(msg_or_cb, state: FSMContext, score: float, *, via_edit: bool):
    await state.update_data(overall_score=score)
    data = await state.get_data()
    if data.get("jump_back"):
        await state.update_data(jump_back=False)
        await _ack(msg_or_cb, f"✅ 综合评分 = {score}")
        await _enter_confirm(_extract_msg(msg_or_cb), state, via_edit=via_edit)
        return
    await _ack(msg_or_cb, f"✅ 综合评分 = {score}")
    await _enter_summary(_extract_msg(msg_or_cb), state, via_edit=via_edit)


# ============ Step 9：过程描述（可选） ============

async def _enter_summary(msg, state: FSMContext, *, via_edit: bool = False):
    await state.set_state(ReviewSubmitStates.waiting_summary)
    text = (
        f"[Step 9/9] 📝 过程描述（可选，{REVIEW_SUMMARY_MIN_LEN}-{REVIEW_SUMMARY_MAX_LEN} 字）\n\n"
        "用一句话描述整体感受 / 过程，会显示在评论区。\n"
        "点 [⏭ 跳过] 也可。"
    )
    await _show(msg, text, review_summary_skip_cancel_kb(), via_edit=via_edit)


@router.callback_query(F.data == "review:summary_skip", ReviewSubmitStates.waiting_summary)
async def cb_summary_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(summary=None)
    data = await state.get_data()
    if data.get("jump_back"):
        await state.update_data(jump_back=False)
    await _enter_confirm(callback.message, state, via_edit=True)
    await callback.answer("已跳过")


@router.message(ReviewSubmitStates.waiting_summary)
async def msg_summary(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel(message, state)
    if not text:
        await message.reply("❌ 请用文字回复，或点 [⏭ 跳过]。")
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
    await _enter_confirm(message, state, via_edit=False)


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
        f"评级：{rating_str} · 🎯 综合 {overall}",
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
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("确认无误点 [✅ 提交审核]，或修改某项。")

    await _show(msg, "\n".join(lines), review_confirm_kb(), via_edit=via_edit)


# ============ 修改某项跳回 ============

_EDIT_DESTINATION: dict[str, dict] = {
    "booking":     {"state": ReviewSubmitStates.waiting_booking_screenshot,
                    "prompt": "请重新发送约课记录截图。", "kind": "photo"},
    "gesture":     {"state": ReviewSubmitStates.waiting_gesture_photo,
                    "prompt": "请重新发送现场手势照片。", "kind": "photo"},
    "rating":      {"state": ReviewSubmitStates.waiting_rating,
                    "prompt": "请重新选择评级：", "kind": "rating"},
    "humanphoto":  {"state": ReviewSubmitStates.waiting_score_humanphoto,
                    "prompt": "请重新打 🎨 人照评分（0-10）：", "kind": "score",
                    "dim_key": "humanphoto"},
    "appearance":  {"state": ReviewSubmitStates.waiting_score_appearance,
                    "prompt": "请重新打颜值评分（0-10）：", "kind": "score",
                    "dim_key": "appearance"},
    "body":        {"state": ReviewSubmitStates.waiting_score_body,
                    "prompt": "请重新打身材评分（0-10）：", "kind": "score",
                    "dim_key": "body"},
    "service":     {"state": ReviewSubmitStates.waiting_score_service,
                    "prompt": "请重新打服务评分（0-10）：", "kind": "score",
                    "dim_key": "service"},
    "attitude":    {"state": ReviewSubmitStates.waiting_score_attitude,
                    "prompt": "请重新打态度评分（0-10）：", "kind": "score",
                    "dim_key": "attitude"},
    "environment": {"state": ReviewSubmitStates.waiting_score_environment,
                    "prompt": "请重新打环境评分（0-10）：", "kind": "score",
                    "dim_key": "environment"},
    "overall":     {"state": ReviewSubmitStates.waiting_overall_score,
                    "prompt": "请重新打综合评分（0-10）：", "kind": "overall"},
    "summary":     {"state": ReviewSubmitStates.waiting_summary,
                    "prompt": "请重新输入过程描述（或跳过）：", "kind": "summary"},
}


@router.callback_query(F.data.startswith("review:edit:"), ReviewSubmitStates.waiting_confirm)
async def cb_review_edit(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) != 3 or parts[2] not in _EDIT_DESTINATION:
        await callback.answer("参数错误", show_alert=True)
        return
    dest = _EDIT_DESTINATION[parts[2]]
    await state.set_state(dest["state"])
    await state.update_data(jump_back=True)

    kind = dest["kind"]
    if kind == "rating":
        kb = review_rating_kb()
    elif kind == "score":
        kb = review_score_kb(dest["dim_key"], REVIEW_SCORE_QUICK_BUTTONS_FOR_DIM)
    elif kind == "overall":
        kb = review_score_kb("overall", REVIEW_SCORE_QUICK_BUTTONS_FOR_OVERALL)
    elif kind == "summary":
        kb = review_summary_skip_cancel_kb()
    else:  # photo
        kb = review_cancel_kb()

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
