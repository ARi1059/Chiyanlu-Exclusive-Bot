"""鉴权中间件（P0·T5）。

公开路径（健康检查 / 换 token）放行；其余端点要求
``Authorization: Bearer <session>``，校验通过把 payload 注入
``request["session"]``，失败回 401（前端据此重新走 /api/auth/session 换 token）。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.web.auth import InvalidSession, verify_session
from bot.web.keys import APP_BOT_TOKEN

logger = logging.getLogger(__name__)

# 无需 session 的公开端点。
PUBLIC_PATHS: frozenset[str] = frozenset({"/api/health", "/api/auth/session"})

_BEARER_PREFIX = "Bearer "


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if request.path in PUBLIC_PATHS:
        return await handler(request)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith(_BEARER_PREFIX):
        raise web.HTTPUnauthorized(reason="missing bearer token")

    token = auth[len(_BEARER_PREFIX):].strip()
    try:
        payload = verify_session(token, request.app[APP_BOT_TOKEN])
    except InvalidSession:
        raise web.HTTPUnauthorized(reason="invalid session")

    request["session"] = payload
    return await handler(request)
