"""POST /api/auth/session —— initData 换 session token（P0·T5）。

前端启动时用 Telegram initData 调本端点；验签 + 角色解析后签发 session token，
后续请求带 ``Authorization: Bearer <token>``。本端点在中间件白名单内（免 session）。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.web.auth import InvalidInitData, issue_session, verify_init_data
from bot.web.keys import APP_BOT_TOKEN
from bot.web.roles import resolve_role

logger = logging.getLogger(__name__)


async def post_session(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(reason="invalid json body")

    init_data = (body or {}).get("init_data") or ""
    secret = request.app[APP_BOT_TOKEN]
    try:
        data = verify_init_data(init_data, secret)
    except InvalidInitData:
        # 不回显具体原因，避免给探测者反馈。
        raise web.HTTPUnauthorized(reason="invalid initData")

    role = await resolve_role(data.user_id)
    token = issue_session(data.user_id, role, secret)
    return web.json_response({
        "token": token,
        "role": role,
        "user_id": data.user_id,
    })
