"""收藏端点（P1·MiniApp）。

    GET    /api/favorites           当前用户的收藏老师列表
    POST   /api/favorites           收藏一个老师（body: {teacher_id}）
    DELETE /api/favorites/{id}      取消收藏

复用 bot.database 的 favorites 写函数（幂等）。身份取自 session（中间件注入）。
"""
from __future__ import annotations

import json
import logging

from aiohttp import web

from bot.database import (
    add_favorite,
    get_teacher_channel_post,
    list_user_favorites,
    remove_favorite,
)

logger = logging.getLogger(__name__)


def _parse_tags(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    try:
        parsed = json.loads(raw or "[]")
        return [str(x) for x in parsed if x] if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


async def get_favorites(request: web.Request) -> web.Response:
    """当前用户收藏的老师（卡片字段，与 /api/teachers 同形）。"""
    uid = request["session"]["uid"]
    rows = await list_user_favorites(uid)  # 老师主键在 user_id 键上
    items = []
    for t in rows:
        tid = t["user_id"]
        post = await get_teacher_channel_post(tid)
        items.append({
            "id": tid,
            "name": t.get("display_name") or "",
            "region": t.get("region") or "",
            "price": t.get("price") or "",
            "tags": _parse_tags(t.get("tags")),
            "available": bool(t.get("is_active")),
            "rating": {
                "avg": round(float((post or {}).get("avg_overall") or 0), 1),
                "count": int((post or {}).get("review_count") or 0),
            },
            "has_photo": bool(t.get("photo_file_id")),
        })
    return web.json_response({"teachers": items})


async def post_favorite(request: web.Request) -> web.Response:
    """收藏一个老师。幂等：重复收藏不报错。"""
    uid = request["session"]["uid"]
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(reason="invalid json body")
    try:
        tid = int((body or {}).get("teacher_id"))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(reason="invalid teacher_id")
    await add_favorite(uid, tid)
    return web.json_response({"ok": True, "favorited": True})


async def delete_favorite(request: web.Request) -> web.Response:
    """取消收藏。删不存在的也返回成功（幂等）。"""
    uid = request["session"]["uid"]
    try:
        tid = int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid teacher id")
    await remove_favorite(uid, tid)
    return web.json_response({"ok": True, "favorited": False})
