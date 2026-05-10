from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from datetime import datetime
from pytz import timezone

from bot.config import config
from bot.database import (
    get_all_admins,
    add_admin,
    remove_admin,
    get_config,
    set_config,
    get_all_teachers,
    get_checkin_stats,
    get_teacher_counts,
    get_sent_messages,
    checkin_teacher,
)
from bot.keyboards.admin_kb import (
    main_menu_kb,
    teacher_menu_kb,
    admin_menu_kb,
    channel_menu_kb,
    system_menu_kb,
    admin_remove_kb,
)
from bot.states.teacher_states import (
    AddAdminStates,
    SetChannelStates,
    SetGroupStates,
    SystemSettingStates,
)
from bot.utils.permissions import admin_required, super_admin_required
from bot.scheduler.tasks import (
    reload_daily_publish,
    reload_checkin_reminder,
    build_daily_checkin_payload,
    send_daily_checkin,
    parse_publish_chat_ids,
)

router = Router(name="admin_panel")


def _today_str() -> str:
    """获取当前时区日期字符串"""
    return datetime.now(timezone(config.timezone)).strftime("%Y-%m-%d")


def _format_teacher_names(teachers: list[dict], limit: int = 20) -> str:
    """格式化老师名称列表"""
    if not teachers:
        return "无"
    names = [t["display_name"] for t in teachers[:limit]]
    suffix = f" 等 {len(teachers)} 位" if len(teachers) > limit else ""
    return "、".join(names) + suffix


def _format_publish_result(success: list[int], failed: list[tuple[int, str]]) -> str:
    """格式化多目标发布结果"""
    lines = [f"成功: {len(success)} 个目标"]
    if success:
        lines.append("已发送: " + ", ".join(str(chat_id) for chat_id in success))
    if failed:
        lines.append(f"失败: {len(failed)} 个目标")
        for chat_id, error in failed:
            lines.append(f"- {chat_id}: {error}")
    return "\n".join(lines)


# ============ 主菜单 ============


@router.message(Command("start", "admin"))
@admin_required
async def cmd_admin(message: types.Message, state: FSMContext):
    """管理员发送 /start 或 /admin 显示管理面板"""
    await state.clear()
    await message.answer("🔧 痴颜录管理面板", reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:main")
@admin_required
async def cb_main_menu(callback: types.CallbackQuery, state: FSMContext):
    """返回主菜单"""
    await state.clear()
    await callback.message.edit_text("🔧 痴颜录管理面板", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "menu:teacher")
@admin_required
async def cb_teacher_menu(callback: types.CallbackQuery):
    """老师管理子面板"""
    await callback.message.edit_text("👩‍🏫 老师管理", reply_markup=teacher_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "menu:admin")
@super_admin_required
async def cb_admin_menu(callback: types.CallbackQuery):
    """管理员管理子面板（仅超管）"""
    await callback.message.edit_text("👥 管理员管理", reply_markup=admin_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "menu:channel")
@admin_required
async def cb_channel_menu(callback: types.CallbackQuery):
    """频道设置子面板"""
    await callback.message.edit_text("📢 频道/群组设置", reply_markup=channel_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "menu:system")
@admin_required
async def cb_system_menu(callback: types.CallbackQuery):
    """系统设置子面板"""
    await callback.message.edit_text("⚙️ 系统设置", reply_markup=system_menu_kb())
    await callback.answer()


# ============ 管理员管理 ============


@router.callback_query(F.data == "admin:add")
@super_admin_required
async def cb_admin_add(callback: types.CallbackQuery, state: FSMContext):
    """添加管理员 - 进入等待输入状态"""
    await state.set_state(AddAdminStates.waiting_user_id)
    await callback.message.edit_text(
        "📝 请输入要添加的管理员 Telegram 数字 ID：\n\n"
        "提示：可让对方发送消息给 @userinfobot 获取 ID",
    )
    await callback.answer()


@router.message(AddAdminStates.waiting_user_id)
@super_admin_required
async def on_admin_user_id(message: types.Message, state: FSMContext):
    """接收管理员 ID 并添加"""
    text = message.text.strip()
    if not text.isdigit():
        await message.reply("❌ 请输入有效的数字 ID")
        return

    user_id = int(text)
    if user_id == config.super_admin_id:
        await message.reply("❌ 超级管理员无需重复添加")
        await state.clear()
        return

    success = await add_admin(user_id)
    if success:
        await message.answer(f"✅ 已添加管理员: {user_id}")
    else:
        await message.answer(f"⚠️ 该用户已是管理员: {user_id}")

    await state.clear()
    await message.answer("🔧 痴颜录管理面板", reply_markup=main_menu_kb())


@router.callback_query(F.data == "admin:remove")
@super_admin_required
async def cb_admin_remove(callback: types.CallbackQuery):
    """移除管理员 - 展示列表"""
    admins = await get_all_admins()
    non_super = [a for a in admins if not a["is_super"]]
    if not non_super:
        await callback.answer("当前没有可移除的管理员", show_alert=True)
        return
    await callback.message.edit_text(
        "👥 选择要移除的管理员：",
        reply_markup=admin_remove_kb(admins),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:confirm_remove:"))
@super_admin_required
async def cb_admin_confirm_remove(callback: types.CallbackQuery):
    """确认移除管理员"""
    user_id = int(callback.data.split(":")[2])
    success = await remove_admin(user_id)
    if success:
        await callback.answer("✅ 已移除", show_alert=True)
    else:
        await callback.answer("⚠️ 移除失败", show_alert=True)
    await callback.message.edit_text("👥 管理员管理", reply_markup=admin_menu_kb())


@router.callback_query(F.data == "admin:list")
@super_admin_required
async def cb_admin_list(callback: types.CallbackQuery):
    """管理员列表"""
    admins = await get_all_admins()
    if not admins:
        text = "📋 当前无管理员"
    else:
        lines = ["📋 管理员列表：\n"]
        for a in admins:
            role = "👑 超管" if a["is_super"] else "🔧 管理"
            name = f"@{a['username']}" if a["username"] else str(a["user_id"])
            lines.append(f"  {role} {name} (ID: {a['user_id']})")
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=admin_menu_kb())
    await callback.answer()


# ============ 频道设置 ============


@router.callback_query(F.data == "channel:set_publish")
@admin_required
async def cb_set_publish_channel(callback: types.CallbackQuery, state: FSMContext):
    """设置发布目标"""
    await state.set_state(SetChannelStates.waiting_channel_id)
    await callback.message.edit_text(
        "📌 请输入发布目标 Chat ID（频道或群组，数字，通常为负数）：\n\n"
        "支持多个目标，用逗号分隔。例如：-100123456,-100789012\n"
        "提示：频道/群组都需要先添加 Bot，并授予发送消息权限",
    )
    await callback.answer()


@router.message(SetChannelStates.waiting_channel_id)
@admin_required
async def on_publish_channel_id(message: types.Message, state: FSMContext):
    """接收发布目标 ID"""
    text = message.text.strip()
    try:
        chat_ids = parse_publish_chat_ids(text)
    except ValueError:
        await message.reply("❌ 请输入有效的数字 ID，多个用逗号分隔")
        return

    if not chat_ids:
        await message.reply("❌ 请至少输入一个发布目标 ID")
        return

    await set_config("publish_channel_id", ",".join(str(chat_id) for chat_id in chat_ids))
    await message.answer(f"✅ 发布目标已设置为: {chat_ids}")
    await state.clear()
    await message.answer("🔧 痴颜录管理面板", reply_markup=main_menu_kb())


@router.callback_query(F.data == "channel:set_response")
@admin_required
async def cb_set_response_group(callback: types.CallbackQuery, state: FSMContext):
    """设置响应群组"""
    await state.set_state(SetGroupStates.waiting_group_id)
    await callback.message.edit_text(
        "💬 请输入响应群组的 Chat ID（数字，通常为负数）：\n\n"
        "支持多个群组，用逗号分隔。例如：-100123456,-100789012",
    )
    await callback.answer()


@router.message(SetGroupStates.waiting_group_id)
@admin_required
async def on_response_group_id(message: types.Message, state: FSMContext):
    """接收响应群组 ID"""
    text = message.text.strip()
    # 验证每个 ID 是否为有效数字
    parts = [p.strip() for p in text.split(",")]
    try:
        group_ids = [int(p) for p in parts]
    except ValueError:
        await message.reply("❌ 请输入有效的数字 ID，多个用逗号分隔")
        return

    await set_config("response_group_ids", ",".join(str(g) for g in group_ids))
    await message.answer(f"✅ 响应群组已设置: {group_ids}")
    await state.clear()
    await message.answer("🔧 痴颜录管理面板", reply_markup=main_menu_kb())


@router.callback_query(F.data == "channel:view")
@admin_required
async def cb_channel_view(callback: types.CallbackQuery):
    """查看当前频道/群组设置"""
    publish_id = await get_config("publish_channel_id")
    group_ids = await get_config("response_group_ids")

    lines = ["📋 当前设置：\n"]
    lines.append(f"📌 发布目标: {publish_id or '未设置'}")
    lines.append(f"💬 响应群组: {group_ids or '未设置'}")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=channel_menu_kb(),
    )
    await callback.answer()


# ============ 系统设置 ============


@router.callback_query(F.data == "system:status")
@admin_required
async def cb_system_status(callback: types.CallbackQuery):
    """系统状态检查"""
    today = _today_str()
    publish_id = await get_config("publish_channel_id")
    group_ids = await get_config("response_group_ids")
    publish_time = await get_config("publish_time") or config.publish_time
    cooldown = await get_config("cooldown_seconds") or str(config.cooldown_seconds)
    reminder_enabled = (await get_config("checkin_reminder_enabled")) == "1"
    reminder_time = await get_config("checkin_reminder_time") or "13:00"
    teacher_counts = await get_teacher_counts()
    stats = await get_checkin_stats(today)
    sent_messages = await get_sent_messages(today)

    lines = [
        "系统状态检查",
        "━━━━━━━━━━━━━━━",
        f"📌 发布目标: {'已设置 ' + publish_id if publish_id else '未设置'}",
        f"💬 响应群组: {'已设置 ' + group_ids if group_ids else '未设置'}",
        f"⏰ 发布时间: {publish_time}",
        f"⏳ 冷却时间: {cooldown} 秒",
        f"🔔 签到提醒: {'开启' if reminder_enabled else '关闭'} ({reminder_time})",
        f"👩‍🏫 老师总数: {teacher_counts['total']}",
        f"✅ 启用老师: {teacher_counts['active']}",
        f"❌ 停用老师: {teacher_counts['inactive']}",
        f"📈 今日签到: {stats['checked_count']}/{stats['active_total']} ({stats['rate']}%)",
        f"🚀 今日发布记录: {len(sent_messages)} 条",
        "━━━━━━━━━━━━━━━",
    ]

    warnings = []
    if not publish_id:
        warnings.append("未设置发布目标，定时发布会跳过")
    if not group_ids:
        warnings.append("未设置响应群组，关键词响应不会生效")
    if teacher_counts["active"] == 0:
        warnings.append("当前没有启用老师")

    if warnings:
        lines.append("⚠️ 需要处理：")
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("✅ 基础配置正常")

    await callback.message.edit_text("\n".join(lines), reply_markup=system_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "publish:preview")
@admin_required
async def cb_publish_preview(callback: types.CallbackQuery):
    """预览今日发布内容"""
    today = _today_str()
    payload = await build_daily_checkin_payload(today)
    if payload is None:
        await callback.answer("今日暂无老师签到", show_alert=True)
        return

    text, keyboard = payload
    await callback.message.answer(f"发布预览\n\n{text}", reply_markup=keyboard)
    await callback.answer("已发送预览")


@router.callback_query(F.data == "publish:manual")
@admin_required
async def cb_publish_manual(callback: types.CallbackQuery):
    """手动发布今日签到汇总"""
    today = _today_str()
    raw_chat_ids = await get_config("publish_channel_id")
    try:
        chat_ids = parse_publish_chat_ids(raw_chat_ids)
    except ValueError:
        await callback.answer("发布目标配置无效", show_alert=True)
        return

    if not chat_ids:
        await callback.answer("未设置发布目标", show_alert=True)
        return

    payload = await build_daily_checkin_payload(today)
    if payload is None:
        await callback.answer("今日暂无老师签到", show_alert=True)
        return

    success = []
    failed = []
    for chat_id in chat_ids:
        try:
            msg = await send_daily_checkin(callback.bot, chat_id, today)
            if msg:
                success.append(chat_id)
            else:
                failed.append((chat_id, "今日暂无老师签到"))
        except Exception as e:
            failed.append((chat_id, str(e)))

    if success:
        await callback.answer("已发布", show_alert=True)
    else:
        await callback.answer("发布失败，请查看详情", show_alert=True)

    await callback.message.answer(
        f"手动发布 {today} 签到汇总完成\n" + _format_publish_result(success, failed)
    )


@router.callback_query(F.data == "test:checkin_publish")
@admin_required
async def cb_test_checkin_publish(callback: types.CallbackQuery):
    """测试签到记录和多目标发送"""
    today = _today_str()
    raw_chat_ids = await get_config("publish_channel_id")
    try:
        chat_ids = parse_publish_chat_ids(raw_chat_ids)
    except ValueError:
        await callback.answer("发布目标配置无效", show_alert=True)
        return

    if not chat_ids:
        await callback.answer("未设置发布目标", show_alert=True)
        return

    teachers = await get_all_teachers(active_only=True)
    if not teachers:
        await callback.answer("当前没有启用老师", show_alert=True)
        return

    teacher = teachers[0]
    checkin_created = await checkin_teacher(teacher["user_id"], today)
    payload = await build_daily_checkin_payload(today)
    if payload is None:
        await callback.answer("没有可发送的有效签到内容", show_alert=True)
        await callback.message.answer(
            "测试失败：已尝试写入签到记录，但没有可发送的有效内容。\n"
            "请检查老师按钮链接是否有效。"
        )
        return

    success = []
    failed = []
    for chat_id in chat_ids:
        try:
            msg = await send_daily_checkin(callback.bot, chat_id, today)
            if msg:
                success.append(chat_id)
            else:
                failed.append((chat_id, "未生成频道/群组消息"))
        except Exception as e:
            failed.append((chat_id, str(e)))

    checkin_status = "新增签到" if checkin_created else "今日已签到，复用现有记录"
    if success:
        await callback.answer("测试完成", show_alert=True)
    else:
        await callback.answer("测试发送失败", show_alert=True)

    await callback.message.answer(
        "测试完成\n"
        f"日期：{today}\n"
        f"测试老师：{teacher['display_name']} (ID: {teacher['user_id']})\n"
        f"签到状态：{checkin_status}\n"
        + _format_publish_result(success, failed)
    )


@router.callback_query(F.data == "checkin:stats")
@admin_required
async def cb_checkin_stats(callback: types.CallbackQuery):
    """今日签到统计"""
    today = _today_str()
    stats = await get_checkin_stats(today)
    lines = [
        f"{today} 签到统计",
        "━━━━━━━━━━━━━━━",
        f"启用老师: {stats['active_total']} 位",
        f"已签到: {stats['checked_count']} 位",
        f"未签到: {stats['unchecked_count']} 位",
        f"签到率: {stats['rate']}%",
        "━━━━━━━━━━━━━━━",
        f"✅ 已签到：{_format_teacher_names(stats['checked_in'])}",
        f"❌ 未签到：{_format_teacher_names(stats['unchecked'])}",
    ]
    await callback.message.edit_text("\n".join(lines), reply_markup=system_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "system:reminder_time")
@admin_required
async def cb_set_reminder_time(callback: types.CallbackQuery, state: FSMContext):
    """修改签到提醒时间"""
    current = await get_config("checkin_reminder_time") or "13:00"
    await state.set_state(SystemSettingStates.waiting_value)
    await state.set_data({"setting": "checkin_reminder_time"})
    await callback.message.edit_text(
        f"🔔 当前签到提醒时间: {current}\n\n"
        "请输入新的提醒时间（格式 HH:MM，如 13:00）：",
    )
    await callback.answer()


@router.callback_query(F.data == "system:reminder_toggle")
@admin_required
async def cb_toggle_reminder(callback: types.CallbackQuery):
    """切换签到提醒开关"""
    enabled = (await get_config("checkin_reminder_enabled")) == "1"
    new_value = "0" if enabled else "1"
    await set_config("checkin_reminder_enabled", new_value)
    status = "关闭" if enabled else "开启"
    await callback.answer(f"签到提醒已{status}", show_alert=True)
    await callback.message.edit_text("⚙️ 系统设置", reply_markup=system_menu_kb())


@router.callback_query(F.data == "system:publish_time")
@admin_required
async def cb_set_publish_time(callback: types.CallbackQuery, state: FSMContext):
    """修改发布时间"""
    current = await get_config("publish_time") or config.publish_time
    await state.set_state(SystemSettingStates.waiting_value)
    await state.set_data({"setting": "publish_time"})
    await callback.message.edit_text(
        f"⏰ 当前发布时间: {current}\n\n"
        "请输入新的发布时间（格式 HH:MM，如 14:00）：",
    )
    await callback.answer()


@router.callback_query(F.data == "system:cooldown")
@admin_required
async def cb_set_cooldown(callback: types.CallbackQuery, state: FSMContext):
    """修改冷却时间"""
    current = await get_config("cooldown_seconds") or str(config.cooldown_seconds)
    await state.set_state(SystemSettingStates.waiting_value)
    await state.set_data({"setting": "cooldown_seconds"})
    await callback.message.edit_text(
        f"⏳ 当前冷却时间: {current} 秒\n\n"
        "请输入新的冷却时间（秒数）：",
    )
    await callback.answer()


@router.message(SystemSettingStates.waiting_value)
@admin_required
async def on_system_setting_value(message: types.Message, state: FSMContext):
    """接收系统设置值"""
    data = await state.get_data()
    setting = data.get("setting")
    text = message.text.strip()

    if setting == "publish_time":
        # 验证时间格式
        parts = text.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            await message.reply("❌ 格式错误，请输入 HH:MM 格式（如 14:00）")
            return
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            await message.reply("❌ 时间无效，小时 0-23，分钟 0-59")
            return
        await set_config("publish_time", text)
        reloaded_time = await reload_daily_publish()
        if reloaded_time:
            await message.answer(f"✅ 发布时间已修改为: {text}\n定时任务已重载")
        else:
            await message.answer(f"✅ 发布时间已修改为: {text}\n⚠️ 定时任务将在重启后生效")

    elif setting == "checkin_reminder_time":
        parts = text.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            await message.reply("❌ 格式错误，请输入 HH:MM 格式（如 13:00）")
            return
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            await message.reply("❌ 时间无效，小时 0-23，分钟 0-59")
            return
        await set_config("checkin_reminder_time", text)
        reloaded_time = await reload_checkin_reminder()
        if reloaded_time:
            await message.answer(f"✅ 签到提醒时间已修改为: {text}\n定时任务已重载")
        else:
            await message.answer(f"✅ 签到提醒时间已修改为: {text}\n⚠️ 定时任务将在重启后生效")

    elif setting == "cooldown_seconds":
        if not text.isdigit() or int(text) < 0:
            await message.reply("❌ 请输入有效的正整数（秒数）")
            return
        await set_config("cooldown_seconds", text)
        await message.answer(f"✅ 冷却时间已修改为: {text} 秒")

    else:
        await message.answer("⚠️ 未知设置项")

    await state.clear()
    await message.answer("🔧 痴颜录管理面板", reply_markup=main_menu_kb())


# ============ 通用取消 ============


@router.callback_query(F.data == "action:cancel")
async def cb_cancel(callback: types.CallbackQuery, state: FSMContext):
    """取消当前操作"""
    await state.clear()
    await callback.message.edit_text("🔧 痴颜录管理面板", reply_markup=main_menu_kb())
    await callback.answer("已取消")
