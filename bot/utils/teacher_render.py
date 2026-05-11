"""老师卡片 / 列表的共享渲染工具

被 keyword.py（群组关键词响应）和 user_search.py（私聊搜索）共用。
Step 2 仅渲染"📩 联系老师"按钮；Step 3 会在此扩展"⭐ 收藏"按钮
（按 v2 §2.1.3：群组场景按钮恒为"⭐ 收藏"，私聊场景按收藏状态切换文本）。
"""

import json
from html import escape

from aiogram import types
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.utils.url import normalize_url


def format_teacher_card_text(teacher: dict) -> str:
    """构造老师卡片文本（用于 photo caption 或纯文字）"""
    try:
        tags = json.loads(teacher["tags"]) if teacher["tags"] else []
    except (json.JSONDecodeError, TypeError):
        tags = []
    tags_str = " | ".join(tags) if tags else "（无标签）"
    return (
        f"👤 {teacher['display_name']}\n"
        f"📍 {teacher['region']}\n"
        f"💰 {teacher['price']}\n"
        f"🏷️ {tags_str}"
    )


def build_teacher_card_keyboard(
    teacher: dict,
    *,
    is_group: bool = False,
    is_favorited: bool = False,
) -> InlineKeyboardMarkup | None:
    """构造老师卡片按钮组（v2 §2.1.3）

    布局：一行两个按钮 [📩 联系] [⭐ 收藏 / ✅ 已收藏(点击取消)]

    场景差异：
        - 群组场景 (is_group=True)：收藏按钮**恒为** "⭐ 收藏"，is_favorited 参数被忽略
          （群组卡片对所有人可见，无法按个体渲染状态）
        - 私聊场景 (is_group=False)：按 is_favorited 切换按钮文案
            · is_favorited=False → "⭐ 收藏"
            · is_favorited=True  → "✅ 已收藏(点击取消)"

    Args:
        teacher: 老师信息字典（含 user_id, button_url, button_text, display_name）
        is_group: 是否群组场景
        is_favorited: 私聊场景下当前用户对该老师的收藏状态

    Returns:
        InlineKeyboardMarkup（始终非 None，至少含收藏按钮）；button_url 无效时
        仅渲染收藏按钮单独一行
    """
    button_url = normalize_url(teacher["button_url"])
    button_text = teacher["button_text"] or teacher["display_name"]
    teacher_id = teacher["user_id"]

    # 收藏按钮文案：群组恒为"⭐ 收藏"，私聊按状态切换
    if is_group or not is_favorited:
        fav_btn = InlineKeyboardButton(
            text="⭐ 收藏",
            callback_data=f"fav:toggle:{teacher_id}",
        )
    else:
        fav_btn = InlineKeyboardButton(
            text="✅ 已收藏(点击取消)",
            callback_data=f"fav:toggle:{teacher_id}",
        )

    # 联系按钮（button_url 有效时与收藏按钮同行，否则单独一行）
    if button_url:
        row = [
            InlineKeyboardButton(text=f"📩 {button_text}", url=button_url),
            fav_btn,
        ]
    else:
        row = [fav_btn]

    return InlineKeyboardMarkup(inline_keyboard=[row])


async def send_teacher_card(
    message: types.Message,
    teacher: dict,
    *,
    is_group: bool = False,
    is_favorited: bool = False,
):
    """发送老师完整卡片（图片+caption / 纯文字 + 按钮）

    参数 is_group / is_favorited 透传给 build_teacher_card_keyboard。
    button_url 无效时仍发文字内容，按钮组退化为仅收藏按钮（行为不缺失）。
    """
    text = format_teacher_card_text(teacher)
    keyboard = build_teacher_card_keyboard(
        teacher, is_group=is_group, is_favorited=is_favorited
    )
    if teacher["photo_file_id"]:
        await message.answer_photo(
            photo=teacher["photo_file_id"],
            caption=text,
            reply_markup=keyboard,
        )
    else:
        await message.answer(text, reply_markup=keyboard)


def format_teacher_list_html(teachers: list[dict]) -> str | None:
    """构造老师超链接列表（HTML）

    每行格式：`<a href="button_url">艺名 - 地区 - 价格</a>`
    无效链接的老师跳过。全部跳过时返回 None。
    """
    valid_lines: list[str] = []
    for t in teachers:
        button_url = normalize_url(t["button_url"])
        if not button_url:
            continue
        url = escape(button_url, quote=True)
        display_name = escape(t["display_name"])
        region = escape(t["region"])
        price = escape(t["price"])
        valid_lines.append(
            f'<a href="{url}">{display_name} - {region} - {price}</a>'
        )

    if not valid_lines:
        return None

    header = f"🔍 找到 {len(valid_lines)} 位相关老师：\n"
    return header + "\n".join(valid_lines)


async def send_teacher_list(message: types.Message, teachers: list[dict]):
    """发送老师超链接列表（无图）"""
    html = format_teacher_list_html(teachers)
    if not html:
        return
    await message.answer(
        html,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
