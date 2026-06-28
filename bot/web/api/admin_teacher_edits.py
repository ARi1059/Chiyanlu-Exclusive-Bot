"""管理台老师资料审核端点（MiniApp·阶段 1，ROLE_ADMIN+）。

    GET  /api/admin/teacher-edits            待审老师资料修改列表
    POST /api/admin/teacher-edits/{id}/approve  通过（含 photo 切图，DB 层处理）+ 通知老师
    POST /api/admin/teacher-edits/{id}/reject   驳回（body: {reason?}）+ 通知老师

复用 bot.services.teacher_edit_moderation —— 与 bot 审核同一套「落库 + 通知老师」逻辑，
避免漂移。bot 取自 app[APP_BOT]。权限对齐 bot review:enter 的 @admin_required（所有管理员）。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.database import list_pending_edits
from bot.keyboards.teacher_self_kb import FIELD_LABELS
from bot.services.teacher_edit_moderation import (
    approve_teacher_edit,
    reject_teacher_edit,
)
from bot.web.keys import APP_BOT
from bot.web.roles import ROLE_ADMIN, ROLE_SUPERADMIN

logger = logging.getLogger(__name__)


def _require_admin(request: web.Request) -> int:
    """校验 admin / superadmin；返回 reviewer_id（当前管理员 uid）。否则 403。"""
    session = request["session"]
    if session["role"] not in (ROLE_ADMIN, ROLE_SUPERADMIN):
        raise web.HTTPForbidden(reason="admin only")
    return session["uid"]


def _edit_id(request: web.Request) -> int:
    try:
        return int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid edit id")


async def _json_body(request: web.Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _mask(field: str, value) -> str:
    """photo 字段的 old/new 脱敏（file_id 对人无意义）。"""
    if field == "photo_file_id":
        return "已上传" if value else "（空）"
    return (str(value) if value else "（空）")


async def get_teacher_edits(request: web.Request) -> web.Response:
    """待审老师资料修改列表。"""
    _require_admin(request)
    rows = await list_pending_edits(limit=50)
    items = []
    for r in rows:
        field = r.get("field_name") or ""
        created = str(r.get("created_at") or "")
        items.append({
            "id": r["id"],
            "teacher": r.get("teacher_display_name") or f"ID {r.get('teacher_id')}",
            "field": field,
            "field_label": FIELD_LABELS.get(field, field),
            "is_photo": field == "photo_file_id",
            "old": _mask(field, r.get("old_value")),
            "new": "新图（待审核）" if field == "photo_file_id" else _mask(field, r.get("new_value")),
            "time": created[5:16] if len(created) >= 16 else created,
        })
    return web.json_response({"edits": items})


async def post_approve_teacher_edit(request: web.Request) -> web.Response:
    reviewer_id = _require_admin(request)
    rid = _edit_id(request)
    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")
    result = await approve_teacher_edit(bot, rid, reviewer_id)
    # 业务失败（已审/不存在）→ 200 + ok:false，前端统一读 body
    return web.json_response(result)


async def post_reject_teacher_edit(request: web.Request) -> web.Response:
    reviewer_id = _require_admin(request)
    rid = _edit_id(request)
    body = await _json_body(request)
    reason = body.get("reason")
    if reason is not None:
        reason = str(reason).strip() or None
    bot = request.app.get(APP_BOT)
    if bot is None:
        raise web.HTTPServiceUnavailable(reason="bot unavailable")
    result = await reject_teacher_edit(bot, rid, reviewer_id, reason)
    return web.json_response(result)
