"""老师自助管理 handler（v2 §2.3 F3）

入口:
    - start_router 识别老师角色后展示 teacher_main_menu_kb（在私聊里）
    - 这里处理:
        · teacher_self:menu       回到老师主菜单
        · teacher_self:profile    展示当前资料 + 字段选择面板
        · teacher_self:edit:<f>   选定字段进入 FSM 等待新值
        · teacher_self:locked:<f> 锁定字段点击提示
        · teacher_self:checkin    用按钮触发签到（v2 §2.5.5 决策 16，与"发文字签到"并存）
    - FSM message handler:接收新值，立即生效（图片例外）+ 创建 edit_request + 通知管理员

字段例外（v2 §2.3.3a）:
    · 文字字段（5 个）:UPDATE teachers 立即生效 + INSERT edit_request
    · 图片字段（photo_file_id）:不动 teachers + INSERT edit_request
      展示位继续用旧图，审核通过后才切换
"""

import json
import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from pytz import timezone

from bot.config import config
from bot.database import (
    checkin_teacher,
    get_config,
    get_teacher,
    is_checked_in,
)
from bot.keyboards.teacher_self_kb import (
    FIELD_LABELS,
    teacher_back_to_profile_kb,
    teacher_edit_cancel_kb,
    teacher_main_menu_kb,
    teacher_profile_kb,
)
from bot.services.teacher_self_edit import EDITABLE_FIELDS, submit_field_edit
from bot.states.teacher_self_states import TeacherEditStates

logger = logging.getLogger(__name__)

router = Router(name="teacher_self")

tz = timezone(config.timezone)


# ========================================================
# 渲染辅助
# ========================================================

def _format_teacher_profile_text(teacher: dict) -> str:
    """构造资料展示文本"""
    try:
        tags = json.loads(teacher["tags"]) if teacher["tags"] else []
    except (json.JSONDecodeError, TypeError):
        tags = []
    tags_str = " | ".join(tags) if tags else "（空）"
    status = "" if teacher["is_active"] else "  ⚠️ 已停用"

    return (
        f"✏️ 你的资料{status}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 ID: {teacher['user_id']}\n"
        f"📛 用户名: @{teacher['username']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📝 艺名: {teacher['display_name']}\n"
        f"📍 地区: {teacher['region']}\n"
        f"💰 价格: {teacher['price']}\n"
        f"🏷️ 标签: {tags_str}\n"
        f"🖼️ 图片: {'已上传' if teacher['photo_file_id'] else '（空）'}\n"
        f"🔠 按钮文本: {teacher['button_text'] or '（默认用艺名）'}\n"
        f"🔗 链接: {teacher['button_url']}（不可自助修改）\n"
        f"━━━━━━━━━━━━━━━\n"
        f"点击下方按钮修改对应字段，修改后管理员将审核。"
    )


def _format_field_prompt(field_name: str, current_value: str | None) -> str:
    """构造"等待输入新值"的提示文本"""
    label = FIELD_LABELS.get(field_name, field_name)
    current = "（空）" if current_value is None or current_value == "" else current_value

    if field_name == "photo_file_id":
        return (
            f"🖼️ 修改图片\n"
            f"━━━━━━━━━━━━━━━\n"
            f"当前: {'已上传' if current_value else '（空）'}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"请发送新的图片（直接发图）。\n\n"
            f"⚠️ 图片修改采用「审核通过后生效」策略：\n"
            f"在管理员审核期间，展示位仍使用旧图。\n\n"
            f"发送 /cancel 取消修改。"
        )
    if field_name == "tags":
        return (
            f"🏷️ 修改标签\n"
            f"━━━━━━━━━━━━━━━\n"
            f"当前: {current}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"请输入新标签，用空格或逗号分隔。\n"
            f"例如：御姐 颜值 服务好\n\n"
            f"修改后立即生效，管理员会审核（如不通过会回滚）。\n"
            f"发送 /cancel 取消修改。"
        )
    return (
        f"修改{label}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"当前: {current}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"请输入新{label}。\n\n"
        f"修改后立即生效，管理员会审核（如不通过会回滚）。\n"
        f"发送 /cancel 取消修改。"
    )


# 注：标签解析 _parse_tags、管理员通知 _notify_admins 已抽到
# bot/services/teacher_self_edit.py（bot/web 同源），本文件不再重复实现。


# ========================================================
# 老师主菜单 callbacks
# ========================================================

@router.callback_query(F.data == "teacher_self:menu")
async def cb_teacher_menu(callback: types.CallbackQuery, state: FSMContext):
    """回到老师主菜单"""
    if not _is_teacher_chat(callback):
        await callback.answer()
        return
    await state.clear()
    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return
    status = "" if teacher["is_active"] else "（账号已停用）"
    # UX-5.1：动态决定签到按钮文案
    from bot.utils.teacher_status import teacher_checked_in_today
    checked = await teacher_checked_in_today(int(teacher["user_id"]))
    await callback.message.edit_text(
        f"👤 你好，{teacher['display_name']}{status}\n\n"
        "你的私聊功能：",
        reply_markup=teacher_main_menu_kb(checked_in=checked),
    )
    await callback.answer()


@router.callback_query(F.data == "teacher_self:profile")
async def cb_profile(callback: types.CallbackQuery, state: FSMContext):
    """展示当前资料 + 字段编辑面板"""
    if not _is_teacher_chat(callback):
        await callback.answer()
        return
    await state.clear()
    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return
    await callback.message.edit_text(
        _format_teacher_profile_text(teacher),
        reply_markup=teacher_profile_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "teacher_self:locked:button_url")
async def cb_locked_button_url(callback: types.CallbackQuery):
    """点击锁定字段（链接）→ 提示由管理员管理"""
    await callback.answer(
        "🔗 链接由管理员管理，无法自助修改\n"
        "如需调整，请联系管理员",
        show_alert=True,
    )


# ========================================================
# 字段编辑入口 + FSM
# ========================================================

@router.callback_query(F.data.startswith("teacher_self:edit:"))
async def cb_edit_field(callback: types.CallbackQuery, state: FSMContext):
    """选定字段，进入 FSM 等待新值"""
    if not _is_teacher_chat(callback):
        await callback.answer()
        return

    field_name = callback.data[len("teacher_self:edit:"):]
    if field_name not in EDITABLE_FIELDS:
        await callback.answer("⚠️ 无效字段", show_alert=True)
        return

    teacher = await get_teacher(callback.from_user.id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return

    current_value = teacher.get(field_name)
    await state.set_state(TeacherEditStates.waiting_new_value)
    await state.set_data({"field_name": field_name})

    await callback.message.edit_text(
        _format_field_prompt(field_name, current_value),
        reply_markup=teacher_edit_cancel_kb(),
    )
    await callback.answer()


@router.message(TeacherEditStates.waiting_new_value, Command("cancel"))
async def cmd_cancel_edit(message: types.Message, state: FSMContext):
    """老师在编辑 FSM 状态下发 /cancel 退出"""
    if message.chat.type != "private":
        return
    await state.clear()
    # UX-5.1：动态决定签到按钮文案
    from bot.utils.teacher_status import teacher_checked_in_today
    checked = await teacher_checked_in_today(message.from_user.id)
    await message.answer(
        "已取消修改",
        reply_markup=teacher_main_menu_kb(checked_in=checked),
    )


@router.message(TeacherEditStates.waiting_new_value)
async def on_edit_value(message: types.Message, state: FSMContext):
    """接收老师输入的新值 → 委托 service 提交（立即生效/图片延后 + edit_request + 通知）。

    handler 只负责传输层（私聊判定 + 取图片 file_id / 文本）；业务逻辑全在
    bot/services/teacher_self_edit.submit_field_edit（bot/web 同源）。
    校验类错误（空 / 过长 / 同值 / 空标签）不退出 FSM，让老师改了再发。
    """
    if message.chat.type != "private":
        return

    user_id = message.from_user.id
    data = await state.get_data()
    field_name: str = data.get("field_name", "")
    if field_name not in EDITABLE_FIELDS:
        await state.clear()
        await message.reply("⚠️ 异常：未知字段，请重新进入编辑")
        return

    # 取原始新值：图片字段取最高分辨率 file_id，文字字段取文本（传输层差异留在 handler）。
    if field_name == "photo_file_id":
        if not message.photo:
            await message.reply("请发送图片（直接发图，不是文字），或 /cancel 取消")
            return
        raw_value: str = message.photo[-1].file_id
    else:
        if not message.text:
            await message.reply("请输入文字内容，或 /cancel 取消")
            return
        raw_value = message.text

    result = await submit_field_edit(message.bot, user_id, field_name, raw_value)

    if not result["ok"]:
        code = result.get("error")
        # 校验类错误：保持 FSM，提示后等待老师重新输入。
        if code in {"empty", "too_long", "empty_tags", "same"}:
            await message.reply(f"⚠️ {result['message']}，请重新输入或 /cancel 取消")
            return
        # 其它（not_teacher / update_failed / unknown_field / create_request_failed）：退出。
        await state.clear()
        await message.reply(f"⚠️ {result['message']}")
        return

    await state.clear()
    await message.answer(result["message"], reply_markup=teacher_back_to_profile_kb())


# ========================================================
# 签到按钮（v2 §2.5.5 决策 16，与 v1 文字"签到"并存）
# ========================================================

@router.callback_query(F.data == "teacher_self:checkin")
async def cb_button_checkin(callback: types.CallbackQuery, state: FSMContext):
    """按钮触发签到（行为同 v1 teacher_checkin.on_checkin）"""
    if not _is_teacher_chat(callback):
        await callback.answer()
        return
    await state.clear()
    user_id = callback.from_user.id

    teacher = await get_teacher(user_id)
    if not teacher:
        await callback.answer("⚠️ 你不在老师名单内", show_alert=True)
        return
    if not teacher["is_active"]:
        await callback.answer("⚠️ 你的账号已被停用", show_alert=True)
        return

    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")

    # 签到截止时间窗口（同 v1）
    publish_time = await get_config("publish_time") or config.publish_time
    hour, minute = map(int, publish_time.split(":"))
    if now.hour > hour or (now.hour == hour and now.minute >= minute):
        await callback.answer(
            f"⏰ 今日签到已截止（{publish_time}）\n请明天再来",
            show_alert=True,
        )
        return

    if await is_checked_in(user_id, today_str):
        await callback.answer("✅ 今日已签到，无需重复操作", show_alert=True)
        return

    ok = await checkin_teacher(user_id, today_str)
    if not ok:
        await callback.answer("⚠️ 签到失败，请稍后重试", show_alert=True)
        return

    # UX-5.1：签到成功后立即把当前菜单的"✅ 今日签到"刷新为"✅ 今日已签到"
    try:
        await callback.message.edit_reply_markup(
            reply_markup=teacher_main_menu_kb(checked_in=True),
        )
    except Exception as e:
        logger.info(
            "[UX-5.1] 签到成功后菜单刷新失败 user=%s: %s", user_id, e,
        )

    await callback.answer(
        f"✅ 签到成功 - {today_str} {now.strftime('%H:%M')}",
        show_alert=True,
    )


# ========================================================
# 工具
# ========================================================

def _is_teacher_chat(callback: types.CallbackQuery) -> bool:
    """只在私聊里响应；群组里收到也视为无效（应不会发生）"""
    return bool(
        callback.message
        and callback.message.chat
        and callback.message.chat.type == "private"
    )
