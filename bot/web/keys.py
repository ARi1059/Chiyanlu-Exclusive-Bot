"""aiohttp Application 共享键（P0·T4）。

集中定义 web.AppKey，消除 NotAppKeyWarning，并避免 server / middleware / api
之间为取键而循环 import。
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiohttp import web

logger = logging.getLogger(__name__)

# 值可能为 None（集成测试不传 bot）；AppKey 不做运行时类型校验。
APP_BOT = web.AppKey("bot", Bot)
APP_BOT_TOKEN = web.AppKey("bot_token", str)

# bot 用户名缓存一次（不变）。供深链构造 t.me 链接（报销同意 / 写评价）。
_bot_username: str | None = None


async def get_bot_username(app: web.Application) -> str:
    """取 bot @username（缓存）。bot 不可用 / 异常时返回空串。"""
    global _bot_username
    if _bot_username is None:
        try:
            me = await app.get(APP_BOT).get_me()
            _bot_username = me.username or ""
        except Exception:
            logger.warning("get_me 取 bot username 失败", exc_info=True)
            return ""
    return _bot_username
