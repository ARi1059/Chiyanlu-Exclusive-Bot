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

# 图片端点：浏览器 <img> 不带 Bearer，改用 URL 签名（handler 内校验），故放行 session。
#   - 老师相册照片
#   - 评价审核媒体（约课截图 / 手势照），签名 URL 仅由超管详情端点下发
_PHOTO_PATH = re.compile(r"^/api/teachers/\d+/photo$")
_REVIEW_MEDIA_PATH = re.compile(r"^/api/admin/reviews/\d+/media/(?:booking|gesture)$")

_BEARER_PREFIX = "Bearer "


def _is_public(path: str) -> bool:
    return (
        path in PUBLIC_PATHS
        or _PHOTO_PATH.match(path) is not None
        or _REVIEW_MEDIA_PATH.match(path) is not None
    )


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


@web.middleware
async def analytics_middleware(request: web.Request, handler):
    """双轨埋点（§16.4）：对已鉴权请求打一条 ``web:active`` 事件。

    必须排在 ``auth_middleware`` 之后——它依赖后者注入的 ``request["session"]``。
    公开路径（health / auth / photo）没有 session，自然跳过。fire-and-forget：
    log_surface_event 内部已吞异常，埋点绝不阻断请求。
    """
    response = await handler(request)
    session = request.get("session")
    if session:
        uid = session.get("uid")
        if uid:
            try:
                from bot.database import log_surface_event
                await log_surface_event(
                    int(uid), "web", "active", {"path": request.path},
                )
            except Exception as e:  # pragma: no cover - 埋点不影响主链
                logger.debug("web 埋点失败 path=%s: %s", request.path, e)
    return response
