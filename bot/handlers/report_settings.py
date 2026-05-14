"""报表设置 handler（Phase 6.3）

Callbacks:
    admin:report_settings           设置主页（兼作 FSM 取消目标）
    admin:report:daily_toggle       开启/关闭日报
    admin:report:daily_time         修改日报时间（FSM）
    admin:report:weekly_toggle      开启/关闭周报
    admin:report:weekly_time        修改周报时间（FSM）
    admin:report:weekly_day         修改周报星期 1-7（FSM）
    admin:report:chat_id            修改接收 chat_id（FSM）
    admin:report:test_daily         立即发送日报测试（force=True）
    admin:report:test_weekly        立即发送周报测试（force=True）

FSM (ReportSettingsStates):
    waiting_daily_time    HH:MM
    waiting_weekly_time   HH:MM
    waiting_weekly_day    1-7
    waiting_chat_id       Telegram chat_id（整数，群组/频道为负数）

所有 FSM 支持 /cancel。降级兼容：log_admin_audit 不存在或失败时静默跳过。
"""

import logging

from aiogram import Bot, Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import config
from bot.database import get_config, set_config
from bot.keyboards.admin_kb import report_settings_cancel_kb
from bot.scheduler.tasks import (
    get_daily_report_time,
    get_weekly_report_day,
    get_weekly_report_time,
    reload_daily_report,
    reload_weekly_report,
    send_daily_report,
    send_weekly_report,
)
from bot.states.teacher_states import ReportSettingsStates
from bot.utils.permissions import admin_required

logger = logging.getLogger(__name__)

router = Router(name="report_settings")


_DAY_NAMES = {
    1: "周一", 2: "周二", 3: "周三", 4: "周四",
    5: "周五", 6: "周六", 7: "周日",
}


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


# ============ 设置主页 ============


def _settings_kb(daily_enabled: bool, weekly_enabled: bool) -> InlineKeyboardMarkup:
    """报表设置主页键盘（动态显示开启/关闭文案）"""
    daily_label = "❌ 关闭日报" if daily_enabled else "✅ 开启日报"
    weekly_label = "❌ 关闭周报" if weekly_enabled else "✅ 开启周报"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=daily_label, callback_data="admin:report:daily_toggle")],
        [InlineKeyboardButton(text="⏰ 修改日报时间", callback_data="admin:report:daily_time")],
        [InlineKeyboardButton(text=weekly_label, callback_data="admin:report:weekly_toggle")],
        [InlineKeyboardButton(text="⏰ 修改周报时间", callback_data="admin:report:weekly_time")],
        [InlineKeyboardButton(text="📅 修改周报星期", callback_data="admin:report:weekly_day")],
        [InlineKeyboardButton(text="👤 修改接收 ID", callback_data="admin:report:chat_id")],
        [
            InlineKeyboardButton(text="📤 测试日报", callback_data="admin:report:test_daily"),
            InlineKeyboardButton(text="📤 测试周报", callback_data="admin:report:test_weekly"),
        ],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="menu:main")],
    ])


async def _render_settings(target: types.Message | types.CallbackQuery) -> None:
    """渲染报表设置主页"""
    daily_enabled = (await get_config("daily_report_enabled")) == "1"
    daily_time = await get_daily_report_time()
    weekly_enabled = (await get_config("weekly_report_enabled")) == "1"
    weekly_time = await get_weekly_report_time()
    weekly_day = await get_weekly_report_day()
    weekly_day_name = _DAY_NAMES.get(weekly_day, "周日")

    chat_id_raw = await get_config("report_chat_id")
    if chat_id_raw:
        chat_id_display = chat_id_raw
    else:
        chat_id_display = f"{config.super_admin_id} (默认超管)"

    text = (
        "📨 自动报表设置\n\n"
        f"日报：{'✅ 开启' if daily_enabled else '❌ 关闭'}\n"
        f"日报时间：{daily_time}\n\n"
        f"周报：{'✅ 开启' if weekly_enabled else '❌ 关闭'}\n"
        f"周报日期：{weekly_day_name}\n"
        f"周报时间：{weekly_time}\n\n"
        f"接收 ID：{chat_id_display}"
    )
    kb = _settings_kb(daily_enabled, weekly_enabled)

    if isinstance(target, types.CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb)
        except Exception:
            await target.message.answer(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "admin:report_settings")
@admin_required
async def cb_report_settings(callback: types.CallbackQuery, state: FSMContext):
    """📨 报表设置主页（兼作 FSM 取消目标）"""
    await state.clear()
    await _render_settings(callback)
    await callback.answer()


# ============ /cancel 退出 FSM ============


@router.message(
    Command("cancel"),
    StateFilter(
        ReportSettingsStates.waiting_daily_time,
        ReportSettingsStates.waiting_weekly_time,
        ReportSettingsStates.waiting_weekly_day,
        ReportSettingsStates.waiting_chat_id,
    ),
)
@admin_required
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("已取消")
    await _render_settings(message)


# ============ 1. 开启/关闭日报 ============


@router.callback_query(F.data == "admin:report:daily_toggle")
@admin_required
async def cb_daily_toggle(callback: types.CallbackQuery):
    """切换 daily_report_enabled"""
    enabled = (await get_config("daily_report_enabled")) == "1"
    new_val = "0" if enabled else "1"
    await set_config("daily_report_enabled", new_val)
    await _safe_log_admin_audit(
        admin_id=callback.from_user.id,
        action="report_daily_toggle",
        target_type="config",
        target_id="daily_report_enabled",
        detail={"new_value": new_val},
    )
    await callback.answer(
        f"日报已{'关闭' if enabled else '开启'}",
        show_alert=False,
    )
    await _render_settings(callback)


# ============ 2. 修改日报时间 ============


@router.callback_query(F.data == "admin:report:daily_time")
@admin_required
async def cb_daily_time(callback: types.CallbackQuery, state: FSMContext):
    current = await get_daily_report_time()
    await state.set_state(ReportSettingsStates.waiting_daily_time)
    text = (
        "⏰ 修改日报时间\n\n"
        f"当前：{current}\n\n"
        "请输入新时间，格式 HH:MM（如 23:30）。\n"
        "/cancel 退出"
    )
    try:
        await callback.message.edit_text(text, reply_markup=report_settings_cancel_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=report_settings_cancel_kb())
    await callback.answer()


@router.message(ReportSettingsStates.waiting_daily_time)
@admin_required
async def on_daily_time(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if not _validate_hhmm(text):
        await message.reply(
            "❌ 时间格式无效，请输入 HH:MM（小时 0-23，分钟 0-59）",
            reply_markup=report_settings_cancel_kb(),
        )
        return
    await set_config("daily_report_time", text)
    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="report_time_update",
        target_type="config",
        target_id="daily_report_time",
        detail={"value": text},
    )
    reloaded = await reload_daily_report()
    note = "（定时任务已重载）" if reloaded else "（⚠️ 定时任务将在重启后生效）"
    await state.clear()
    await message.answer(f"✅ 日报时间已设为 {text} {note}")
    await _render_settings(message)


# ============ 3. 开启/关闭周报 ============


@router.callback_query(F.data == "admin:report:weekly_toggle")
@admin_required
async def cb_weekly_toggle(callback: types.CallbackQuery):
    enabled = (await get_config("weekly_report_enabled")) == "1"
    new_val = "0" if enabled else "1"
    await set_config("weekly_report_enabled", new_val)
    await _safe_log_admin_audit(
        admin_id=callback.from_user.id,
        action="report_weekly_toggle",
        target_type="config",
        target_id="weekly_report_enabled",
        detail={"new_value": new_val},
    )
    await callback.answer(
        f"周报已{'关闭' if enabled else '开启'}",
        show_alert=False,
    )
    await _render_settings(callback)


# ============ 4. 修改周报时间 ============


@router.callback_query(F.data == "admin:report:weekly_time")
@admin_required
async def cb_weekly_time(callback: types.CallbackQuery, state: FSMContext):
    current = await get_weekly_report_time()
    await state.set_state(ReportSettingsStates.waiting_weekly_time)
    text = (
        "⏰ 修改周报时间\n\n"
        f"当前：{current}\n\n"
        "请输入新时间，格式 HH:MM（如 23:00）。\n"
        "/cancel 退出"
    )
    try:
        await callback.message.edit_text(text, reply_markup=report_settings_cancel_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=report_settings_cancel_kb())
    await callback.answer()


@router.message(ReportSettingsStates.waiting_weekly_time)
@admin_required
async def on_weekly_time(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if not _validate_hhmm(text):
        await message.reply(
            "❌ 时间格式无效，请输入 HH:MM",
            reply_markup=report_settings_cancel_kb(),
        )
        return
    await set_config("weekly_report_time", text)
    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="report_time_update",
        target_type="config",
        target_id="weekly_report_time",
        detail={"value": text},
    )
    reloaded = await reload_weekly_report()
    note = "（定时任务已重载）" if reloaded else "（⚠️ 定时任务将在重启后生效）"
    await state.clear()
    await message.answer(f"✅ 周报时间已设为 {text} {note}")
    await _render_settings(message)


# ============ 5. 修改周报星期 ============


@router.callback_query(F.data == "admin:report:weekly_day")
@admin_required
async def cb_weekly_day(callback: types.CallbackQuery, state: FSMContext):
    current = await get_weekly_report_day()
    current_name = _DAY_NAMES.get(current, "周日")
    await state.set_state(ReportSettingsStates.waiting_weekly_day)
    text = (
        "📅 修改周报星期\n\n"
        f"当前：{current_name}（{current}）\n\n"
        "请输入数字 1-7：\n"
        "  1=周一，2=周二，3=周三，4=周四\n"
        "  5=周五，6=周六，7=周日\n\n"
        "/cancel 退出"
    )
    try:
        await callback.message.edit_text(text, reply_markup=report_settings_cancel_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=report_settings_cancel_kb())
    await callback.answer()


@router.message(ReportSettingsStates.waiting_weekly_day)
@admin_required
async def on_weekly_day(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.reply(
            "❌ 请输入纯数字 1-7",
            reply_markup=report_settings_cancel_kb(),
        )
        return
    d = int(text)
    if d < 1 or d > 7:
        await message.reply(
            "❌ 范围必须 1-7",
            reply_markup=report_settings_cancel_kb(),
        )
        return
    await set_config("weekly_report_day", str(d))
    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="report_time_update",
        target_type="config",
        target_id="weekly_report_day",
        detail={"value": d, "name": _DAY_NAMES.get(d)},
    )
    reloaded = await reload_weekly_report()
    note = "（定时任务已重载）" if reloaded else "（⚠️ 定时任务将在重启后生效）"
    await state.clear()
    await message.answer(f"✅ 周报星期已设为 {_DAY_NAMES.get(d)} {note}")
    await _render_settings(message)


# ============ 6. 修改接收 ID ============


@router.callback_query(F.data == "admin:report:chat_id")
@admin_required
async def cb_chat_id(callback: types.CallbackQuery, state: FSMContext):
    current = await get_config("report_chat_id")
    if not current:
        current_display = f"{config.super_admin_id}（默认超管）"
    else:
        current_display = current
    await state.set_state(ReportSettingsStates.waiting_chat_id)
    text = (
        "👤 修改报表接收 ID\n\n"
        f"当前：{current_display}\n\n"
        "请输入 Telegram chat_id（整数）：\n"
        "  · 私聊：自己的 user_id（正数）\n"
        "  · 群组/频道：负数（如 -100xxx）\n\n"
        "/cancel 退出"
    )
    try:
        await callback.message.edit_text(text, reply_markup=report_settings_cancel_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=report_settings_cancel_kb())
    await callback.answer()


@router.message(ReportSettingsStates.waiting_chat_id)
@admin_required
async def on_chat_id(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    try:
        cid = int(text)
    except ValueError:
        await message.reply(
            "❌ 请输入整数 chat_id",
            reply_markup=report_settings_cancel_kb(),
        )
        return
    await set_config("report_chat_id", str(cid))
    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="report_chat_update",
        target_type="config",
        target_id="report_chat_id",
        detail={"value": cid},
    )
    await state.clear()
    await message.answer(f"✅ 报表接收 ID 已设为 {cid}")
    await _render_settings(message)


# ============ 7 / 8. 立即测试发送 ============


@router.callback_query(F.data == "admin:report:test_daily")
@admin_required
async def cb_test_daily(callback: types.CallbackQuery):
    """立即发送日报测试（force=True 绕过 enabled 检查）"""
    ok = False
    try:
        ok = await send_daily_report(callback.bot, force=True)
    except Exception as e:
        logger.warning("test_daily 发送失败: %s", e)

    await _safe_log_admin_audit(
        admin_id=callback.from_user.id,
        action="report_test_send",
        target_type="report",
        target_id="daily",
        detail={"success": ok},
    )
    await callback.answer(
        "✅ 日报已发送" if ok else "⚠️ 发送失败，查看日志",
        show_alert=True,
    )


@router.callback_query(F.data == "admin:report:test_weekly")
@admin_required
async def cb_test_weekly(callback: types.CallbackQuery):
    """立即发送周报测试（force=True 绕过 enabled 检查）"""
    ok = False
    try:
        ok = await send_weekly_report(callback.bot, force=True)
    except Exception as e:
        logger.warning("test_weekly 发送失败: %s", e)

    await _safe_log_admin_audit(
        admin_id=callback.from_user.id,
        action="report_test_send",
        target_type="report",
        target_id="weekly",
        detail={"success": ok},
    )
    await callback.answer(
        "✅ 周报已发送" if ok else "⚠️ 发送失败，查看日志",
        show_alert=True,
    )


# ============ 工具：HH:MM 校验 ============


def _validate_hhmm(text: str) -> bool:
    """校验 HH:MM 格式"""
    if not text or ":" not in text:
        return False
    parts = text.split(":")
    if len(parts) != 2:
        return False
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError:
        return False
    return 0 <= h <= 23 and 0 <= m <= 59
