"""鉴权中间件（P0·T5）。

公开路径（健康检查 / 换 token）放行；其余端点要求
``Authorization: Bearer <session>``，校验通过把 payload 注入
``request["session"]``，失败回 401（前端据此重新走 /api/auth/session 换 token）。
"""
from __future__ import annotations

import logging
import re

from aiohttp import web

from bot.web.auth import InvalidSession, verify_session
from bot.web.keys import APP_BOT_TOKEN

logger = logging.getLogger(__name__)

# 无需 session 的公开端点。
PUBLIC_PATHS: frozenset[str] = frozenset({"/api/health", "/api/auth/session"})

# 照片端点：浏览器 <img> 不带 Bearer，改用 URL 签名（handler 内校验），故放行 session。
_PHOTO_PATH = re.compile(r"^/api/teachers/\d+/photo$")

_BEARER_PREFIX = "Bearer "


def _is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or _PHOTO_PATH.match(path) is not None


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if _is_public(request.path):
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
