"""bot/web 管理台统计端点测试（P1）。

GET /api/admin/stats：user → 403；admin/superadmin → 200 含 point_packages 等。
内部聚合（overview / 趋势 / 队列 / 报销池）monkeypatch，避免触 DB。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.admin as mod
from bot.config import config
from bot.services.admin_overview import AdminOverviewStats
from bot.services.reimbursement_pool import ReimbursementPoolStats
from bot.web.auth import issue_session
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _tok(role: str, uid: int = 123) -> str:
    return issue_session(uid, role, config.bot_token)


def _patch_internals(monkeypatch):
    async def fake_overview():
        return AdminOverviewStats(
            today_checkin_teachers=3, today_new_users=2, today_new_reviews=1,
            pending_reviews=4, pending_reimbursements=0,
        )

    async def fake_counts():
        return {"active": 38, "inactive": 1, "total": 39}

    async def fake_trend():
        return [{"day": "06/27", "reviews": 1, "signins": 3}]

    async def fake_queue(limit=10):
        return []

    async def fake_pool():
        return ReimbursementPoolStats(feature_enabled=False, monthly_pool=6000,
                                      approved_amount_this_month=0, remaining_pool=6000)

    monkeypatch.setattr(mod, "get_admin_overview_stats", fake_overview)
    monkeypatch.setattr(mod, "get_teacher_counts", fake_counts)
    monkeypatch.setattr(mod, "_trend_7d", fake_trend)
    monkeypatch.setattr(mod, "_pending_queue", fake_queue)
    monkeypatch.setattr(mod, "get_reimbursement_pool_stats", fake_pool)


def test_stats_user_forbidden(monkeypatch):
    _patch_internals(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/stats", headers={"Authorization": f"Bearer {_tok('user')}"})
            assert r.status == 403

    _run(_t())


def test_stats_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            assert (await c.get("/api/admin/stats")).status == 401

    _run(_t())


def test_stats_superadmin_ok(monkeypatch):
    _patch_internals(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/stats",
                            headers={"Authorization": f"Bearer {_tok('superadmin')}"})
            assert r.status == 200
            d = await r.json()
            assert d["today_checkins"] == 3
            assert d["active_teachers"] == 38
            # 加分套餐随 stats 下发，且 delta 正确
            pkgs = {p["key"]: p["delta"] for p in d["point_packages"]}
            assert pkgs["night"] == 5 and pkgs["zero"] == 0
            # 报销池仅超管可见
            assert d["reimburse_pool"]["monthly_pool"] == 6000

    _run(_t())


def test_stats_admin_no_reimburse_pool(monkeypatch):
    """普通 admin（非超管）看不到报销池。"""
    _patch_internals(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/stats",
                            headers={"Authorization": f"Bearer {_tok('admin')}"})
            assert r.status == 200
            d = await r.json()
            assert "reimburse_pool" not in d

    _run(_t())
