"""个人主页端点（P1·MiniApp）。

    GET /api/profile   当前用户：用户名 / id / 角色 / 积分 / 评价数 / 收藏数

身份取自 session（中间件注入）。评价数只算 approved（与详情页口径一致）。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.database import (
    count_user_reviews,
    get_user,
    list_user_favorites,
)

logger = logging.getLogger(__name__)


async def get_profile(request: web.Request) -> web.Response:
    session = request["session"]
    uid = session["uid"]

    user = await get_user(uid)
    username = (user or {}).get("username") or ""
    first_name = (user or {}).get("first_name") or ""
    points = int((user or {}).get("total_points") or 0)

    review_count = await count_user_reviews(uid, status_filter="approved")
    fav_count = len(await list_user_favorites(uid))

    return web.json_response({
        "user_id": uid,
        "role": session["role"],
        "username": username,
        "first_name": first_name,
        "points": points,
        "review_count": review_count,
        "favorite_count": fav_count,
    })
