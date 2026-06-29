"""bot/web 审计日志台端点测试（§15.7）。

覆盖 GET /api/admin/audit-logs：
  - 鉴权：仅 superadmin（user / admin → 403，查询不被调用）
  - 分页 + action 过滤透传；limit clamp；offset 负数归 0
  - 返回 logs/total/actions 结构 + 行序列化（admin 标签 / 脱敏）

DB 查询全 monkeypatch；token 用 issue_session 直接签。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.admin_audit as mod
from bot.config import config
from bot.web.auth import issue_session
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _super() -> str:
    return issue_session(config.super_admin_id, "superadmin", config.bot_token)


def _admin(uid: int = 1234) -> str:
    return issue_session(uid, "admin", config.bot_token)


def _user(uid: int = 99999999) -> str:
    return issue_session(uid, "user", config.bot_token)


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _patch(monkeypatch, *, rows=None, total=3, actions=None):
    rec = {"paged": None, "count": None}

    async def fake_paged(*, offset, limit, action):
        rec["paged"] = {"offset": offset, "limit": limit, "action": action}
        return rows if rows is not None else [{
            "id": 10, "admin_id": 777, "admin_username": "boss",
            "action": "reimburse_payout_sent", "target_type": "reimbursement",
            "target_id": "5", "detail": '{"amount": 200}',
            "created_at": "2026-06-30 12:34:56",
        }]

    async def fake_count(*, action):
        rec["count"] = {"action": action}
        return total

    async def fake_actions():
        return actions if actions is not None else ["reimburse_payout_sent", "rreview_approve"]

    monkeypatch.setattr(mod, "list_admin_audits_paged", fake_paged)
    monkeypatch.setattr(mod, "count_admin_audits", fake_count)
    monkeypatch.setattr(mod, "list_admin_audit_actions", fake_actions)
    return rec


# ============ 鉴权 ============

def test_requires_superadmin_user(monkeypatch):
    rec = _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/audit-logs", headers=_hdr(_user()))
            assert r.status == 403

    _run(_t())
    assert rec["paged"] is None  # 查询不被调用


def test_admin_also_forbidden(monkeypatch):
    _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/audit-logs", headers=_hdr(_admin()))
            assert r.status == 403  # 审计日志仅超管

    _run(_t())


def test_no_token_401(monkeypatch):
    _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/audit-logs")
            assert r.status == 401

    _run(_t())


# ============ 分页 / 过滤 / 序列化 ============

def test_default_paging_and_serialize(monkeypatch):
    rec = _patch(monkeypatch, total=42)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/admin/audit-logs", headers=_hdr(_super()))
            assert r.status == 200
            d = await r.json()
            assert d["total"] == 42 and d["offset"] == 0 and d["limit"] == 20
            assert d["actions"] == ["reimburse_payout_sent", "rreview_approve"]
            row = d["logs"][0]
            assert row["admin"] == "@boss"
            assert row["action"] == "reimburse_payout_sent"
            assert row["target_type"] == "reimbursement" and row["target_id"] == "5"
            assert row["time"] == "06-30 12:34"

    _run(_t())
    assert rec["paged"] == {"offset": 0, "limit": 20, "action": None}
    assert rec["count"] == {"action": None}


def test_action_filter_passthrough(monkeypatch):
    rec = _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/admin/audit-logs?action=rreview_approve&offset=20&limit=10",
                            headers=_hdr(_super()))
            assert r.status == 200

    _run(_t())
    assert rec["paged"] == {"offset": 20, "limit": 10, "action": "rreview_approve"}
    assert rec["count"] == {"action": "rreview_approve"}


def test_limit_clamped(monkeypatch):
    rec = _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            # >50 → 回默认 20
            await c.get("/api/admin/audit-logs?limit=999", headers=_hdr(_super()))
            assert rec["paged"]["limit"] == 20
            # <1 → 回默认 20
            await c.get("/api/admin/audit-logs?limit=0", headers=_hdr(_super()))
            assert rec["paged"]["limit"] == 20

    _run(_t())


def test_negative_offset_zeroed(monkeypatch):
    rec = _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            await c.get("/api/admin/audit-logs?offset=-5", headers=_hdr(_super()))
            assert rec["paged"]["offset"] == 0

    _run(_t())


def test_admin_label_fallback_masks_id(monkeypatch):
    _patch(monkeypatch, rows=[{
        "id": 1, "admin_id": 88887777, "admin_username": "",
        "action": "rreview_approve", "target_type": "teacher_review",
        "target_id": "9", "detail": "", "created_at": "2026-06-30 09:00:00",
    }])

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/admin/audit-logs", headers=_hdr(_super()))
            row = (await r.json())["logs"][0]
            assert row["admin"] == "****7777"  # 无 username → 尾号脱敏

    _run(_t())
