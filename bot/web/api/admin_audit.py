"""管理台审计日志端点（§15.7·MiniApp，仅超管）。

    GET /api/admin/audit-logs?action=&offset=&limit=

审计日志含全部敏感动作（打款 reimburse_payout_sent / 强制接管 rreview_force_claim /
加分 rreview_approve 等），故仅 superadmin 可见（与 reimburse_pool 一致）。

复用 database.list_admin_audits_paged / count_admin_audits / list_admin_audit_actions——
零新查询逻辑，端点只做编排 + 序列化。
"""
from __future__ import annotations

import logging

from aiohttp import web

from bot.database import (
    count_admin_audits,
    list_admin_audit_actions,
    list_admin_audits_paged,
)
from bot.web.roles import ROLE_SUPERADMIN

logger = logging.getLogger(__name__)

_LIMIT_DEFAULT = 20
_LIMIT_MAX = 50


def _require_super(request: web.Request) -> int:
    session = request["session"]
    if session["role"] != ROLE_SUPERADMIN:
        raise web.HTTPForbidden(reason="superadmin only")
    return session["uid"]


def _int_param(request: web.Request, key: str, default: int) -> int:
    try:
        return int(request.query.get(key, default))
    except (TypeError, ValueError):
        return default


def _admin_label(row: dict) -> str:
    """管理员展示：优先 @username，否则 admin_id 尾号脱敏。"""
    uname = (row.get("admin_username") or "").strip()
    if uname:
        return f"@{uname}"
    s = str(row.get("admin_id") or "")
    return ("****" + s[-4:]) if len(s) >= 4 else (s or "—")


def _serialize(row: dict) -> dict:
    created = str(row.get("created_at") or "")
    return {
        "id": row.get("id"),
        "time": created[5:16] if len(created) >= 16 else created,
        "admin": _admin_label(row),
        "action": row.get("action") or "",
        "target_type": row.get("target_type") or "",
        "target_id": row.get("target_id") or "",
        "detail": row.get("detail") or "",
    }


async def get_audit_logs(request: web.Request) -> web.Response:
    """审计日志分页 + action 过滤（仅超管）。"""
    _require_super(request)

    offset = max(0, _int_param(request, "offset", 0))
    limit = _int_param(request, "limit", _LIMIT_DEFAULT)
    if limit < 1 or limit > _LIMIT_MAX:
        limit = _LIMIT_DEFAULT
    action = (request.query.get("action") or "").strip() or None

    rows = await list_admin_audits_paged(offset=offset, limit=limit, action=action)
    total = await count_admin_audits(action=action)

    return web.json_response({
        "logs": [_serialize(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "actions": await list_admin_audit_actions(),
    })
