"""管理台报销审核端点（P1·MiniApp，仅超管）。

    GET  /api/admin/reimbursements          待审(pending) + 名单(queued) 列表
    POST /api/admin/reimbursements/{id}/reject    驳回(body: {reason} 必填)
    POST /api/admin/reimbursements/{id}/activate  激活 queued → pending

⚠️ 无「同意/打款」端点 —— 同意是真实打款(超管输支付宝口令 → bot 发用户 → 才 approve)，
必须走 bot 私聊口令 FSM；MiniApp 用深链跳回 bot 完成。本文件只做拒绝/激活/列表。

复用 bot.services.reimbursement_moderation（与 bot Telegram 审核同一套逻辑）。bot 取自
app[APP_BOT]（通知用户用）。仅 superadmin。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.database import (
    get_teacher,
    get_user,
    list_pending_reimbursements,
    list_queued_reimbursements_paged,
)
from bot.services.reimbursement_moderation import (
    activate_reimbursement_core,
    reject_reimbursement_core,
)
from bot.web.keys import APP_BOT
from bot.web.roles import ROLE_SUPERADMIN

logger = logging.getLogger(__name__)


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
