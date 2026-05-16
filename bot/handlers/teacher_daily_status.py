"""老师今日状态管理 + 管理员今日状态总览 + noop 占位（Phase 5）

老师侧 callbacks:
    teacher:status                 进入"今日状态"页（老师菜单入口）
    teacher:status:mark_full       标记今日已满
    teacher:status:cancel          取消今日开课 → 提示输入原因
    teacher:status:cancel_skip     跳过原因直接取消

管理员侧 callbacks:
    admin:today_status             今日开课状态总览（刷新 + 返回）

通用 callbacks:
    noop:<any>                     频道发布键盘里的占位（不做任何事，仅消除 spinner）

FSM (TeacherDailyStatusStates):
    waiting_cancel_reason          取消原因（可选文本）

注：可约时间段相关流程（set_time / time:* / custom_time）已移除。老师签到后
直接进入「✅ 可约」状态，admin / 用户列表统一展示，无需再选时间段。
"""

import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from pytz import timezone

from bot.config import config
from bot.database import (
    cancel_teacher_today,
    get_teacher,
    get_teacher_daily_status,
    get_today_teacher_statuses,
    is_admin,
    is_checked_in,
    mark_teacher_full_today,
)
from bot.keyboards.admin_kb import admin_today_status_kb
from bot.keyboards.teacher_self_kb import (
    cancel_reason_kb,
    teacher_main_menu_kb,
    teacher_status_kb,
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
        note_label = "—"
    else:
        sign_label = "已签到" if signed_in else "未签到"
        status = (status_row or {}).get("status") or "available"
        note = (status_row or {}).get("note")
        if status == "available":
            course_label = "✅ 可约"
        elif status == "full":
            course_label = "🈵 已满"
        elif status == "unavailable":
            course_label = "❌ 已取消"
        else:
            course_label = "未设置"
        note_label = (note or "").strip() or "—"

    lines = [
        f"📅 今日状态 · {_today_str()}",
        "━━━━━━━━━━━━━━━",
        f"签到状态：{sign_label}",
        f"开课状态：{course_label}",
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
    """管理员视图分组键：available / full / unavailable / not_signed"""
    if not row.get("signed_in"):
        return "not_signed"
    status = (row.get("daily_status") or "").strip()
    if status == "unavailable":
        return "unavailable"
    if status == "full":
        return "full"
    return "available"


_ADMIN_GROUP_ORDER: list[tuple[str, str]] = [
    ("available", "✅ 可约"),
    ("full", "🈵 已满"),
    ("unavailable", "❌ 已取消"),
    ("not_signed", "📅 未签到"),
]


@router.callback_query(F.data == "admin:today_status")
async def cb_admin_today_status(callback: types.CallbackQuery, state: FSMContext):
    """📅 今日开课状态总览（管理员）"""
    user_id = callback.from_user.id
    if not (user_id == config.super_admin_id or await is_admin(user_id)):
        await callback.answer("⚠️ 仅管理员可用", show_alert=True)
        return
    await state.clear()

    today = _today_str()
    rows = await get_today_teacher_statuses(today, active_only=True)

    groups: dict[str, list[dict]] = {key: [] for key, _ in _ADMIN_GROUP_ORDER}
    signed_count = 0
    cancelled_count = 0
    full_count = 0
    available_count = 0
    for r in rows:
        if r.get("signed_in"):
            signed_count += 1
        key = _classify_for_admin(r)
        groups[key].append(r)
        if key == "unavailable":
            cancelled_count += 1
        elif key == "full":
            full_count += 1
        elif key == "available":
            available_count += 1

    lines = [
        f"📅 今日开课状态总览 · {today}",
        "━━━━━━━━━━━━━━━",
        f"已签到：{signed_count}",
        f"可展示：{available_count}",
        f"已满：{full_count}",
        f"已取消：{cancelled_count}",
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
            if key == "unavailable" and note:
                lines.append(f"- {name}：{note}")
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
