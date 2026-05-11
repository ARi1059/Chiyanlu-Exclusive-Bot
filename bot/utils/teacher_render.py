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


def build_teacher_card_keyboard(teacher: dict) -> InlineKeyboardMarkup | None:
    """构造老师卡片按钮组

    Step 2：仅"📩 联系老师"按钮（跳转 button_url）。
    Step 3 会扩展签名以支持收藏按钮。

    Returns:
        InlineKeyboardMarkup 或 None（当 button_url 无效时）
    """
    button_url = normalize_url(teacher["button_url"])
    if not button_url:
        return None
    button_text = teacher["button_text"] or teacher["display_name"]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📩 {button_text}", url=button_url)],
    ])


async def send_teacher_card(message: types.Message, teacher: dict):
    """发送老师完整卡片（图片+caption / 纯文字 + 按钮）

    button_url 无效时仍发文字内容，但不附按钮。
    """
    text = format_teacher_card_text(teacher)
    keyboard = build_teacher_card_keyboard(teacher)
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
