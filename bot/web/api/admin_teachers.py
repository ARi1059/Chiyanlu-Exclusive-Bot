"""管理台老师管理端点（阶段2）。

    GET  /api/admin/teachers?status=active|disabled|deleted|all   名册（ROLE_ADMIN+）
    POST /api/admin/teachers/{id}/status  {action: enable|disable|delete|restore}
         enable/disable → ROLE_ADMIN+；delete(软删)/restore → ROLE_SUPERADMIN（破坏性）
    POST /api/admin/teachers/{id}/field   {field, value}  管理员直改字段（ROLE_ADMIN+，无审核）

复用 DB 名册/生命周期函数 + teacher_self_edit.admin_set_field（直改即时生效）。
"""
from __future__ import annotations

import json
import logging

from aiohttp import web

from bot.database import (
    enable_teacher,
    get_all_teachers,
    get_deleted_teachers,
    get_teacher_counts,
    remove_teacher,
    restore_teacher,
    soft_delete_teacher,
)
from bot.services.teacher_self_edit import ADMIN_EDITABLE_FIELDS, admin_set_field
from bot.web.roles import ROLE_ADMIN, ROLE_SUPERADMIN

logger = logging.getLogger(__name__)


def _require_admin(request: web.Request) -> None:
    if request["session"]["role"] not in (ROLE_ADMIN, ROLE_SUPERADMIN):
        raise web.HTTPForbidden(reason="admin only")


def _require_super(request: web.Request) -> None:
    if request["session"]["role"] != ROLE_SUPERADMIN:
        raise web.HTTPForbidden(reason="superadmin only")


def _teacher_id(request: web.Request) -> int:
    try:
        return int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(reason="invalid teacher id")


def _parse_tags(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    try:
        v = json.loads(raw or "[]")
        return [str(x) for x in v if x] if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _item(t: dict) -> dict:
    return {
        "id": t["user_id"],
        "name": t.get("display_name") or "",
        "region": t.get("region") or "",
        "price": t.get("price") or "",
        "tags": _parse_tags(t.get("tags")),
        "button_text": t.get("button_text") or "",
        "button_url": t.get("button_url") or "",
        "is_active": bool(t.get("is_active")),
        "is_deleted": bool(t.get("is_deleted")),
        "has_photo": bool(t.get("photo_file_id")),
    }


async def get_admin_teachers(request: web.Request) -> web.Response:
    """老师名册（按状态过滤）+ 三态计数。"""
    _require_admin(request)
    status = request.query.get("status", "active")

    if status == "deleted":
        rows = await get_deleted_teachers()
    elif status == "disabled":
        rows = [t for t in await get_all_teachers(active_only=False, include_deleted=False)
                if not t.get("is_active")]
    elif status == "all":
        rows = await get_all_teachers(active_only=False, include_deleted=True)
    else:  # active
        rows = await get_all_teachers(active_only=True, include_deleted=False)

    counts = await get_teacher_counts()
    try:
        deleted_count = len(await get_deleted_teachers())
    except Exception:
        deleted_count = 0

    return web.json_response({
        "teachers": [_item(t) for t in rows],
        "counts": {
            "active": counts.get("active", 0),
            "disabled": counts.get("inactive", 0),
            "deleted": deleted_count,
        },
    })


_STATUS_ACTIONS = {"enable", "disable", "delete", "restore"}


async def post_admin_teacher_status(request: web.Request) -> web.Response:
    """启停 / 软删 / 恢复。enable/disable=admin；delete/restore=超管。"""
    _require_admin(request)
    tid = _teacher_id(request)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(reason="invalid json body")
    action = (body or {}).get("action")
    if action not in _STATUS_ACTIONS:
        raise web.HTTPBadRequest(reason="invalid action")

    if action in ("delete", "restore"):
        _require_super(request)  # 破坏性操作仅超管

    if action == "enable":
        ok = await enable_teacher(tid)
    elif action == "disable":
        ok = await remove_teacher(tid)
    elif action == "delete":
        ok = await soft_delete_teacher(tid)
    else:  # restore
        ok = await restore_teacher(tid)

    return web.json_response({"ok": bool(ok), "action": action})


async def post_admin_teacher_field(request: web.Request) -> web.Response:
    """管理员直改老师文字字段（即时生效，无审核）。"""
    _require_admin(request)
    tid = _teacher_id(request)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(reason="invalid json body")
    field = (body or {}).get("field")
    value = (body or {}).get("value")
    if field not in ADMIN_EDITABLE_FIELDS:
        raise web.HTTPBadRequest(reason="invalid field")
    if field == "tags" and isinstance(value, list):
        value = " ".join(str(x) for x in value)

    result = await admin_set_field(tid, field, value)
    return web.json_response(result)
