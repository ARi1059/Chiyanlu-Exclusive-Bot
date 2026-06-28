from aiogram import Router, types, F
from aiogram.filters import StateFilter

from bot.services.teacher_checkin import perform_checkin

router = Router(name="teacher_checkin")


# StateFilter(None) 保证只在用户不在任何 FSM 状态时触发，避免误劫持搜索 /
# 评价 / 资料录入等流程中输入的文字（2026-05-18 P0 修复）。
@router.message(StateFilter(None), F.text == "签到")
async def on_checkin(message: types.Message):
    """老师私聊签到（文字「签到」）。业务逻辑委托 services.teacher_checkin。"""
    # 仅处理私聊消息
    if message.chat.type != "private":
        return

    result = await perform_checkin(message.from_user.id)
    status = result.status

    if status == "not_teacher":
        await message.reply("您未被授权使用此功能")
    elif status == "inactive":
        await message.reply("您的账号已被停用，请联系管理员")
    elif status == "closed":
        await message.reply(
            f"⏰ 今日签到已截止（截止时间 {result.deadline}）\n"
            "请明天再来签到"
        )
    elif status == "already":
        await message.reply("✅ 今日已签到，无需重复操作")
    elif status == "success":
        await message.reply(
            f"✅ 签到成功！\n\n"
            f"👤 {result.teacher['display_name']}\n"
            f"📅 {result.today_str}\n"
            f"⏰ {result.now_hm}"
        )
    else:  # failed
        await message.reply("⚠️ 签到失败，请稍后重试")
