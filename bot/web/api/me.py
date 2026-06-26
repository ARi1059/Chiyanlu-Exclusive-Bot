"""GET /api/me —— 返回当前 session 的身份与角色（P0·T5）。

身份来自鉴权中间件注入的 ``request["session"]``（已验签的 token payload）。
display_name 等富信息留待 P1（避免 P0 地基连 db）。
"""
from __future__ import annotations

from aiohttp import web


async def get_me(request: web.Request) -> web.Response:
    session = request["session"]
    return web.json_response({
        "user_id": session["uid"],
        "role": session["role"],
        "session_expires_at": session["exp"],
    })
