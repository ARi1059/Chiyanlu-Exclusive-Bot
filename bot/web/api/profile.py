"""个人主页端点（P1·MiniApp）。

    GET  /api/profile      当前用户：用户名 / id / 角色 / 积分 / 评价数 / 收藏数 / 通知开关
                           老师额外带 is_teacher / checked_in_today；并带 bot_username（深链用）
    GET  /api/me/points    积分流水（分页）
    GET  /api/me/reviews   我提交的评价（含状态）
    POST /api/me/notify    设置开课提醒通知开关（body: {enabled}）
    POST /api/me/checkin   老师自助签到（角色→active→时间窗口→幂等）

身份取自 session（中间件注入）。评价数只算 approved（与详情页口径一致）。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.config import config
from bot.database import (
    _today_str_local,
    checkin_teacher,
    count_user_reviews,
    get_config,
    get_teacher,
    get_teacher_channel_post,
    get_teacher_full_profile,
    get_user,
    get_user_total_points,
    is_checked_in,
    is_teacher_profile_complete,
    list_user_favorites,
    list_user_point_transactions,
    list_user_reviews_paged,
    set_user_notify_enabled,
)
from bot.web.keys import get_bot_username
from bot.web.roles import ROLE_TEACHER

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

    resp = {
        "user_id": uid,
        "role": session["role"],
        "username": username,
        "first_name": first_name,
        "points": points,
        "review_count": review_count,
        "favorite_count": fav_count,
        "notify_enabled": notify_enabled,
        "bot_username": await get_bot_username(request.app),
    }

    # 老师额外带签到态（前端给「今日签到」按钮）
    if session["role"] == ROLE_TEACHER:
        teacher = await get_teacher(uid)
        resp["is_teacher"] = bool(teacher and teacher.get("is_active"))
        resp["checked_in_today"] = await is_checked_in(uid, _today_str_local())
    else:
        resp["is_teacher"] = False
        resp["checked_in_today"] = False

    return web.json_response(resp)


async def post_checkin(request: web.Request) -> web.Response:
    """老师自助签到。校验链对齐 teacher_checkin handler：
    角色=teacher → is_active → 时间窗口(publish_time 截止) → 幂等(已签)。"""
    session = request["session"]
    uid = session["uid"]

    if session["role"] != ROLE_TEACHER:
        raise web.HTTPForbidden(reason="teacher only")
    teacher = await get_teacher(uid)
    if not teacher:
        raise web.HTTPForbidden(reason="not a registered teacher")
    if not teacher.get("is_active"):
        return web.json_response({"ok": False, "error": "账号已停用，请联系管理员"})

    # 时间窗口：现在 ≥ publish_time → 截止
    from datetime import datetime
    try:
        from pytz import timezone
        now = datetime.now(timezone(config.timezone))
    except Exception:
        now = datetime.now()
    publish_time = await get_config("publish_time") or config.publish_time
    try:
        hour, minute = map(int, str(publish_time).split(":"))
    except (ValueError, AttributeError):
        hour, minute = 14, 0
    if now.hour > hour or (now.hour == hour and now.minute >= minute):
        return web.json_response({
            "ok": False,
            "error": f"今日签到已截止（截止 {publish_time}），请明天再来",
        })

    today = _today_str_local()
    if await is_checked_in(uid, today):
        return web.json_response({"ok": True, "checked_in": True, "already": True})

    success = await checkin_teacher(uid, today)
    if not success:
        return web.json_response({"ok": False, "error": "签到失败，请稍后重试"})
    return web.json_response({"ok": True, "checked_in": True, "already": False})


async def get_teacher_home(request: web.Request) -> web.Response:
    """老师端首页（仅 teacher 角色）：签到态/截止/资料完整度/被评价。P4 §16.1。"""
    session = request["session"]
    uid = session["uid"]
    if session["role"] != ROLE_TEACHER:
        raise web.HTTPForbidden(reason="teacher only")
    teacher = await get_teacher_full_profile(uid)
    if not teacher:
        raise web.HTTPForbidden(reason="not a registered teacher")

    complete, missing = await is_teacher_profile_complete(uid)
    checked_in = await is_checked_in(uid, _today_str_local())
    publish_time = await get_config("publish_time") or config.publish_time
    post = await get_teacher_channel_post(uid)  # 未发档案帖 → None
    from datetime import datetime
    try:
        from pytz import timezone
        now = datetime.now(timezone(config.timezone))
    except Exception:
        now = datetime.now()

    return web.json_response({
        "display_name": teacher.get("display_name") or "",
        "is_active": bool(teacher.get("is_active")),
        "checked_in_today": checked_in,
        "deadline": publish_time,
        "server_time": now.strftime("%H:%M"),
        "profile_complete": complete,
        "missing_fields": missing,
        "review_count": int((post or {}).get("review_count") or 0),
        "avg_overall": round(float((post or {}).get("avg_overall") or 0), 1),
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
