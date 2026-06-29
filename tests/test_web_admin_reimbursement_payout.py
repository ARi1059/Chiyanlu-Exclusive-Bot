"""bot/web 报销详情 + 打款 + 重置端点测试（§15.5）。

覆盖 GET /{id}（badge 四态字段）、POST /{id}/payout（委托 core + token 不回显 + 鉴权）、
POST /{id}/reset-week。core/DB 全 monkeypatch；token 用 issue_session 直接签。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.admin_reimbursements as mod
from bot.config import config
from bot.services.reimbursement_moderation import PayoutPrecheck, PayoutResult, ResetResult
from bot.web.auth import issue_session
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _super(uid: int | None = None) -> str:
    return issue_session(uid or config.super_admin_id, "superadmin", config.bot_token)


def _user(uid: int = 99999999) -> str:
    return issue_session(uid, "user", config.bot_token)


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _reimb(**over) -> dict:
    d = {
        "id": 1, "user_id": 555, "review_id": 7, "teacher_id": 100,
        "amount": 200, "status": "pending",
        "week_key": "2026-W26", "month_key": "2026-06", "created_at": "2026-06-29 10:00:00",
    }
    d.update(over)
    return d


# ============ 详情 ============

def test_detail_requires_super(monkeypatch):
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/admin/reimbursements/1", headers=_hdr(_user()))
            assert r.status == 403

    _run(_t())


def test_detail_returns_badge(monkeypatch):
    async def fake_get_reimb(rid):
        return _reimb()

    async def fake_get_teacher(tid):
        return {"display_name": "小美", "price": "1000P"}

    async def fake_get_user(uid):
        return {"username": "stud"}

    async def fake_precheck(reimb):
        return PayoutPrecheck(
            state="need_voucher", amount=200, week_used=3, weekly_limit=3,
            month_used=0, pool=0, pool_remaining=None, has_reset=True,
            reset_voucher_id=9,
        )

    monkeypatch.setattr(mod, "get_reimbursement", fake_get_reimb)
    monkeypatch.setattr(mod, "get_teacher", fake_get_teacher)
    monkeypatch.setattr(mod, "get_user", fake_get_user)
    monkeypatch.setattr(mod, "compute_payout_precheck", fake_precheck)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/admin/reimbursements/1", headers=_hdr(_super()))
            assert r.status == 200
            d = (await r.json())["detail"]
            assert d["amount"] == 200 and d["teacher"] == "小美"
            assert d["teacher_price"] == "1000P"
            assert d["badge"]["state"] == "need_voucher"
            assert d["badge"]["week_used"] == 3 and d["badge"]["weekly_limit"] == 3
            assert d["badge"]["has_reset"] is True
            assert "voucher" in d["badge"]["label"]

    _run(_t())


def test_detail_not_found_404(monkeypatch):
    async def fake_get_reimb(rid):
        return None

    monkeypatch.setattr(mod, "get_reimbursement", fake_get_reimb)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/admin/reimbursements/999", headers=_hdr(_super()))
            assert r.status == 404

    _run(_t())


# ============ 打款 ============

def test_payout_requires_super(monkeypatch):
    called = {"n": 0}

    async def fake_core(*a, **k):
        called["n"] += 1
        return PayoutResult(ok=True)

    monkeypatch.setattr(mod, "payout_reimbursement_core", fake_core)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/reimbursements/1/payout",
                             headers=_hdr(_user()), json={"token": "ABCD1234"})
            assert r.status == 403

    _run(_t())
    assert called["n"] == 0  # 鉴权拦在 core 之前


def test_payout_delegates_and_hides_token(monkeypatch):
    rec = {}

    async def fake_core(bot, *, reimb_id, admin_id, token):
        rec.update(reimb_id=reimb_id, admin_id=admin_id, token=token)
        return PayoutResult(ok=True, reimb_id=reimb_id, amount=200)

    monkeypatch.setattr(mod, "payout_reimbursement_core", fake_core)
    secret = "ALIPAY-SECRET-9988"

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reimbursements/1/payout",
                             headers=_hdr(_super(42)), json={"token": secret})
            assert r.status == 200
            text = await r.text()
            d = await r.json()
            assert d["ok"] is True and d["amount"] == 200
            # 口令绝不出现在响应里
            assert secret not in text

    _run(_t())
    assert rec["reimb_id"] == 1 and rec["admin_id"] == 42
    assert rec["token"] == secret  # 原样透传给 core


def test_payout_business_fail_ok_false(monkeypatch):
    async def fake_core(*a, **k):
        return PayoutResult(ok=False, error="超月池：本月仅剩 100 元")

    monkeypatch.setattr(mod, "payout_reimbursement_core", fake_core)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reimbursements/1/payout",
                             headers=_hdr(_super()), json={"token": "ABCD1234"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False and "超月池" in d["error"]

    _run(_t())


def test_payout_empty_token_business_fail(monkeypatch):
    # 不 monkeypatch core：真 core 先做 token 长度校验，token="" → ok:false（不碰 DB）
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reimbursements/1/payout",
                             headers=_hdr(_super()), json={})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False

    _run(_t())


# ============ 重置本周 ============

def test_reset_week_delegates(monkeypatch):
    rec = {}

    async def fake_get_reimb(rid):
        return _reimb()

    async def fake_reset(*, reimb_id, user_id, admin_id):
        rec.update(reimb_id=reimb_id, user_id=user_id, admin_id=admin_id)
        return ResetResult(ok=True, reimb_id=reimb_id, voucher_id=77)

    monkeypatch.setattr(mod, "get_reimbursement", fake_get_reimb)
    monkeypatch.setattr(mod, "grant_reset_core", fake_reset)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reimbursements/1/reset-week", headers=_hdr(_super(42)))
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True and d["voucher_id"] == 77

    _run(_t())
    assert rec["reimb_id"] == 1 and rec["user_id"] == 555 and rec["admin_id"] == 42


def test_reset_week_requires_super(monkeypatch):
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reimbursements/1/reset-week", headers=_hdr(_user()))
            assert r.status == 403

    _run(_t())
