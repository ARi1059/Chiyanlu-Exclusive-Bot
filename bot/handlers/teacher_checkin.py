from datetime import datetime

from aiogram import Router, types, F
from pytz import timezone

from bot.config import config
from bot.database import get_teacher, is_checked_in, checkin_teacher, get_config
from bot.keyboards.teacher_self_kb import time_picker_kb

router = Router(name="teacher_checkin")

# 北京时间时区
tz = timezone(config.timezone)


@router.message(F.text == "签到")
async def on_checkin(message: types.Message):
    """老师私聊签到"""
    # 仅处理私聊消息
    if message.chat.type != "private":
        return

    user_id = message.from_user.id

    # 验证是否为已录入老师
    teacher = await get_teacher(user_id)
    if not teacher:
        await message.reply("您未被授权使用此功能")
        return

    if not teacher["is_active"]:
        await message.reply("您的账号已被停用，请联系管理员")
        return

    # 获取当前北京时间
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")

    # 检查签到时间窗口：00:00 - 发布时间
    publish_time = await get_config("publish_time") or config.publish_time
    hour, minute = map(int, publish_time.split(":"))
    if now.hour > hour or (now.hour == hour and now.minute >= minute):
        await message.reply(
            f"⏰ 今日签到已截止（截止时间 {publish_time}）\n"
            "请明天再来签到"
        )
        return

    # 检查是否已签到
    if await is_checked_in(user_id, today_str):
        await message.reply("✅ 今日已签到，无需重复操作")
        return

    # 执行签到
    success = await checkin_teacher(user_id, today_str)
    if success:
        await message.reply(
            f"✅ 签到成功！\n\n"
            f"👤 {teacher['display_name']}\n"
            f"📅 {today_str}\n"
            f"⏰ {now.strftime('%H:%M')}"
        )
        # Phase 5：签到后提示设置今日可约时间
        await message.answer(
            "请选择今日可约时间：",
            reply_markup=time_picker_kb(),
        )
    else:
        await message.reply("⚠️ 签到失败，请稍后重试")
