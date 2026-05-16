"""群组内关键词响应 + 群内快捷入口（Phase 7.3 §五）

匹配优先级:
    1. 老师艺名精确命中  → 老师卡片（v2 行为不变）
    2. 标签/地区/价格命中 → 老师列表（v2 行为不变）
    3. 快捷入口关键词     → 私聊跳转按钮（菜单/今日/热门/筛选/推荐）

模式 1 + 模式 2 仍可同时命中（一个老师卡片 + 该老师从列表里排除）。
快捷入口只在模式 1、2 都未命中时触发，避免与老师同名词冲突。
"""

import logging
import time
from typing import Tuple
from aiogram import Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import config
from bot.database import (
    get_teacher_by_name,
    search_teachers_by_keyword,
    get_config,
)
from bot.utils.teacher_render import send_teacher_card, send_teacher_list

logger = logging.getLogger(__name__)

router = Router(name="keyword")

# 冷却时间记录: {(user_id, keyword): last_trigger_time}
_cooldown_cache: dict[Tuple[int, str], float] = {}


# Phase 7.3 §五：群内快捷入口关键词 → 私聊 deep link 落地
# value 与 start_router._QUICK_ENTRY_PAGES 的 key 一一对应
_QUICK_ENTRY_KEYWORDS: dict[str, tuple[str, str]] = {
    # keyword: (group banner, deep_link_suffix)
    "菜单": ("📲 进入痴颜录 Bot", "menu"),
    "今日": ("📚 今日开课入口", "today"),
    "热门": ("🔥 热门推荐入口", "hot"),
    "筛选": ("🔎 条件筛选入口", "filter"),
    "推荐": ("🎯 帮我推荐入口", "recommend"),
}


# 群内快捷入口出现时附带的 3 个跳转按钮（一致体验）
_QUICK_ENTRY_FOLLOW_BUTTONS: list[tuple[str, str]] = [
    # (button text, deep_link_suffix)
    ("📚 打开今日开课", "today"),
    ("🔥 热门推荐", "hot"),
    ("🔎 按条件筛选", "filter"),
]


async def _get_response_group_ids() -> list[int]:
    """获取响应群组 ID 列表"""
    raw = await get_config("response_group_ids")
    if not raw:
        return []
    try:
        return [int(g.strip()) for g in raw.split(",") if g.strip()]
    except ValueError:
        return []


async def _get_cooldown() -> int:
    """获取冷却时间（秒）"""
    val = await get_config("cooldown_seconds")
    if val and val.isdigit():
        return int(val)
    return config.cooldown_seconds


def _check_cooldown(user_id: int, keyword: str, cooldown: int) -> bool:
    """检查冷却时间，返回 True 表示在冷却中"""
    key = (user_id, keyword.lower())
    now = time.time()
    last = _cooldown_cache.get(key, 0)
    if now - last < cooldown:
        return True
    _cooldown_cache[key] = now
    return False


async def _safe_log_event(user_id: int, event_type: str, payload=None) -> None:
    try:
        from bot.database import log_user_event  # type: ignore
    except ImportError:
        return
    try:
        await log_user_event(user_id, event_type, payload)
    except Exception as e:
        logger.debug("log_user_event(%s) 失败: %s", event_type, e)


def _build_quick_entry_kb(
    bot_username: str,
    primary_target: str,
    primary_label: str,
) -> InlineKeyboardMarkup:
    """Phase 7.3：群内快捷入口的 URL deep link 按钮组

    所有按钮都用 t.me/<bot>?start=<target> URL 跳转私聊（不使用 callback，
    spec §五 要求群内按钮使用 URL deep link）。
    """
    base = f"https://t.me/{bot_username}"

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            text=primary_label,
            url=f"{base}?start={primary_target}",
        )],
    ]
    # 附 2 个常用快捷入口（排除已作为主按钮的那个）
    follow_row: list[InlineKeyboardButton] = []
    for label, suffix in _QUICK_ENTRY_FOLLOW_BUTTONS:
        if suffix == primary_target:
            continue
        follow_row.append(InlineKeyboardButton(
            text=label,
            url=f"{base}?start={suffix}",
        ))
        if len(follow_row) == 2:
            break
    if follow_row:
        rows.append(follow_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_quick_entry(
    message: types.Message,
    keyword: str,
) -> None:
    """群内匹配到快捷入口关键词时的轻量回复"""
    banner, target = _QUICK_ENTRY_KEYWORDS[keyword]

    # 取 bot username（构造 t.me deep link）
    try:
        me = await message.bot.get_me()
        bot_username = me.username
    except Exception as e:
        logger.warning("get_me 失败，跳过快捷入口: %s", e)
        return

    if not bot_username:
        return

    # 主按钮文案：与 banner 对齐
    primary_label_map = {
        "menu":      "📲 打开主菜单",
        "today":     "📚 打开今日开课",
        "hot":       "🔥 打开热门推荐",
        "filter":    "🔎 打开条件筛选",
        "recommend": "🎯 打开帮我推荐",
    }
    primary_label = primary_label_map.get(target, "📲 进入 Bot")

    body = (
        f"{banner}\n\n"
        "点击下方按钮进入私聊查看完整功能。"
    )
    try:
        await message.reply(
            body,
            reply_markup=_build_quick_entry_kb(bot_username, target, primary_label),
            disable_web_page_preview=True,
        )
    except Exception as e:
        # 群里无发言权限 / 网络异常都不阻塞主流程
        logger.warning("发送群内快捷入口失败: %s", e)
        return

    # 埋点
    user_id = message.from_user.id if message.from_user else 0
    await _safe_log_event(
        user_id,
        "group_quick_entry",
        {"keyword": keyword, "target": target, "chat_id": message.chat.id},
    )


@router.message()
async def on_keyword_message(message: types.Message):
    """群组内关键词响应 + 群内快捷入口"""
    # 仅处理群组/超级群组消息
    if message.chat.type not in ("group", "supergroup"):
        return

    # 仅处理纯文本消息
    if not message.text:
        return

    # 检查是否在指定响应群组内
    group_ids = await _get_response_group_ids()
    if not group_ids:
        return
    if message.chat.id not in group_ids:
        return

    keyword = message.text.strip()
    if not keyword:
        return

    # 冷却检查
    cooldown = await _get_cooldown()
    if _check_cooldown(message.from_user.id, keyword, cooldown):
        return

    # 模式 A：精准匹配老师艺名（群组场景，按钮恒为 ⭐ 收藏，v2 §2.1.3）
    teacher = await get_teacher_by_name(keyword)
    if teacher:
        await send_teacher_card(message, teacher, is_group=True)

    # 模式 B：精准匹配标签/地区/价格（多人列表无个体收藏按钮，行为不变）
    matched = await search_teachers_by_keyword(keyword)
    # 如果模式 A 已匹配到该老师，从模式 B 结果中排除（避免重复）
    if teacher:
        matched = [t for t in matched if t["user_id"] != teacher["user_id"]]

    if matched:
        await send_teacher_list(message, matched)

    # Phase 7.3 §五：快捷入口（仅当模式 A/B 均未命中时触发，避免与老师同名词冲突）
    if not teacher and not matched and keyword in _QUICK_ENTRY_KEYWORDS:
        await _send_quick_entry(message, keyword)
