from typing import Optional

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
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
    count_pending_edits,
    log_admin_audit,
    get_dashboard_metrics,
    list_recent_admin_audits,
    set_archive_channel_id,
    get_archive_channel_id,
    is_super_admin,
    count_pending_reviews,
)
from bot.keyboards.admin_kb import (
    main_menu_kb,
    teacher_menu_kb,
    admin_menu_kb,
    channel_menu_kb,
    system_menu_kb,
    admin_remove_kb,
    dashboard_menu_kb,
    dashboard_audit_back_kb,
)
from bot.states.teacher_states import (
    AddAdminStates,
    SetChannelStates,
    SetGroupStates,
    SystemSettingStates,
    SetArchiveChannelStates,
)
from bot.utils.permissions import admin_required, super_admin_required
from bot.scheduler.tasks import (
    reload_daily_publish,
    reload_checkin_reminder,
    build_daily_checkin_payload,
    send_daily_checkin,
    parse_publish_chat_ids,
)
from bot.utils.notifier import send_notification_to_user

router = Router(name="admin_panel")


def _today_str() -> str:
    """获取当前时区日期字符串"""
    return datetime.now(timezone(config.timezone)).strftime("%Y-%m-%d")


async def _build_main_menu_kb(user_id: Optional[int] = None):
    """构造主菜单 keyboard，带待审核角标 + 仅超管可见的 [📝 报告审核]（Phase 9.4）

    Args:
        user_id: 调用方 user_id；用于判断 is_super；None 时按非超管渲染
    """
    n = await count_pending_edits()
    is_super = False
    rcount = 0
    if user_id is not None:
        if user_id == config.super_admin_id or await is_super_admin(user_id):
            is_super = True
            rcount = await count_pending_reviews()
    return main_menu_kb(
        pending_count=n,
        pending_review_count=rcount,
        is_super=is_super,
    )


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


@router.message(Command("admin"))
@admin_required
async def cmd_admin(message: types.Message, state: FSMContext):
    """管理员发送 /admin 显示管理面板

    /start 命令由 start_router 统一处理并按角色分流（v2 §2.5.5）。
    管理员从 /start 进入也会走 start_router，最终调用 main_menu_kb。
    """
    await state.clear()
    await message.answer("🔧 痴颜录管理面板", reply_markup=await _build_main_menu_kb(message.from_user.id))


@router.callback_query(F.data == "menu:main")
@admin_required
async def cb_main_menu(callback: types.CallbackQuery, state: FSMContext):
    """返回主菜单"""
    await state.clear()
    await callback.message.edit_text("🔧 痴颜录管理面板", reply_markup=await _build_main_menu_kb(callback.from_user.id))
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
        await log_admin_audit(
            admin_id=message.from_user.id,
            action="admin_add",
            target_type="admin",
            target_id=user_id,
        )
        await message.answer(f"✅ 已添加管理员: {user_id}")
    else:
        await message.answer(f"⚠️ 该用户已是管理员: {user_id}")

    await state.clear()
    await message.answer("🔧 痴颜录管理面板", reply_markup=await _build_main_menu_kb(message.from_user.id))


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
        await log_admin_audit(
            admin_id=callback.from_user.id,
            action="admin_remove",
            target_type="admin",
            target_id=user_id,
        )
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

    chat_ids_str = ",".join(str(chat_id) for chat_id in chat_ids)
    await set_config("publish_channel_id", chat_ids_str)
    await log_admin_audit(
        admin_id=message.from_user.id,
        action="publish_channel_set",
        target_type="config",
        target_id="publish_channel_id",
        detail={"value": chat_ids_str},
    )
    await message.answer(f"✅ 发布目标已设置为: {chat_ids}")
    await state.clear()
    await message.answer("🔧 痴颜录管理面板", reply_markup=await _build_main_menu_kb(message.from_user.id))


@router.callback_query(F.data == "channel:set_archive")
@admin_required
async def cb_set_archive_channel(callback: types.CallbackQuery, state: FSMContext):
    """Phase 9.2：设置档案帖发布频道（单个 chat_id）"""
    current = await get_archive_channel_id()
    fallback_hint = ""
    if current is None:
        fallback_hint = "\n当前未配置（且 publish_channel_id 也为空）。"
    else:
        fallback_hint = f"\n当前生效值：{current}（独立配置或回退自发布目标）。"
    await state.set_state(SetArchiveChannelStates.waiting_chat_id)
    await callback.message.edit_text(
        "📦 请输入档案帖发布频道 Chat ID（单个数字，通常为负数）：\n\n"
        "档案帖用于发布老师完整资料 + 相册（媒体组），与每日签到帖解耦。\n"
        "未配置时回退使用 [📌 发布目标] 的第一个 ID。\n"
        "回复 0 表示清空独立配置（之后将回退 publish_channel_id）。"
        f"{fallback_hint}",
    )
    await callback.answer()


@router.message(SetArchiveChannelStates.waiting_chat_id)
@admin_required
async def on_archive_channel_id(message: types.Message, state: FSMContext):
    """Phase 9.2：接收档案频道 ID 并入库"""
    text = (message.text or "").strip()
    try:
        chat_id = int(text)
    except ValueError:
        await message.reply("❌ 请输入单个数字 ID（正负均可）。回复 0 清空。")
        return

    if chat_id == 0:
        await set_config("archive_channel_id", "")
        await log_admin_audit(
            admin_id=message.from_user.id,
            action="archive_channel_set",
            target_type="config",
            target_id="archive_channel_id",
            detail={"value": ""},
        )
        await message.answer("✅ 已清空独立档案频道配置（后续将回退 publish_channel_id）")
    else:
        await set_archive_channel_id(chat_id)
        await log_admin_audit(
            admin_id=message.from_user.id,
            action="archive_channel_set",
            target_type="config",
            target_id="archive_channel_id",
            detail={"value": str(chat_id)},
        )
        await message.answer(f"✅ 档案频道已设置为: {chat_id}")
    await state.clear()
    await message.answer("🔧 痴颜录管理面板", reply_markup=await _build_main_menu_kb(message.from_user.id))


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

    group_ids_str = ",".join(str(g) for g in group_ids)
    await set_config("response_group_ids", group_ids_str)
    await log_admin_audit(
        admin_id=message.from_user.id,
        action="response_group_set",
        target_type="config",
        target_id="response_group_ids",
        detail={"value": group_ids_str},
    )
    await message.answer(f"✅ 响应群组已设置: {group_ids}")
    await state.clear()
    await message.answer("🔧 痴颜录管理面板", reply_markup=await _build_main_menu_kb(message.from_user.id))


@router.callback_query(F.data == "channel:view")
@admin_required
async def cb_channel_view(callback: types.CallbackQuery):
    """查看当前频道/群组设置"""
    publish_id = await get_config("publish_channel_id")
    archive_id_raw = await get_config("archive_channel_id")
    archive_effective = await get_archive_channel_id()
    group_ids = await get_config("response_group_ids")

    if archive_id_raw:
        archive_display = f"{archive_id_raw}（独立配置）"
    elif archive_effective is not None:
        archive_display = f"{archive_effective}（回退 publish_channel_id）"
    else:
        archive_display = "未设置"

    lines = ["📋 当前设置：\n"]
    lines.append(f"📌 发布目标: {publish_id or '未设置'}")
    lines.append(f"📦 档案频道: {archive_display}")
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

    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="publish_manual",
        target_type="publish",
        target_id=today,
        detail={
            "success_count": len(success),
            "failed_count": len(failed),
            "success_targets": success,
        },
    )

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


@router.callback_query(F.data == "test:fav_notification")
@admin_required
async def cb_test_fav_notification(callback: types.CallbackQuery):
    """测试收藏通知（F2，v2 Step 4）

    仅给**当前点击的管理员**发其自身的"收藏 ∩ 签到"聚合通知，便于自测
    无副作用，不影响其他用户。
    """
    today = _today_str()
    user = callback.from_user

    success, n = await send_notification_to_user(
        callback.bot,
        user.id,
        user.first_name,
        user.username,
        today,
    )

    if n == 0:
        await callback.answer(
            f"你的收藏老师在 {today} 没有人签到，\n无可发送内容",
            show_alert=True,
        )
        return

    if success:
        await callback.answer(
            f"✅ 测试通知已发送（含 {n} 位老师），请查收私聊",
            show_alert=True,
        )
    else:
        await callback.answer(
            "⚠️ 推送失败：你可能未私聊过 bot，\n请先私聊 bot 发送 /start 再重试",
            show_alert=True,
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
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="reminder_toggle",
        target_type="config",
        target_id="checkin_reminder_enabled",
        detail={"new_value": new_value},
    )
    status = "关闭" if enabled else "开启"
    await callback.answer(f"签到提醒已{status}", show_alert=True)
    await callback.message.edit_text("⚙️ 系统设置", reply_markup=system_menu_kb())


@router.callback_query(F.data == "system:lottery_contact")
@super_admin_required
async def cb_set_lottery_contact_from_system(callback: types.CallbackQuery, state: FSMContext):
    """[👨‍💼 抽奖客服链接] 入口（系统设置）；与抽奖管理入口共用 FSM"""
    from bot.handlers.admin_lottery import _enter_contact_url_fsm
    await _enter_contact_url_fsm(callback.message, state, edit=True)
    await callback.answer()


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
        await log_admin_audit(
            admin_id=message.from_user.id,
            action="publish_time_set",
            target_type="config",
            target_id="publish_time",
            detail={"value": text},
        )
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
        await log_admin_audit(
            admin_id=message.from_user.id,
            action="reminder_time_set",
            target_type="config",
            target_id="checkin_reminder_time",
            detail={"value": text},
        )
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
        await log_admin_audit(
            admin_id=message.from_user.id,
            action="cooldown_set",
            target_type="config",
            target_id="cooldown_seconds",
            detail={"value": text},
        )
        await message.answer(f"✅ 冷却时间已修改为: {text} 秒")

    else:
        await message.answer("⚠️ 未知设置项")

    await state.clear()
    await message.answer("🔧 痴颜录管理面板", reply_markup=await _build_main_menu_kb(message.from_user.id))


# ============ 数据看板（Phase 1） ============


_AUDIT_ACTION_LABELS: dict[str, str] = {
    "admin_add": "添加管理员",
    "admin_remove": "移除管理员",
    "publish_channel_set": "设置发布目标",
    "archive_channel_set": "设置档案频道",
    "response_group_set": "设置响应群组",
    "publish_time_set": "修改发布时间",
    "cooldown_set": "修改冷却时间",
    "reminder_time_set": "修改提醒时间",
    "reminder_toggle": "切换签到提醒",
    "publish_manual": "手动发布",
    "review_approve": "审核通过",
    "review_reject": "审核驳回",
    "teacher_publish_to_channel": "发布档案帖到频道",
    "teacher_channel_repost": "重发档案帖",
    "teacher_channel_caption_update": "同步档案 caption",
    "teacher_channel_post_delete": "删除频道档案帖",
    "subreq_add": "添加必关频道/群组",
    "subreq_remove": "删除必关频道/群组",
    "subreq_toggle": "启停必关频道/群组",
    "rreview_view": "查看报告",
    "rreview_approve": "通过报告",
    "rreview_reject": "驳回报告",
    "points_query": "查询用户积分",
    "points_grant": "手动加扣积分",
    "lottery_create": "创建抽奖",
    "lottery_cancel": "取消抽奖",
    "lottery_publish": "发布抽奖到频道",
    "lottery_entry": "参与抽奖",
    "lottery_repost": "重发抽奖帖",
    "lottery_contact_set": "设置抽奖客服链接",
    "lottery_edit": "编辑抽奖",
}


def _format_audit_detail(action: str, detail: str | None, target_id: str | None) -> str:
    """把审计 detail 字段格式化成易读的一行摘要"""
    parts: list[str] = []
    if target_id:
        parts.append(f"#{target_id}")
    if detail:
        # detail 大部分时候是 JSON 字符串，能解析就提关键字段，不能就原样截断
        try:
            import json as _json
            data = _json.loads(detail)
            if isinstance(data, dict):
                for k, v in list(data.items())[:3]:
                    parts.append(f"{k}={v}")
            else:
                parts.append(str(data)[:80])
        except Exception:
            parts.append(detail[:80])
    return " ".join(parts) if parts else ""


@router.callback_query(F.data == "dashboard:enter")
@admin_required
async def cb_dashboard_enter(callback: types.CallbackQuery):
    """数据看板主视图"""
    tz = timezone(config.timezone)
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    since_str = (now - timedelta(days=6)).strftime("%Y-%m-%d")  # 含今天共 7 天
    metrics = await get_dashboard_metrics(today_str, since_str)

    events = metrics["events_today"]

    def _ev(name: str) -> int:
        return events.get(name, 0)

    lines = [
        "📊 数据看板",
        f"📅 {today_str}（近 7 日窗口含今日）",
        "━━━━━━━━━━━━━━━",
        "【用户】",
        f"👥 总用户: {metrics['total_users']}",
        f"🆕 新增: 今日 {metrics['new_users_today']} / 7日 {metrics['new_users_range']}",
        f"🟢 活跃: 今日 {metrics['active_today']} / 7日 {metrics['active_range']}",
        f"🔔 可推送: {metrics['reachable_users']}",
        "",
        "【老师】",
        f"👩‍🏫 启用 / 停用: {metrics['active_teachers']} / {metrics['inactive_teachers']}",
        f"📈 今日签到: {metrics['checkins_today']}/{metrics['active_teachers']}",
        f"⭐ 累计收藏关系: {metrics['total_favorites']}",
        "",
        "【今日行为】",
        f"🚪 启动 /start: {_ev('start')}",
        f"🔍 搜索: {_ev('search')}",
        f"⭐ 新收藏: {_ev('favorite_add')}",
        f"🗑 取消收藏: {_ev('favorite_remove')}",
        f"📚 查看今日开课: {_ev('view_today')}",
        f"💝 查看收藏开课: {_ev('view_fav_signed_in')}",
        "",
        "【运营】",
        f"📝 待审核: {metrics['pending_reviews']}",
        f"🚀 今日发布: {metrics['publishes_today']} 条",
        f"🛡️ 今日管理员操作: {metrics['audits_today']} 次",
        "━━━━━━━━━━━━━━━",
    ]

    # 用户行为埋点尚未在所有用户侧入口接入时，给个提示
    if not events:
        lines.append("ℹ️ 今日暂无用户事件记录（埋点接入中）")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=dashboard_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "dashboard:audit")
@admin_required
async def cb_dashboard_audit(callback: types.CallbackQuery):
    """管理员操作日志（最近 20 条）"""
    rows = await list_recent_admin_audits(limit=20)
    if not rows:
        await callback.message.edit_text(
            "📜 操作日志\n\n(暂无记录)",
            reply_markup=dashboard_audit_back_kb(),
        )
        await callback.answer()
        return

    lines = ["📜 操作日志（最近 20 条）", "━━━━━━━━━━━━━━━"]
    for r in rows:
        ts = (r.get("created_at") or "").replace("T", " ")[:19]
        action_label = _AUDIT_ACTION_LABELS.get(r["action"], r["action"])
        admin_label = f"@{r['admin_username']}" if r.get("admin_username") else str(r["admin_id"])
        summary = _format_audit_detail(r["action"], r.get("detail"), r.get("target_id"))
        line = f"• {ts}  {admin_label}  {action_label}"
        if summary:
            line += f"  {summary}"
        lines.append(line)

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=dashboard_audit_back_kb(),
    )
    await callback.answer()


# ============ 通用取消 ============


@router.callback_query(F.data == "action:cancel")
async def cb_cancel(callback: types.CallbackQuery, state: FSMContext):
    """取消当前操作"""
    await state.clear()
    await callback.message.edit_text("🔧 痴颜录管理面板", reply_markup=await _build_main_menu_kb(callback.from_user.id))
    await callback.answer("已取消")
