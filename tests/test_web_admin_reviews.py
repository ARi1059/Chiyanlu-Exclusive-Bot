"""bot/web 评价审核端点测试（P1）。

覆盖 POST /api/admin/reviews/{id}/approve|reject：
  - 鉴权：仅 superadmin（user → 403，service 不被调用）
  - 加分套餐：package_key 后端权威解析 delta/label；自定义 delta 范围校验
  - 委托：成功路径调用 review_moderation.approve_review/reject_review 并透传参数
  - 业务失败（评价不存在/已审）→ 200 + {ok:false}

DB / service 全部 monkeypatch（:memory: 跨连接不持表，conftest）；token 用
issue_session 直接签（中间件用同一 secret 验）。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.admin_reviews as mod
from bot.config import config
from bot.services.review_moderation import ApproveResult, RejectResult
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


# ============ approve：鉴权 ============

def test_approve_requires_superadmin(monkeypatch):
    called = {"n": 0}

    async def fake_approve(*a, **k):
        called["n"] += 1
        return ApproveResult(ok=True)

    monkeypatch.setattr(mod, "approve_review", fake_approve)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/reviews/5/approve",
                             headers=_hdr(_user()), json={"package_key": "night"})
            assert r.status == 403

    _run(_t())
    assert called["n"] == 0  # 鉴权拦在 service 之前


def test_approve_no_token_401(monkeypatch):
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/reviews/5/approve", json={"package_key": "night"})
            assert r.status == 401

    _run(_t())


# ============ approve：加分套餐解析 ============

def test_approve_preset_resolves_delta(monkeypatch):
    rec: dict = {}

    async def fake_approve(bot, *, review_id, reviewer_id, delta, package_label):
        rec.update(review_id=review_id, delta=delta, package_label=package_label)
        return ApproveResult(ok=True, review_id=review_id, delta=delta, new_total=42)

    monkeypatch.setattr(mod, "approve_review", fake_approve)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reviews/5/approve",
                             headers=_hdr(_super()), json={"package_key": "night"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True and d["new_total"] == 42

    _run(_t())
    assert rec["review_id"] == 5
    assert rec["delta"] == 5            # 包夜 = +5（后端权威解析）
    assert rec["package_label"] == "包夜"


def test_approve_unknown_package_400(monkeypatch):
    async def fake_approve(*a, **k):
        raise AssertionError("不应到达 service")

    monkeypatch.setattr(mod, "approve_review", fake_approve)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reviews/5/approve",
                             headers=_hdr(_super()), json={"package_key": "bogus"})
            assert r.status == 400

    _run(_t())


def test_approve_missing_amount_400(monkeypatch):
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reviews/5/approve", headers=_hdr(_super()), json={})
            assert r.status == 400

    _run(_t())


def test_approve_custom_delta_out_of_range_400(monkeypatch):
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reviews/5/approve",
                             headers=_hdr(_super()), json={"delta": 9999})
            assert r.status == 400

    _run(_t())


def test_approve_custom_delta_ok(monkeypatch):
    rec: dict = {}

    async def fake_approve(bot, *, review_id, reviewer_id, delta, package_label):
        rec.update(delta=delta)
        return ApproveResult(ok=True, review_id=review_id, delta=delta)

    monkeypatch.setattr(mod, "approve_review", fake_approve)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reviews/5/approve",
                             headers=_hdr(_super()), json={"delta": 7})
            assert r.status == 200

    _run(_t())
    assert rec["delta"] == 7


def test_approve_business_failure_ok_false(monkeypatch):
    async def fake_approve(*a, **k):
        return ApproveResult(ok=False, error="评价不存在")

    monkeypatch.setattr(mod, "approve_review", fake_approve)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reviews/5/approve",
                             headers=_hdr(_super()), json={"package_key": "zero"})
            assert r.status == 200            # 业务失败仍 200，前端读 body
            d = await r.json()
            assert d["ok"] is False and d["error"] == "评价不存在"

    _run(_t())


# ============ reject ============

def test_reject_requires_superadmin(monkeypatch):
    called = {"n": 0}

    async def fake_reject(*a, **k):
        called["n"] += 1
        return RejectResult(ok=True)

    monkeypatch.setattr(mod, "reject_review", fake_reject)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/reviews/5/reject", headers=_hdr(_user()), json={})
            assert r.status == 403

    _run(_t())
    assert called["n"] == 0


def test_reject_delegates_with_reason(monkeypatch):
    rec: dict = {}

    async def fake_reject(bot, *, review_id, reviewer_id, reason):
        rec.update(review_id=review_id, reason=reason)
        return RejectResult(ok=True, review_id=review_id)

    monkeypatch.setattr(mod, "reject_review", fake_reject)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.post("/api/admin/reviews/7/reject",
                             headers=_hdr(_super()), json={"reason": "证据不充分"})
            assert r.status == 200
            assert (await r.json())["ok"] is True

    _run(_t())
    assert rec["review_id"] == 7
    assert rec["reason"] == "证据不充分"
