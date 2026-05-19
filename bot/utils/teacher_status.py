"""老师签到状态共用 helper（UX-5.1）。

`teacher_main_menu_kb(checked_in=...)` 需要每个 caller 预先查"今日是否已签到"。
本模块封装这一步，避免 3 个 caller 重复 import datetime / pytz / config / is_checked_in。

设计：
    - 纯查询（无副作用），失败时（DB 异常 / chat 异常）回退为 False，
      让按钮显示默认"✅ 今日签到"而不是阻塞 caller。
    - today_str 计算与 bot/handlers/teacher_checkin.py / teacher_self.py 完全一致
      （bot.config.timezone 本地时区 → %Y-%m-%d）。
"""
from __future__ import annotations

import logging
from datetime import datetime

from pytz import timezone

from bot.config import config
from bot.database import is_checked_in

logger = logging.getLogger(__name__)


def _today_local_str() -> str:
    """本地时区的今日日期（%Y-%m-%d），与 teacher_checkin.py 一致。"""
    return datetime.now(timezone(config.timezone)).strftime("%Y-%m-%d")


async def teacher_checked_in_today(user_id: int) -> bool:
    """返回老师今日是否已签到；DB 异常时回退 False（不阻塞主流程）。

    用于 teacher_main_menu_kb(checked_in=...) 入参；切勿用于业务判定
    （业务判定应直接调用 is_checked_in，避免本函数的 fallback 行为掩盖错误）。
    """
    try:
        return await is_checked_in(user_id, _today_local_str())
    except Exception as e:
        logger.warning(
            "[UX-5.1] teacher_checked_in_today 查询失败 user=%s: %s", user_id, e,
        )
        return False
