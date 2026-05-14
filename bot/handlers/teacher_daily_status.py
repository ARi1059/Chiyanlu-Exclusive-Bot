"""老师今日状态管理 + 管理员今日状态总览 + noop 占位（Phase 5）

老师侧 callbacks:
    teacher:status                 进入"今日状态"页（老师菜单入口）
    teacher:status:set_time        设置可约时间 → 显示时间选择器
    teacher:status:mark_full       标记今日已满
    teacher:status:cancel          取消今日开课 → 提示输入原因
    teacher:status:cancel_skip     跳过原因直接取消
    teacher:time:all|afternoon|evening|custom|skip
                                   签到后 / 状态菜单的时间段选择

管理员侧 callbacks:
    admin:today_status             今日开课状态总览（刷新 + 返回）

通用 callbacks:
    noop:<any>                     频道发布键盘里的分组标签占位
                                   (不做任何事，仅消除按钮 spinner)

FSM (TeacherDailyStatusStates):
    waiting_custom_time            自定义时间段文字
    waiting_cancel_reason          取消原因（可选文本）
"""

import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from pytz import timezone

from bot.config import config
from bot.database import (
    TEACHER_TIME_SLOTS,
    cancel_teacher_today,
    get_teacher,
    get_teacher_daily_status,
    get_today_teacher_statuses,
    is_admin,
    is_checked_in,
    mark_teacher_full_today,
    set_teacher_daily_status,
)
from bot.keyboards.admin_kb import admin_today_status_kb
from bot.keyboards.teacher_self_kb import (
    cancel_reason_kb,
    custom_time_cancel_kb,
    teacher_main_menu_kb,
    teacher_status_kb,
    time_picker_kb,
)
from bot.states.teacher_states import TeacherDailyStatusStates

logger = logging.getLogger(__name__)

router = Router(name="teacher_daily_status")

_tz = timezone(config.timezone)


def _today_str() -> str:
    return datetime.now(_tz).strftime("%Y-%m-%d")


def _is_private_chat(callback: types.CallbackQuery) -> bool:
    return bool(
        callback.message
        and callback.message.chat
        and callback.message.chat.type == "private"
    )


async def _safe_log_user_event(
    user_id: int,
    event_type: str,
    payload=None,
) -> None:
    """log_user_event 不存在或失败时静默跳过（Phase 1 兼容降级）"""
    try:
        from bot.database import log_user_event  # type: ignore
    except ImportError:
        return
    try:
        await log_user_event(user_id, event_type, payload)
    except Exception as e:
        logger.debug("log_user_event 失败 (type=%s): %s", event_type, e)


async def _safe_log_admin_audit(
    admin_id: int,
    action: str,
    **kwargs,
) -> None:
    """log_admin_audit 不存在或失败时静默跳过（Phase 1 兼容降级）"""
    try:
        from bot.database import log_admin_audit  # type: ignore
    except ImportError:
        return
    try:
        await log_admin_audit(admin_id=admin_id, action=action, **kwargs)
    except Exception as e:
        logger.debug("log_admin_audit 失败 (action=%s): %s", action, e)


# ============ 老师今日状态主页 ============


def _format_status_summary(
    teacher: dict,
    *,
    signed_in: bool,
    status_row: dict | None,
) -> str:
    """格式化老师今日状态摘要文本"""
    if not signed_in and not status_row:
        sign_label = "未签到"
        course_label = "今日暂未开课"
        time_label = "—"
        note_label = "—"
    else:
        sign_label = "已签到" if signed_in else "未签到"
        status = (status_row or {}).get("status") or "available"
        avt = (status_row or {}).get("available_time")
        note = (status_row or {}).get("note")
        if status == "available":
            course_label = "✅ 可约"
        elif status == "full":
            course_label = "🈵 已满"
        elif status == "unavailable":
            course_label = "❌ 已取消"
        else:
            course_label = "未设置"
        time_label = (avt or "").strip() or "未设置"
        note_label = (note or "").strip() or "—"

    lines = [
        f"📅 今日状态 · {_today_str()}",
        "━━━━━━━━━━━━━━━",
        f"签到状态：{sign_label}",
        f"开课状态：{course_label}",
        f"可约时间：{time_label}",
        f"备注：{note_label}",
        "━━━━━━━━━━━━━━━",
    ]
    if not signed_in:
        lines.append("⚠️ 你今日还未签到，需先签到才会被纳入开课列表。")
    return "\n".join(lines)


@router.callback_query(F.data == "teacher:status")
async def cb_teacher_status(callback: types.CallbackQuery, state: FSMContext):
    """老师今日状态主页"""
    if not _is_private_chat(callback):
        await callback.answer()
        return
    await state.clear()

    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return

    today = _today_str()
    signed_in = await is_checked_in(callback.from_user.id, today)
    row = await get_teacher_daily_status(callback.from_user.id, today)
    text = _format_status_summary(teacher, signed_in=signed_in, status_row=row)
    try:
        await callback.message.edit_text(text, reply_markup=teacher_status_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=teacher_status_kb())
    await callback.answer()


# ============ teacher:status:set_time —— 进入时间选择器 ============


@router.callback_query(F.data == "teacher:status:set_time")
async def cb_set_time_entry(callback: types.CallbackQuery, state: FSMContext):
    """状态菜单点击"设置可约时间" → 复用 time_picker_kb"""
    if not _is_private_chat(callback):
        await callback.answer()
        return
    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return
    await state.clear()
    try:
        await callback.message.edit_text(
            "⏰ 请选择今日可约时间：",
            reply_markup=time_picker_kb(),
        )
    except Exception:
        await callback.message.answer(
            "⏰ 请选择今日可约时间：",
            reply_markup=time_picker_kb(),
        )
    await callback.answer()


# ============ teacher:time:* —— 时间段选择 callbacks ============


_TIME_KEY_TO_LABEL: dict[str, str] = {
    "all": "全天",
    "afternoon": "下午",
    "evening": "晚上",
    "custom": "自定义",
    "skip": "",
}


async def _apply_time_slot(
    user_id: int,
    teacher: dict,
    slot_label: str,
    note: str | None = None,
) -> None:
    """写入 teacher_daily_status：status=available + available_time + 可选 note"""
    today = _today_str()
    await set_teacher_daily_status(
        teacher_id=user_id,
        status_date=today,
        status="available",
        available_time=slot_label,
        note=note,
    )
    await _safe_log_user_event(
        user_id=user_id,
        event_type="teacher_time_set",
        payload={"available_time": slot_label, "note": note},
    )


async def _send_status_summary_after(callback: types.CallbackQuery) -> None:
    """完成某个状态操作后,展示当前最新状态 + 状态菜单"""
    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        return
    today = _today_str()
    signed_in = await is_checked_in(callback.from_user.id, today)
    row = await get_teacher_daily_status(callback.from_user.id, today)
    text = _format_status_summary(teacher, signed_in=signed_in, status_row=row)
    try:
        await callback.message.edit_text(text, reply_markup=teacher_status_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=teacher_status_kb())


@router.callback_query(F.data.startswith("teacher:time:"))
async def cb_time_pick(callback: types.CallbackQuery, state: FSMContext):
    """处理时间段选择"""
    if not _is_private_chat(callback):
        await callback.answer()
        return
    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return

    key = callback.data[len("teacher:time:"):]
    user_id = callback.from_user.id

    if key == "skip":
        # 不强制写入 daily_status；只关闭选择器
        await state.clear()
        await callback.answer("已跳过设置")
        await _send_status_summary_after(callback)
        return

    if key == "custom":
        # 进 FSM 等待自定义输入
        await state.set_state(TeacherDailyStatusStates.waiting_custom_time)
        try:
            await callback.message.edit_text(
                "📝 请输入自定义可约时间（一句话）：\n"
                "例如：晚上 8 点后可约 / 接 2 个 / 仅老客\n\n"
                "/cancel 退出",
                reply_markup=custom_time_cancel_kb(),
            )
        except Exception:
            await callback.message.answer(
                "📝 请输入自定义可约时间（一句话）：",
                reply_markup=custom_time_cancel_kb(),
            )
        await callback.answer()
        return

    label = _TIME_KEY_TO_LABEL.get(key)
    if not label or label not in TEACHER_TIME_SLOTS:
        await callback.answer("⚠️ 无效时间段", show_alert=True)
        return

    await _apply_time_slot(user_id, teacher, label, note=None)
    await state.clear()
    await callback.answer(f"✅ 已设置：{label}")
    await _send_status_summary_after(callback)


@router.message(TeacherDailyStatusStates.waiting_custom_time)
async def on_custom_time(message: types.Message, state: FSMContext):
    """接收自定义时间段文字，写入 available_time='自定义' + note=输入"""
    if message.chat.type != "private":
        return
    teacher = await get_teacher(message.from_user.id)
    if not teacher:
        await state.clear()
        return

    text = (message.text or "").strip()
    if not text:
        await message.reply(
            "请输入有效的文字，或点击下方「取消」",
            reply_markup=custom_time_cancel_kb(),
        )
        return
    if len(text) > 200:
        await message.reply("内容过长（>200 字），请精简一下")
        return

    await _apply_time_slot(
        message.from_user.id,
        teacher,
        slot_label="自定义",
        note=text,
    )
    await state.clear()
    await message.answer(f"✅ 已设置自定义时间：{text}")

    today = _today_str()
    signed_in = await is_checked_in(message.from_user.id, today)
    row = await get_teacher_daily_status(message.from_user.id, today)
    summary = _format_status_summary(teacher, signed_in=signed_in, status_row=row)
    await message.answer(summary, reply_markup=teacher_status_kb())


# ============ teacher:status:mark_full —— 标记今日已满 ============


@router.callback_query(F.data == "teacher:status:mark_full")
async def cb_mark_full(callback: types.CallbackQuery, state: FSMContext):
    if not _is_private_chat(callback):
        await callback.answer()
        return
    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return

    await state.clear()
    today = _today_str()
    await mark_teacher_full_today(callback.from_user.id, today)
    await _safe_log_user_event(
        user_id=callback.from_user.id,
        event_type="teacher_mark_full",
        payload={"date": today},
    )
    await callback.answer("🈵 已标记今日已满")
    await _send_status_summary_after(callback)


# ============ teacher:status:cancel —— 取消今日开课 ============


@router.callback_query(F.data == "teacher:status:cancel")
async def cb_cancel_today(callback: types.CallbackQuery, state: FSMContext):
    """❌ 取消今日开课 - 进 FSM 等取消原因"""
    if not _is_private_chat(callback):
        await callback.answer()
        return
    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return

    await state.set_state(TeacherDailyStatusStates.waiting_cancel_reason)
    try:
        await callback.message.edit_text(
            "❌ 取消今日开课\n\n"
            "请输入取消原因（一句话，可跳过）：\n"
            "例如：临时请假 / 身体不适 / 有事\n\n"
            "/cancel 退出",
            reply_markup=cancel_reason_kb(),
        )
    except Exception:
        await callback.message.answer(
            "❌ 取消今日开课\n\n请输入取消原因（可跳过）：",
            reply_markup=cancel_reason_kb(),
        )
    await callback.answer()


@router.callback_query(F.data == "teacher:status:cancel_skip")
async def cb_cancel_skip(callback: types.CallbackQuery, state: FSMContext):
    """跳过原因直接取消"""
    if not _is_private_chat(callback):
        await callback.answer()
        return
    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return

    today = _today_str()
    await cancel_teacher_today(callback.from_user.id, today, note=None)
    await _safe_log_user_event(
        user_id=callback.from_user.id,
        event_type="teacher_cancel_today",
        payload={"date": today, "reason": None},
    )
    await state.clear()
    await callback.answer("❌ 已取消今日开课")
    await _send_status_summary_after(callback)


@router.message(TeacherDailyStatusStates.waiting_cancel_reason)
async def on_cancel_reason(message: types.Message, state: FSMContext):
    """接收取消原因文字"""
    if message.chat.type != "private":
        return
    teacher = await get_teacher(message.from_user.id)
    if not teacher:
        await state.clear()
        return

    reason = (message.text or "").strip()
    if len(reason) > 200:
        await message.reply("原因过长（>200 字），请精简一下")
        return

    today = _today_str()
    await cancel_teacher_today(message.from_user.id, today, note=reason or None)
    await _safe_log_user_event(
        user_id=message.from_user.id,
        event_type="teacher_cancel_today",
        payload={"date": today, "reason": reason or None},
    )
    await state.clear()
    await message.answer(
        f"❌ 已取消今日开课"
        + (f"\n原因：{reason}" if reason else "")
    )

    signed_in = await is_checked_in(message.from_user.id, today)
    row = await get_teacher_daily_status(message.from_user.id, today)
    summary = _format_status_summary(teacher, signed_in=signed_in, status_row=row)
    await message.answer(summary, reply_markup=teacher_status_kb())


# ============ 管理员今日状态总览 ============


def _classify_for_admin(row: dict) -> str:
    """管理员视图的细分组键：返回 'all/afternoon/evening/custom/none/full/unavailable'"""
    status = (row.get("daily_status") or "").strip()
    if status == "unavailable":
        return "unavailable"
    if status == "full":
        return "full"
    avt = (row.get("daily_available_time") or "").strip()
    if avt == "全天":
        return "all"
    if avt == "下午":
        return "afternoon"
    if avt == "晚上":
        return "evening"
    if avt == "自定义":
        return "custom"
    return "none"


_ADMIN_GROUP_ORDER: list[tuple[str, str]] = [
    ("all", "🌞 全天可约"),
    ("afternoon", "🌤 下午可约"),
    ("evening", "🌙 晚上可约"),
    ("custom", "📝 自定义"),
    ("none", "📅 未设置时间"),
    ("full", "🈵 已满"),
    ("unavailable", "❌ 已取消"),
]


@router.callback_query(F.data == "admin:today_status")
async def cb_admin_today_status(callback: types.CallbackQuery, state: FSMContext):
    """📅 今日开课状态总览（管理员）"""
    # admin_required 装饰器需要导入；这里复用 is_admin 简化（含超管判断）
    user_id = callback.from_user.id
    if not (user_id == config.super_admin_id or await is_admin(user_id)):
        await callback.answer("⚠️ 仅管理员可用", show_alert=True)
        return
    await state.clear()

    today = _today_str()
    rows = await get_today_teacher_statuses(today, active_only=True)

    # 分组
    groups: dict[str, list[dict]] = {key: [] for key, _ in _ADMIN_GROUP_ORDER}
    signed_count = 0
    cancelled_count = 0
    full_count = 0
    none_count = 0
    for r in rows:
        if r.get("signed_in"):
            signed_count += 1
        key = _classify_for_admin(r)
        groups[key].append(r)
        if key == "unavailable":
            cancelled_count += 1
        elif key == "full":
            full_count += 1
        elif key == "none" and r.get("signed_in"):
            none_count += 1

    showable = signed_count - cancelled_count

    lines = [
        f"📅 今日开课状态总览 · {today}",
        "━━━━━━━━━━━━━━━",
        f"已签到：{signed_count}",
        f"可展示：{showable}",
        f"已满：{full_count}",
        f"已取消：{cancelled_count}",
        f"未设置时间：{none_count}",
        "━━━━━━━━━━━━━━━",
    ]

    for key, header in _ADMIN_GROUP_ORDER:
        bucket = groups[key]
        if not bucket:
            continue
        lines.append("")
        lines.append(header)
        for r in bucket:
            name = r.get("display_name") or str(r.get("user_id"))
            note = (r.get("daily_note") or "").strip()
            if key == "unavailable":
                # 取消的展示原因
                lines.append(f"- {name}" + (f"：{note}" if note else ""))
            elif key == "custom":
                # 自定义展示备注内容
                lines.append(f"- {name}" + (f"（{note}）" if note else ""))
            else:
                lines.append(f"- {name}")

    text = "\n".join(lines)

    await _safe_log_admin_audit(
        admin_id=user_id,
        action="admin_view_today_status",
        target_type="daily_status",
        target_id=today,
    )

    try:
        await callback.message.edit_text(text, reply_markup=admin_today_status_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=admin_today_status_kb())
    await callback.answer()


# ============ noop —— 频道键盘分组标签占位 ============


@router.callback_query(F.data.startswith("noop"))
async def cb_noop(callback: types.CallbackQuery):
    """频道发布键盘里的分组标题占位按钮，仅消除按钮 spinner"""
    await callback.answer()
