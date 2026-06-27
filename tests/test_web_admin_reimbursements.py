"""bot/web 报销审核端点测试（P1·Tier2）。

覆盖 POST /api/admin/reimbursements/{id}/reject|activate + GET 列表：
  - 鉴权：仅 superadmin（user → 403，service 不被调用）
  - reject：reason 必填（空 → 400，service 不调用）；成功委托 reject_reimbursement_core
  - activate：成功委托 activate_reimbursement_core
  - 业务失败（不存在/状态变更）→ 200 + {ok:false}

⚠️ 无「同意/打款」端点（同意=真实打款，走 bot 口令 FSM，web 只深链）。
service 全部 monkeypatch；token 用 issue_session 直接签。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.admin_reimbursements as mod
from bot.config import config
from bot.services.reimbursement_moderation import ActivateResult, RejectResult
from bot.web.auth import issue_session
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _super() -> str:
    return issue_session(config.super_admin_id, "superadmin", config.bot_token)


def _user(uid: int = 99999999) -> str:
    return issue_session(uid, "user", config.bot_token)


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ============ reject：鉴权 ============

def test_reject_requires_superadmin(monkeypatch):
    called = {"n": 0}

    async def fake_reject(*a, **k):
        called["n"] += 1
        return RejectResult(ok=True)

    monkeypatch.setattr(mod, "reject_reimbursement_core", fake_reject)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/reimbursements/5/reject",
                             headers=_hdr(_user()), json={"reason": "金额不符"})
            assert r.status == 403

    _run(_t())
    assert called["n"] == 0  # 鉴权拦在 service 之前


def test_reject_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/reimbursements/5/reject", json={"reason": "x"})
            assert r.status == 401

    _run(_t())


def test_reject_empty_reason_400(monkeypatch):
    async def fake_reject(*a, **k):
        raise AssertionError("空原因不应到达 service")

    monkeypatch.setattr(mod, "reject_reimbursement_core", fake_reject)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reimbursements/5/reject",
                             headers=_hdr(_super()), json={})
            assert r.status == 400

    _run(_t())


def test_reject_delegates_with_reason(monkeypatch):
    rec: dict = {}

    async def fake_reject(bot, *, reimb_id, admin_id, reason):
        rec.update(reimb_id=reimb_id, reason=reason)
        return RejectResult(ok=True, reimb_id=reimb_id)

    monkeypatch.setattr(mod, "reject_reimbursement_core", fake_reject)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reimbursements/7/reject",
                             headers=_hdr(_super()), json={"reason": "证据不清晰"})
            assert r.status == 200
            assert (await r.json())["ok"] is True

    _run(_t())
    assert rec["reimb_id"] == 7
    assert rec["reason"] == "证据不清晰"


def test_reject_business_failure_ok_false(monkeypatch):
    async def fake_reject(*a, **k):
        return RejectResult(ok=False, error="报销状态已变更")

    monkeypatch.setattr(mod, "reject_reimbursement_core", fake_reject)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reimbursements/5/reject",
                             headers=_hdr(_super()), json={"reason": "x"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False and d["error"] == "报销状态已变更"

    _run(_t())


# ============ activate ============

def test_activate_requires_superadmin(monkeypatch):
    called = {"n": 0}

    async def fake_activate(*a, **k):
        called["n"] += 1
        return ActivateResult(ok=True)

    monkeypatch.setattr(mod, "activate_reimbursement_core", fake_activate)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/reimbursements/5/activate", headers=_hdr(_user()))
            assert r.status == 403

    _run(_t())
    assert called["n"] == 0


def test_activate_delegates(monkeypatch):
    rec: dict = {}

    async def fake_activate(bot, *, reimb_id, admin_id):
        rec.update(reimb_id=reimb_id, admin_id=admin_id)
        return ActivateResult(ok=True, reimb_id=reimb_id)

    monkeypatch.setattr(mod, "activate_reimbursement_core", fake_activate)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reimbursements/9/activate", headers=_hdr(_super()))
            assert r.status == 200
            assert (await r.json())["ok"] is True

    _run(_t())
    assert rec["reimb_id"] == 9


def test_activate_business_failure_ok_false(monkeypatch):
    async def fake_activate(*a, **k):
        return ActivateResult(ok=False, error="当前状态 pending，无法激活")

    monkeypatch.setattr(mod, "activate_reimbursement_core", fake_activate)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reimbursements/5/activate", headers=_hdr(_super()))
            assert r.status == 200
            assert (await r.json())["ok"] is False

    _run(_t())


# ============ 列表：鉴权 ============

def test_list_requires_superadmin():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/reimbursements", headers=_hdr(_user()))
            assert r.status == 403

    _run(_t())
