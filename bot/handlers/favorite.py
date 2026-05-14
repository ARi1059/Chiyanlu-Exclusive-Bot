"""收藏相关 callback handlers（v2 §2.1 F1）

Callback 设计:
    - fav:toggle:<teacher_id>      切换收藏（卡片场景，群组/私聊通用）
    - fav:rm_from_list:<teacher_id> 我的收藏列表里点 ❌ 取消（私聊场景）
    - fav:invalid_url               私聊"我的收藏"里链接失效老师的占位 callback（仅 alert）

群组/私聊场景区分通过 callback.message.chat.type 判断；
未私聊过 bot 的群组用户额外发送 deep link 激活引导（v2 §2.1.4 混合方案）。
"""

import logging

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database import (
    get_teacher,
    get_user,
    list_user_favorites,
    remove_favorite,
    toggle_favorite,
    update_user_tags_from_teacher_action,
    upsert_user,
)
from bot.keyboards.user_kb import back_to_user_main_kb, my_favorites_kb
from bot.utils.teacher_render import build_teacher_card_keyboard

logger = logging.getLogger(__name__)

router = Router(name="favorite")


def _parse_teacher_id(data: str, prefix: str) -> int | None:
    """从 callback_data 解析 teacher_id；prefix 形如 'fav:toggle:'"""
    if not data.startswith(prefix):
        return None
    try:
        return int(data[len(prefix):])
    except ValueError:
        return None


def _is_group_chat(message: types.Message | None) -> bool:
    """判断 callback 关联的 message 是否来自群组"""
    return bool(
        message and message.chat and message.chat.type in ("group", "supergroup")
    )


async def _ensure_user_record(user: types.User) -> bool:
    """upsert_user 后返回该用户**先前**是否已私聊过 bot

    返回 True 表示已激活通知（last_started_bot=1）；False 表示未激活或新建。
    upsert_user 不动 last_started_bot 字段，所以查询要在 upsert 前后都有意义。
    """
    existing = await get_user(user.id)
    await upsert_user(user.id, user.username, user.first_name)
    return bool(existing and existing["last_started_bot"])


def _activation_hint_kb(bot_username: str) -> InlineKeyboardMarkup:
    """构造未激活用户的 deep link 引导按钮"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📩 激活通知",
            url=f"https://t.me/{bot_username}?start=activate",
        )]
    ])


# ============ fav:toggle —— 卡片场景的切换 ============

@router.callback_query(F.data.startswith("fav:toggle:"))
async def cb_fav_toggle(callback: types.CallbackQuery):
    """切换收藏（卡片场景：群组关键词卡片 / 私聊搜索卡片）

    群组场景:
        - 写入数据 + alert 反馈
        - 按钮文案不变（恒为 ⭐ 收藏，v2 §2.1.3）
        - 未私聊过 bot 的用户：alert 后另发引导消息（带 deep link 按钮）

    私聊场景:
        - 写入数据 + alert 反馈（show_alert=False，仅 toast）
        - edit_reply_markup 切换按钮文案（⭐ 收藏 ↔ ✅ 已收藏(点击取消)）
    """
    teacher_id = _parse_teacher_id(callback.data, "fav:toggle:")
    if teacher_id is None:
        await callback.answer("⚠️ 无效操作")
        return

    teacher = await get_teacher(teacher_id)
    if not teacher:
        await callback.answer("⚠️ 该老师已不存在", show_alert=True)
        return

    user = callback.from_user
    user_id = user.id
    display_name = teacher["display_name"]

    started_bot = await _ensure_user_record(user)
    is_fav_now = await toggle_favorite(user_id, teacher_id)

    # Phase 6.1：仅收藏成功时累加画像分；取消不扣分（群组 + 私聊卡片通用）
    if is_fav_now:
        await update_user_tags_from_teacher_action(
            user_id, teacher_id, "favorite_add",
        )

    is_group = _is_group_chat(callback.message)

    if is_group:
        # 群组：alert 反馈（200 字符内）
        if is_fav_now:
            alert = f"✅ 已收藏 {display_name}"
            if not started_bot:
                alert += "\n\n⚠️ 请激活通知，否则 14:00 收不到开课提醒"
        else:
            alert = f"已取消收藏 {display_name}"
        await callback.answer(alert, show_alert=True)

        # 未激活用户：另发一条引导消息（alert 不能附按钮，必须用 reply）
        if is_fav_now and not started_bot:
            try:
                me = await callback.bot.get_me()
                bot_username = me.username
                mention = f"@{user.username}" if user.username else user.first_name
                await callback.message.reply(
                    f"{mention}，请点击下方按钮激活通知，"
                    f"14:00 才能收到 {display_name} 的开课提醒。",
                    reply_markup=_activation_hint_kb(bot_username),
                )
            except Exception as e:
                # 群里无发言权限 / 网络异常都不阻塞主流程
                logger.warning("发送激活引导失败 (user=%s): %s", user_id, e)
        return

    # 私聊场景：toast + 按钮状态切换
    if is_fav_now:
        await callback.answer(f"✅ 已收藏 {display_name}")
    else:
        await callback.answer(f"已取消收藏 {display_name}")

    new_kb = build_teacher_card_keyboard(
        teacher, is_group=False, is_favorited=is_fav_now
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=new_kb)
    except Exception as e:
        # 编辑可能失败（消息过旧 / 已被编辑过 / 内容相同），不影响数据正确性
        logger.debug("edit_reply_markup 失败: %s", e)


# ============ fav:rm_from_list —— "我的收藏"列表的取消 ============

@router.callback_query(F.data.startswith("fav:rm_from_list:"))
async def cb_fav_rm_from_list(callback: types.CallbackQuery):
    """从"我的收藏"列表里点 ❌ 取消，然后刷新列表

    仅私聊场景（"我的收藏"只在私聊里出现）。
    """
    teacher_id = _parse_teacher_id(callback.data, "fav:rm_from_list:")
    if teacher_id is None:
        await callback.answer("⚠️ 无效操作")
        return

    user_id = callback.from_user.id

    # 先看一下被取消的是哪位老师（用于 toast 文案；老师可能已删除）
    teacher = await get_teacher(teacher_id)
    display_name = teacher["display_name"] if teacher else "该老师"

    # 即使已经不在收藏里（双击），remove_favorite 是幂等的
    await remove_favorite(user_id, teacher_id)
    await callback.answer(f"已取消收藏 {display_name}")

    # 刷新列表
    favorites = await list_user_favorites(user_id, active_only=True)
    if not favorites:
        await callback.message.edit_text(
            "⭐ 我的收藏\n\n你还没有收藏任何老师。\n试试 🔍 搜索老师 找一个。",
            reply_markup=back_to_user_main_kb(),
        )
        return

    text = f"⭐ 我的收藏（{len(favorites)} 位）\n\n点击老师跳转，点击 ❌ 取消收藏"
    try:
        await callback.message.edit_text(text, reply_markup=my_favorites_kb(favorites))
    except Exception as e:
        logger.debug("edit_text 刷新收藏列表失败: %s", e)


# ============ fav:invalid_url —— 链接失效占位（仅 alert） ============

@router.callback_query(F.data == "fav:invalid_url")
async def cb_fav_invalid_url(callback: types.CallbackQuery):
    """点击"我的收藏"列表中链接失效的老师按钮 → 给出提示"""
    await callback.answer(
        "该老师的链接已失效，请联系管理员更新",
        show_alert=True,
    )
