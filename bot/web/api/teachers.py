"""老师数据端点（P1·MiniApp）。

    GET /api/teachers        列出在册老师（卡片所需字段 + 评分摘要）
    GET /api/teachers/{id}   单个老师详情（6 维雷达 + 已通过评价）

评分/评价数读 teacher_channel_posts 缓存（不实时聚合）；评价列表读
list_approved_reviews。照片不在此返回，前端用 /api/teachers/{id}/photo 拉取。
"""
from __future__ import annotations

import json
import logging

from aiohttp import web

from bot.database import (
    get_all_teachers,
    get_teacher_channel_post,
    get_teacher_full_profile,
    list_approved_reviews,
    list_user_favorites,
)
from bot.web.api.photo import signed_photo_url

logger = logging.getLogger(__name__)

# 6 维评分字段 → 前端雷达 subject（顺序与原型一致）
_DIM_FIELDS = [
    ("avg_humanphoto", "人像"),
    ("avg_appearance", "颜值"),
    ("avg_body", "身材"),
    ("avg_service", "服务"),
    ("avg_attitude", "态度"),
    ("avg_environment", "环境"),
]


def _parse_tags(raw) -> list[str]:
    """tags 列可能是 JSON 字符串或已解析的 list，统一成 list[str]。"""
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    try:
        parsed = json.loads(raw or "[]")
        return [str(x) for x in parsed if x] if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _rating(post: dict | None) -> dict:
    """从缓存行取 {avg, count}；无缓存时给 0。"""
    if not post:
        return {"avg": 0.0, "count": 0}
    return {
        "avg": round(float(post.get("avg_overall") or 0), 1),
        "count": int(post.get("review_count") or 0),
    }


def _has_photo(teacher: dict) -> bool:
    return bool(teacher.get("photo_file_id"))


async def get_teachers(request: web.Request) -> web.Response:
    """列出在册老师（is_active=1 且未删）。任意已登录角色可访问。"""
    uid = request["session"]["uid"]
    favs = await list_user_favorites(uid)
    fav_ids = {f["user_id"] for f in favs}  # 收藏列表里老师主键在 user_id 键
    teachers = await get_all_teachers(active_only=True, include_deleted=False)
    items = []
    for t in teachers:
        tid = t["user_id"]
        post = await get_teacher_channel_post(tid)
        items.append({
            "id": tid,
            "name": t.get("display_name") or "",
            "region": t.get("region") or "",
            "price": t.get("price") or "",
            "tags": _parse_tags(t.get("tags")),
            "available": bool(t.get("is_active")),
            "rating": _rating(post),
            "has_photo": _has_photo(t),
            "photo_url": signed_photo_url(request, tid, _has_photo(t)),
            "favorited": tid in fav_ids,
        })
    return web.json_response({"teachers": items})


def _mask_sig(review: dict) -> str:
    """评价者标识：匿名给「匿名」，否则用 user_id 末 4 位脱敏。"""
    if review.get("anonymous"):
        return "匿名"
    uid = str(review.get("user_id") or "")
    return ("****" + uid[-4:]) if len(uid) >= 4 else "****"


async def get_teacher_detail(request: web.Request) -> web.Response:
    """单个老师详情：基础字段 + 6 维雷达 + 已通过评价列表。"""
    try:
        tid = int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid teacher id")

    teacher = await get_teacher_full_profile(tid)
    if not teacher or teacher.get("is_deleted"):
        raise web.HTTPNotFound(reason="teacher not found")

    post = await get_teacher_channel_post(tid)
    dims = [
        {"subject": label, "A": round(float((post or {}).get(field) or 0), 1)}
        for field, label in _DIM_FIELDS
    ]

    raw_reviews = await list_approved_reviews(tid, limit=20)
    reviews = [{
        "id": r["id"],
        "rating": r.get("rating") or "neutral",
        "summary": r.get("summary") or "",
        "sig": _mask_sig(r),
        "created_at": r.get("created_at"),
    } for r in raw_reviews]

    return web.json_response({
        "id": tid,
        "name": teacher.get("display_name") or "",
        "region": teacher.get("region") or "",
        "price": teacher.get("price") or "",
        "tags": _parse_tags(teacher.get("tags")),
        "available": bool(teacher.get("is_active")),
        "rating": _rating(post),
        "dims": dims,
        "reviews": reviews,
        "has_photo": _has_photo(teacher),
        "photo_url": signed_photo_url(request, tid, _has_photo(teacher)),
    })
