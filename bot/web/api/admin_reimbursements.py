"""管理台报销审核端点（P1/§15.4·MiniApp，仅超管）。

    GET  /api/admin/reimbursements          待审(pending) + 名单(queued) 列表
    GET  /api/admin/reimbursements/{id}     详情 + 配额徽标四态（§15.5）
    POST /api/admin/reimbursements/{id}/reject      驳回(body: {reason} 必填)
    POST /api/admin/reimbursements/{id}/activate    激活 queued → pending
    POST /api/admin/reimbursements/{id}/payout      打款(body: {token} 支付宝口令)（§15.5）
    POST /api/admin/reimbursements/{id}/reset-week  发放本周 reset voucher（§15.5）

「打款」是真实动钱：复用 reimbursement_moderation.payout_reimbursement_core——口令经 bot DM
发用户、发送成功才 approve、口令不存库、audit 只记 mask。**本文件绝不 log token / 不回显 token。**

复用 bot.services.reimbursement_moderation（与 bot Telegram 审核同一套逻辑）。bot 取自
app[APP_BOT]（通知/发口令用）。仅 superadmin。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.database import (
    get_reimbursement,
    get_teacher,
    get_user,
    list_pending_reimbursements,
    list_queued_reimbursements_paged,
)
from bot.services.reimbursement_moderation import (
    activate_reimbursement_core,
    compute_payout_precheck,
    grant_reset_core,
    payout_reimbursement_core,
    reject_reimbursement_core,
)
from bot.web.keys import APP_BOT
from bot.web.roles import ROLE_SUPERADMIN

logger = logging.getLogger(__name__)

# 配额徽标四态 → 文案（与 bot _render_reimbursement_detail 124–147 同义）
_BADGE_LABEL = {
    "ok": "✅ 可批：周配额 + 月池均满足",
    "need_voucher": "⚠️ 需消耗 voucher：本周已满，通过将消耗预留 voucher",
    "week_blocked": "🛑 周配额已满：通过前需先「重置本周」",
    "over_pool": "🛑 超月池：本月池余额不足",
}


def _require_super(request: web.Request) -> int:
    session = request["session"]
    if session["role"] != ROLE_SUPERADMIN:
        raise web.HTTPForbidden(reason="superadmin only")
    return session["uid"]


def _reimb_id(request: web.Request) -> int:
    try:
        return int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid reimbursement id")


async def _user_label(user_id) -> str:
    """脱敏用户标识：优先 @username / first_name，否则尾号。"""
    try:
        u = await get_user(int(user_id))
    except Exception:
        u = None
    if u and u.get("username"):
        return f"@{u['username']}"
    if u and u.get("first_name"):
        return u["first_name"]
    s = str(user_id)
    return ("****" + s[-4:]) if len(s) >= 4 else "****"


async def _serialize(r: dict) -> dict:
    teacher = await get_teacher(r["teacher_id"])
    created = str(r.get("created_at") or "")
    return {
        "id": r["id"],
        "amount": int(r.get("amount") or 0),
        "status": r.get("status") or "",
        "teacher": (teacher or {}).get("display_name") or "未知",
        "user": await _user_label(r.get("user_id")),
        "time": created[5:16] if len(created) >= 16 else created,
    }


async def get_reimbursements(request: web.Request) -> web.Response:
    """pending + queued 列表（pending 在前）。"""
    _require_super(request)
    pending = await list_pending_reimbursements(limit=50)
    queued = await list_queued_reimbursements_paged(limit=50)
    items = [await _serialize(r) for r in pending] + [await _serialize(r) for r in queued]
    return web.json_response({"reimbursements": items})


async def post_reject_reimbursement(request: web.Request) -> web.Response:
    admin_id = _require_super(request)
    reimb_id = _reimb_id(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = str((body or {}).get("reason") or "").strip()
    if not reason:
        raise web.HTTPBadRequest(reason="reason required")

    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")

    res = await reject_reimbursement_core(
        bot, reimb_id=reimb_id, admin_id=admin_id, reason=reason,
    )
    if not res.ok:
        return web.json_response({"ok": False, "error": res.error})
    return web.json_response({"ok": True, "reimb_id": res.reimb_id})


async def post_activate_reimbursement(request: web.Request) -> web.Response:
    admin_id = _require_super(request)
    reimb_id = _reimb_id(request)

    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")

    res = await activate_reimbursement_core(bot, reimb_id=reimb_id, admin_id=admin_id)
    if not res.ok:
        return web.json_response({"ok": False, "error": res.error})
    return web.json_response({"ok": True, "reimb_id": res.reimb_id})


# ============ 详情 + 打款（§15.5）============


async def get_reimbursement_detail(request: web.Request) -> web.Response:
    """GET /api/admin/reimbursements/{id} —— 详情 + 配额徽标四态（仅超管）。"""
    _require_super(request)
    reimb_id = _reimb_id(request)
    reimb = await get_reimbursement(reimb_id)
    if not reimb:
        raise web.HTTPNotFound(reason="reimbursement not found")

    teacher = await get_teacher(reimb["teacher_id"]) if reimb.get("teacher_id") else None
    pre = await compute_payout_precheck(reimb)
    created = str(reimb.get("created_at") or "")
    detail = {
        "id": reimb["id"],
        "amount": int(reimb.get("amount") or 0),
        "status": reimb.get("status") or "",
        "teacher": (teacher or {}).get("display_name") or "未知",
        "teacher_price": (teacher or {}).get("price"),
        "user": await _user_label(reimb.get("user_id")),
        "review_id": reimb.get("review_id"),
        "week_key": reimb.get("week_key") or "",
        "month_key": reimb.get("month_key") or "",
        "time": created[5:16] if len(created) >= 16 else created,
        "badge": {
            "state": pre.state,
            "label": _BADGE_LABEL.get(pre.state, pre.state),
            "week_used": pre.week_used,
            "weekly_limit": pre.weekly_limit,
            "month_used": pre.month_used,
            "pool": pre.pool,
            "pool_remaining": pre.pool_remaining,
            "has_reset": pre.has_reset,
        },
    }
    return web.json_response({"ok": True, "detail": detail})


async def post_payout_reimbursement(request: web.Request) -> web.Response:
    """POST /api/admin/reimbursements/{id}/payout —— 打款（body: {token}）。

    口令是真钱：core 先发后批 + 服务端复核配额 + 仅记 mask。本端点不 log token、不回显 token。
    """
    admin_id = _require_super(request)
    reimb_id = _reimb_id(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    token = str((body or {}).get("token") or "")

    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")

    res = await payout_reimbursement_core(
        bot, reimb_id=reimb_id, admin_id=admin_id, token=token,
    )
    if not res.ok:
        return web.json_response({"ok": False, "error": res.error})
    return web.json_response({
        "ok": True, "reimb_id": res.reimb_id, "amount": res.amount,
    })


async def post_reset_week_reimbursement(request: web.Request) -> web.Response:
    """POST /api/admin/reimbursements/{id}/reset-week —— 发放本周 reset voucher。"""
    admin_id = _require_super(request)
    reimb_id = _reimb_id(request)
    reimb = await get_reimbursement(reimb_id)
    if not reimb:
        raise web.HTTPNotFound(reason="reimbursement not found")

    res = await grant_reset_core(
        reimb_id=reimb_id, user_id=int(reimb["user_id"]), admin_id=admin_id,
    )
    if not res.ok:
        return web.json_response({"ok": False, "error": res.error})
    return web.json_response({"ok": True, "voucher_id": res.voucher_id})
