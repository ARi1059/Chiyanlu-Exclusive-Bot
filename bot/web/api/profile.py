"""个人主页端点（P1·MiniApp）。

    GET  /api/profile      当前用户：用户名 / id / 角色 / 积分 / 评价数 / 收藏数 / 通知开关
    GET  /api/me/points    积分流水（分页）
    GET  /api/me/reviews   我提交的评价（含状态）
    POST /api/me/notify    设置开课提醒通知开关（body: {enabled}）

身份取自 session（中间件注入）。评价数只算 approved（与详情页口径一致）。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.database import (
    count_user_reviews,
    get_teacher,
    get_user,
    get_user_total_points,
    list_user_favorites,
    list_user_point_transactions,
    list_user_reviews_paged,
    set_user_notify_enabled,
)

logger = logging.getLogger(__name__)

# 积分 reason → 中文文案（对齐 bot/utils/user_points_render 的标签）
_POINT_REASON_LABELS = {
    "review_approved": "评价通过",
    "admin_grant": "管理员加分",
    "admin_revoke": "管理员扣分",
    "lottery_entry": "抽奖参与",
    "lottery_refund": "抽奖退还",
}


async def get_profile(request: web.Request) -> web.Response:
    session = request["session"]
    uid = session["uid"]

    user = await get_user(uid)
    username = (user or {}).get("username") or ""
    first_name = (user or {}).get("first_name") or ""
    points = int((user or {}).get("total_points") or 0)
    # notify_enabled 默认 1（schema），未显式关闭即视为开启
    notify_enabled = bool((user or {}).get("notify_enabled", 1))

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
        "notify_enabled": notify_enabled,
    })


async def get_my_points(request: web.Request) -> web.Response:
    """当前用户积分流水（最近 50 条）+ 当前总分。"""
    uid = request["session"]["uid"]
    txs = await list_user_point_transactions(uid, limit=50)
    total = await get_user_total_points(uid)
    items = [{
        "delta": int(t.get("delta") or 0),
        "reason": t.get("reason") or "",
        "label": _POINT_REASON_LABELS.get(t.get("reason"), t.get("reason") or "积分变动"),
        "note": t.get("note") or "",
        "created_at": t.get("created_at"),
    } for t in txs]
    return web.json_response({"total": total, "transactions": items})


async def get_my_reviews(request: web.Request) -> web.Response:
    """当前用户提交的评价（最近 30 条，含审核状态）。"""
    uid = request["session"]["uid"]
    rows = await list_user_reviews_paged(uid, limit=30)
    items = []
    for r in rows:
        t = await get_teacher(r["teacher_id"])
        items.append({
            "id": r["id"],
            "teacher": (t or {}).get("display_name") or "未知",
            "rating": r.get("rating") or "neutral",
            "status": r.get("status") or "pending",
            "overall_score": round(float(r.get("overall_score") or 0), 1),
            "summary": r.get("summary") or "",
            "created_at": r.get("created_at"),
        })
    return web.json_response({"reviews": items})


async def post_notify(request: web.Request) -> web.Response:
    """设置开课提醒通知开关。"""
    uid = request["session"]["uid"]
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(reason="invalid json body")
    enabled = bool((body or {}).get("enabled"))
    await set_user_notify_enabled(uid, enabled)
    return web.json_response({"ok": True, "notify_enabled": enabled})
