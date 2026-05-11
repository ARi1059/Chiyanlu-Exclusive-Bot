import time
from typing import Tuple
from aiogram import Router, types

from bot.config import config
from bot.database import (
    get_teacher_by_name,
    search_teachers_by_keyword,
    get_config,
)
from bot.utils.teacher_render import send_teacher_card, send_teacher_list

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
