import json
import time
from html import escape
from typing import Tuple
from aiogram import Router, types
from aiogram.enums import ParseMode

from bot.config import config
from bot.database import (
    get_teacher_by_name,
    search_teachers_by_keyword,
    get_config,
)
from bot.utils.url import normalize_url

router = Router(name="keyword")

# 冷却时间记录: {(user_id, keyword): last_trigger_time}
_cooldown_cache: dict[Tuple[int, str], float] = {}


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


@router.message()
async def on_keyword_message(message: types.Message):
    """群组内关键词响应"""
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

    # 模式 A：精准匹配老师艺名
    teacher = await get_teacher_by_name(keyword)
    if teacher:
        await _send_teacher_card(message, teacher)

    # 模式 B：精准匹配标签/地区/价格
    matched = await search_teachers_by_keyword(keyword)
    # 如果模式 A 已匹配到该老师，从模式 B 结果中排除（避免重复）
    if teacher:
        matched = [t for t in matched if t["user_id"] != teacher["user_id"]]

    if matched:
        await _send_teacher_list(message, matched)


async def _send_teacher_card(message: types.Message, teacher: dict):
    """模式 A：发送老师完整卡片（图片+详情+按钮）"""
    tags = json.loads(teacher["tags"]) if teacher["tags"] else []
    tags_str = " | ".join(tags)

    text = (
        f"👤 {teacher['display_name']}\n"
        f"📍 {teacher['region']}\n"
        f"💰 {teacher['price']}\n"
        f"🏷️ {tags_str}"
    )

    button_text = teacher["button_text"] or teacher["display_name"]
    button_url = normalize_url(teacher["button_url"])
    keyboard = None
    if button_url:
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=f"📩 {button_text}", url=button_url)]
        ])

    if teacher["photo_file_id"]:
        await message.answer_photo(
            photo=teacher["photo_file_id"],
            caption=text,
            reply_markup=keyboard,
        )
    else:
        await message.answer(text, reply_markup=keyboard)


async def _send_teacher_list(message: types.Message, teachers: list[dict]):
    """模式 B：发送超链接列表"""
    lines = [f"🔍 找到 {len(teachers)} 位相关老师：\n"]
    for t in teachers:
        button_url = normalize_url(t["button_url"])
        if not button_url:
            continue
        url = escape(button_url, quote=True)
        display_name = escape(t["display_name"])
        region = escape(t["region"])
        price = escape(t["price"])
        line = f"<a href=\"{url}\">{display_name} - {region} - {price}</a>"
        lines.append(line)

    if len(lines) == 1:
        return

    await message.answer(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
