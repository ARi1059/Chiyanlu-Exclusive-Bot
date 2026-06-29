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
    add_teacher_photo,
    count_user_reviews,
    get_config,
    get_teacher,
    get_teacher_channel_post,
    get_teacher_full_profile,
    get_teacher_photos,
    get_user,
    get_user_total_points,
    is_checked_in,
    is_teacher_profile_complete,
    list_user_favorites,
    list_user_point_transactions,
    list_user_reviews_paged,
    remove_teacher_photo,
    set_user_notify_enabled,
)
from bot.web.keys import APP_BOT, get_bot_username
from bot.web.roles import ROLE_TEACHER
from bot.web.api.photo import signed_photo_url
from bot.services.teacher_checkin import perform_checkin
from bot.services.teacher_self_edit import (
    EDITABLE_FIELDS,
    FIELD_LABELS,
    submit_field_edit,
)

TEACHER_ALBUM_MAX = 10

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
    """老师自助签到（业务逻辑委托 services.teacher_checkin，与 bot 同源）。
    role 校验留在端点（web 鉴权关注点）；其余校验链在 service。"""
    session = request["session"]
    uid = session["uid"]

    if session["role"] != ROLE_TEACHER:
        raise web.HTTPForbidden(reason="teacher only")

    result = await perform_checkin(uid)
    status = result.status

    if status == "not_teacher":
        raise web.HTTPForbidden(reason="not a registered teacher")
    if status == "inactive":
        return web.json_response({"ok": False, "error": "账号已停用，请联系管理员"})
    if status == "closed":
        return web.json_response({
            "ok": False,
            "error": f"今日签到已截止（截止 {result.deadline}），请明天再来",
        })
    if status == "already":
        return web.json_response({"ok": True, "checked_in": True, "already": True})
    if status == "success":
        return web.json_response({"ok": True, "checked_in": True, "already": False})
    return web.json_response({"ok": False, "error": "签到失败，请稍后重试"})  # failed


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


async def get_teacher_edit_profile(request: web.Request) -> web.Response:
    """老师自助编辑资料 —— 当前可编辑字段值（仅 teacher 角色）。§16.3。

    返回 6 个白名单字段当前值（tags 以 list 给前端）+ 锁定的 button_url（只读展示）。
    """
    session = request["session"]
    uid = session["uid"]
    if session["role"] != ROLE_TEACHER:
        raise web.HTTPForbidden(reason="teacher only")
    teacher = await get_teacher_full_profile(uid)  # tags 已解析为 list
    if not teacher:
        raise web.HTTPForbidden(reason="not a registered teacher")

    return web.json_response({
        "fields": {
            "display_name": teacher.get("display_name") or "",
            "region": teacher.get("region") or "",
            "price": teacher.get("price") or "",
            "tags": teacher.get("tags") or [],
            "button_text": teacher.get("button_text") or "",
            "has_photo": bool(teacher.get("photo_file_id")),
        },
        "button_url": teacher.get("button_url") or "",  # 锁定，仅展示
        "labels": FIELD_LABELS,
        "editable_fields": sorted(EDITABLE_FIELDS),
    })


async def post_teacher_edit_profile(request: web.Request) -> web.Response:
    """老师自助提交单字段修改（仅 teacher 角色）。§16.3。

    body: {field, value}。复用 bot/web 同源 service：文字立即生效（可回滚）、
    图片延后（审核后生效），并通知管理员。图片字段的 value 是先经
    POST /api/uploads 换得的 file_id。tags 可传 list 或分隔串。
    """
    session = request["session"]
    uid = session["uid"]
    if session["role"] != ROLE_TEACHER:
        raise web.HTTPForbidden(reason="teacher only")

    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(reason="invalid json body")

    field = (body or {}).get("field")
    value = (body or {}).get("value")
    if field not in EDITABLE_FIELDS:
        raise web.HTTPBadRequest(reason="invalid field")
    # tags 允许前端传数组：拼成分隔串交给 service.parse_tags 统一处理。
    if field == "tags" and isinstance(value, list):
        value = " ".join(str(x) for x in value)

    bot = request.app[APP_BOT]
    result = await submit_field_edit(bot, uid, field, value)
    # 业务校验失败（空/过长/同值/空标签等）返回 200 + ok:false，前端内联提示。
    return web.json_response(result)


# ── 老师自助多图相册（即时生效，不走审核）──────────────────────────────────────

def _album_payload(request: web.Request, uid: int, file_ids: list[str]) -> dict:
    """组装相册响应：每张带签名 URL + cache-bust（按 file_id 片段）。

    照片端点回 max-age=86400 且 URL 含 ?sig=&i=N；删/换图后同一 i 指向新 file_id，
    必须用按内容变化的 &v= 破除浏览器缓存（端点忽略未知 query）。
    """
    photos = []
    for i, fid in enumerate(file_ids):
        url = signed_photo_url(request, uid, True, i)
        if url:
            url = f"{url}{'&' if '?' in url else '?'}v={str(fid)[:8]}"
        photos.append({"index": i, "url": url})
    return {"photos": photos, "count": len(file_ids), "max": TEACHER_ALBUM_MAX}


async def get_teacher_album(request: web.Request) -> web.Response:
    """老师自助相册：当前照片列表（仅 teacher）。"""
    session = request["session"]
    uid = session["uid"]
    if session["role"] != ROLE_TEACHER:
        raise web.HTTPForbidden(reason="teacher only")
    file_ids = await get_teacher_photos(uid)
    return web.json_response(_album_payload(request, uid, file_ids))


async def post_teacher_album(request: web.Request) -> web.Response:
    """追加一张到相册（即时生效）。body: {file_id}（先经 /api/uploads 换得）。"""
    session = request["session"]
    uid = session["uid"]
    if session["role"] != ROLE_TEACHER:
        raise web.HTTPForbidden(reason="teacher only")
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(reason="invalid json body")
    file_id = str((body or {}).get("file_id") or "").strip()
    if not file_id:
        raise web.HTTPBadRequest(reason="missing file_id")

    before = await get_teacher_photos(uid)
    if len(before) >= TEACHER_ALBUM_MAX:
        return web.json_response({
            "ok": False, "error": "full", "count": len(before),
            "message": f"相册已满（最多 {TEACHER_ALBUM_MAX} 张），请先删除再添加。",
        })
    count = await add_teacher_photo(uid, file_id)
    return web.json_response({"ok": True, "count": count})


async def delete_teacher_album(request: web.Request) -> web.Response:
    """删除相册第 index 张（0-based，即时生效）。"""
    session = request["session"]
    uid = session["uid"]
    if session["role"] != ROLE_TEACHER:
        raise web.HTTPForbidden(reason="teacher only")
    try:
        index = int(request.match_info["index"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid index")
    # DB remove_teacher_photo 是 1-based；越界返回 False。
    ok = await remove_teacher_photo(uid, index + 1)
    if not ok:
        return web.json_response({"ok": False, "error": "bad_index"})
    count = len(await get_teacher_photos(uid))
    return web.json_response({"ok": True, "count": count})


