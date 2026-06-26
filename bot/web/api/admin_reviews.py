"""管理台评价审核端点（P1·MiniApp，仅超管）。

    POST /api/admin/reviews/{id}/approve   通过 + 加分套餐（body: {package_key} 或 {delta}）
    POST /api/admin/reviews/{id}/reject    驳回（body: {reason?}）

复用 bot.services.review_moderation —— 与 bot Telegram 审核同一套业务逻辑（含频道发布/
讨论群/私聊通知/报销联动），避免逻辑漂移。bot 对象取自 app[APP_BOT]（同进程共享）。
仅 superadmin 可操作（对齐 bot 的 _super_admin_required）。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.database import POINT_CUSTOM_MAX, POINT_CUSTOM_MIN, POINT_PACKAGE_OPTIONS
from bot.services.review_moderation import approve_review, reject_review
from bot.web.keys import APP_BOT
from bot.web.roles import ROLE_SUPERADMIN

logger = logging.getLogger(__name__)


def _require_super(request: web.Request) -> int:
    """校验 superadmin；返回 reviewer_id（当前超管 uid）。否则 403。"""
    session = request["session"]
    if session["role"] != ROLE_SUPERADMIN:
        raise web.HTTPForbidden(reason="superadmin only")
    return session["uid"]


def _review_id(request: web.Request) -> int:
    try:
        return int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid review id")


async def _json_body(request: web.Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _resolve_delta(body: dict) -> tuple[int, str]:
    """解析加分量：优先 package_key（预设套餐），否则 delta（自定义 0..100）。
    delta 由后端权威解析，不信前端传的 label。"""
    key = body.get("package_key")
    if key:
        pkg = next((o for o in POINT_PACKAGE_OPTIONS if o["key"] == key), None)
        if not pkg:
            raise web.HTTPBadRequest(reason="unknown package_key")
        return int(pkg["delta"]), str(pkg["label"])
    raw = body.get("delta")
    if raw is None:
        raise web.HTTPBadRequest(reason="missing package_key or delta")
    try:
        delta = int(raw)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(reason="invalid delta")
    if not (POINT_CUSTOM_MIN <= delta <= POINT_CUSTOM_MAX):
        raise web.HTTPBadRequest(
            reason=f"delta out of range [{POINT_CUSTOM_MIN},{POINT_CUSTOM_MAX}]"
        )
    return delta, f"自定义 +{delta}"


async def post_approve_review(request: web.Request) -> web.Response:
    reviewer_id = _require_super(request)
    review_id = _review_id(request)
    delta, package_label = _resolve_delta(await _json_body(request))

    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")

    result = await approve_review(
        bot, review_id=review_id, reviewer_id=reviewer_id,
        delta=delta, package_label=package_label,
    )
    if not result.ok:
        # 业务失败（不存在/已审）→ 200 + ok:false，前端统一读 body
        return web.json_response({"ok": False, "error": result.error})
    return web.json_response({
        "ok": True,
        "review_id": result.review_id,
        "delta": result.delta,
        "new_total": result.new_total,
        "reimb_amount": result.reimb_amount,
        "reimb_status": result.reimb_status,
    })


async def post_reject_review(request: web.Request) -> web.Response:
    reviewer_id = _require_super(request)
    review_id = _review_id(request)
    body = await _json_body(request)
    reason = body.get("reason")
    if reason is not None:
        reason = str(reason).strip() or None

    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")

    result = await reject_review(
        bot, review_id=review_id, reviewer_id=reviewer_id, reason=reason,
    )
    if not result.ok:
        return web.json_response({"ok": False, "error": result.error})
    return web.json_response({"ok": True, "review_id": result.review_id})
