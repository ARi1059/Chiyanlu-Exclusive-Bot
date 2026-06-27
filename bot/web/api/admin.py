"""管理台统计端点（P1·MiniApp）。

    GET /api/admin/stats   运营总览（仅 admin / superadmin）

复用 services/admin_overview（今日数据 + 待处理，单连接独立容错）、get_teacher_counts
（活跃老师）、services/reimbursement_pool（报销池，仅 superadmin 给）。近 7 日趋势自写
GROUP BY。待审评价队列附老师名。
"""
from __future__ import annotations

import logging
from datetime import timedelta

from aiohttp import web

from bot.config import config
from bot.database import (
    get_db,
    get_teacher,
    get_teacher_counts,
    list_pending_reviews,
)
from bot.services.admin_overview import get_admin_overview_stats
from bot.services.reimbursement_pool import get_reimbursement_pool_stats
from bot.web.keys import APP_BOT
from bot.web.roles import ROLE_ADMIN, ROLE_SUPERADMIN

logger = logging.getLogger(__name__)

# bot 用户名缓存一次（不变）。供报销「同意」深链构造 t.me 链接。
_bot_username: str | None = None


async def _get_bot_username(request: web.Request) -> str:
    global _bot_username
    if _bot_username is None:
        try:
            bot = request.app.get(APP_BOT)
            me = await bot.get_me()
            _bot_username = me.username or ""
        except Exception:
            logger.warning("get_me 取 bot username 失败", exc_info=True)
            return ""
    return _bot_username

try:
    from pytz import timezone as _tz
except Exception:  # pragma: no cover
    _tz = None


def _today_local():
    from datetime import datetime
    if _tz is not None:
        return datetime.now(_tz(config.timezone))
    return datetime.now()


async def _trend_7d() -> list[dict]:
    """近 7 日评价/签到按天计数。checkins.checkin_date 本地日；
    teacher_reviews.created_at 是 UTC，按本地日聚合需加时区偏移。"""
    now = _today_local()
    days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    start = days[0]
    # 本地时区偏移（如 +08:00 → '+8 hours'），用于把 UTC created_at 折算到本地日
    offset_hours = int(now.utcoffset().total_seconds() // 3600) if now.utcoffset() else 0
    shift = f"{offset_hours:+d} hours"

    checkin_map: dict[str, int] = {}
    review_map: dict[str, int] = {}
    db = await get_db()
    try:
        try:
            cur = await db.execute(
                "SELECT checkin_date AS d, COUNT(*) AS n FROM checkins "
                "WHERE checkin_date >= ? GROUP BY checkin_date",
                (start,),
            )
            for r in await cur.fetchall():
                checkin_map[r["d"]] = int(r["n"])
        except Exception:
            logger.warning("trend checkins 查询失败", exc_info=True)
        try:
            cur = await db.execute(
                "SELECT date(created_at, ?) AS d, COUNT(*) AS n FROM teacher_reviews "
                "WHERE date(created_at, ?) >= ? GROUP BY d",
                (shift, shift, start),
            )
            for r in await cur.fetchall():
                review_map[r["d"]] = int(r["n"])
        except Exception:
            logger.warning("trend reviews 查询失败", exc_info=True)
    finally:
        await db.close()

    return [{
        "day": f"{d[5:7]}/{d[8:10]}",  # MM-DD → M/D 风格
        "reviews": review_map.get(d, 0),
        "signins": checkin_map.get(d, 0),
    } for d in days]


_RATING_OK = {"positive", "neutral", "negative"}


async def _pending_queue(limit: int = 10) -> list[dict]:
    """待审评价队列（附老师名、脱敏用户、时间）。"""
    rows = await list_pending_reviews(limit=limit)
    items = []
    for r in rows:
        t = await get_teacher(r["teacher_id"])
        uid = str(r.get("user_id") or "")
        sig = ("****" + uid[-4:]) if len(uid) >= 4 else "****"
        created = str(r.get("created_at") or "")
        time_str = created[11:16] if len(created) >= 16 else created
        rating = r.get("rating") if r.get("rating") in _RATING_OK else "neutral"
        items.append({
            "id": r["id"],
            "teacher": (t or {}).get("display_name") or "未知",
            "user": sig,
            "rating": rating,
            "time": time_str,
        })
    return items


async def get_admin_stats(request: web.Request) -> web.Response:
    """运营总览。仅 admin / superadmin。"""
    role = request["session"]["role"]
    if role not in (ROLE_ADMIN, ROLE_SUPERADMIN):
        raise web.HTTPForbidden(reason="admin only")

    overview = await get_admin_overview_stats()
    counts = await get_teacher_counts()
    trend = await _trend_7d()
    queue = await _pending_queue()

    from bot.database import POINT_PACKAGE_OPTIONS
    resp = {
        "today_checkins": overview.today_checkin_teachers or 0,
        "today_new_users": overview.today_new_users or 0,
        "today_new_reviews": overview.today_new_reviews or 0,
        "pending_reviews": overview.pending_reviews or 0,
        "pending_reimbursements": overview.pending_reimbursements or 0,
        "active_teachers": counts.get("active", 0),
        "trend": trend,
        "pending_queue": queue,
        # 审核加分套餐（前端 ✓ 选套餐用，与 bot 同源）
        "point_packages": [
            {"key": o["key"], "label": o["label"], "delta": o["delta"]}
            for o in POINT_PACKAGE_OPTIONS
        ],
        # bot 用户名（前端报销「同意」深链 https://t.me/<bot>?start=reimb_<id> 用）
        "bot_username": await _get_bot_username(request),
    }

    # 报销池仅超管可见
    if role == ROLE_SUPERADMIN:
        try:
            pool = await get_reimbursement_pool_stats()
            resp["reimburse_pool"] = {
                "enabled": bool(pool.feature_enabled),
                "monthly_pool": pool.monthly_pool,
                "used": pool.approved_amount_this_month,
                "remaining": pool.remaining_pool,
            }
        except Exception:
            logger.warning("报销池统计失败", exc_info=True)
            resp["reimburse_pool"] = None

    return web.json_response(resp)
