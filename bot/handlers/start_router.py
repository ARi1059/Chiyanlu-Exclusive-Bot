"""/start 命令角色分流入口（v2 §2.5 C1 私聊冷启动）

按角色分流到对应菜单:
    - 管理员（含超管） → 管理面板（v1 行为不变）
    - 老师（含停用 is_active=0） → 老师私聊菜单（Step 2 占位，Step 5 完整实现）
    - 普通用户 → 用户主菜单

多角色重叠时优先匹配高权限（管理员 > 老师 > 普通用户）。

Deep Link 参数:
    /start                  → 角色分流主流程
    /start activate         → 激活通知（mark_user_started），用于 Step 3 群组收藏的 deep link 流
    /start fav_<teacher_id> → Step 3 收藏 deep link 预留（本 Step 不处理具体收藏，仅占位）
"""

from aiogram import Router, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import (
    is_admin,
    get_teacher,
    upsert_user,
    mark_user_started,
)
from bot.keyboards.admin_kb import main_menu_kb
from bot.keyboards.user_kb import user_main_menu_kb

router = Router(name="start_router")


async def _is_admin_user(user_id: int) -> bool:
    """统一管理员判定：含超管"""
    return user_id == config.super_admin_id or await is_admin(user_id)


@router.message(CommandStart(deep_link=True))
async def cmd_start_with_arg(
    message: types.Message,
    command: CommandObject,
    state: FSMContext,
):
    """/start 带参数（deep link）入口

    解析 command.args 后做相应动作，最后仍走主流程展示对应菜单。
    """
    await state.clear()
    user = message.from_user
    user_id = user.id
    arg = (command.args or "").strip()

    # 普通用户身份层维护（管理员/老师也会进 users 表，便于后续统计；不影响 v1）
    await upsert_user(user_id, user.username, user.first_name)
    await mark_user_started(user_id)

    # Deep link 分支处理
    extra_text: str | None = None
    if arg == "activate":
        # Step 3 群组收藏后的"激活通知"入口（v2 §2.1.4）
        extra_text = "✅ 已激活开课通知，14:00 会收到收藏老师的开课提醒"
    elif arg.startswith("fav_"):
        # Step 3 收藏 deep link 预留：本 Step 不处理具体收藏，给提示
        extra_text = "⏳ 收藏功能即将上线，请稍后再试"

    await _route_by_role(message, user_id, extra_text=extra_text)


@router.message(CommandStart())
async def cmd_start_plain(message: types.Message, state: FSMContext):
    """/start 无参数入口：角色分流"""
    await state.clear()
    user = message.from_user
    user_id = user.id

    # 普通用户身份层维护
    await upsert_user(user_id, user.username, user.first_name)
    await mark_user_started(user_id)

    await _route_by_role(message, user_id)


async def _route_by_role(
    message: types.Message,
    user_id: int,
    extra_text: str | None = None,
):
    """根据角色展示对应菜单。

    优先级：管理员 > 老师 > 普通用户。
    extra_text 用于在菜单前展示一行额外提示（deep link 场景）。
    """
    # 1. 管理员
    if await _is_admin_user(user_id):
        text = "🔧 痴颜录管理面板"
        if extra_text:
            text = f"{extra_text}\n\n{text}"
        await message.answer(text, reply_markup=main_menu_kb())
        return

    # 2. 老师（含停用，v2 §2.5.5 决策 15）
    teacher = await get_teacher(user_id)
    if teacher:
        # Step 2 占位：老师私聊菜单完整实现留给 Step 5
        # 同时签到功能仍通过 v1 的 teacher_checkin.py 处理（发送文字"签到"）
        status = "" if teacher["is_active"] else "（账号已停用）"
        text = (
            f"👤 你好，{teacher['display_name']}{status}\n\n"
            "你的私聊功能：\n"
            "・发送『签到』完成今日签到\n"
            "・更多自助功能将在后续版本上线"
        )
        if extra_text:
            text = f"{extra_text}\n\n{text}"
        await message.answer(text)
        return

    # 3. 普通用户
    text = "👋 欢迎使用痴颜录 Bot\n\n请选择下方功能："
    if extra_text:
        text = f"{extra_text}\n\n{text}"
    await message.answer(text, reply_markup=user_main_menu_kb())
