"""bot/web 评价审核详情 + claim 占用锁 + 媒体端点测试（§15.4）。

覆盖：
  - GET /api/admin/reviews/{id}              详情（6 维分 / 媒体签名 URL / 资格预判 / claim）
  - POST /api/admin/reviews/{id}/claim       占用锁声明 + 冲突
  - POST /api/admin/reviews/{id}/force-claim 强制接管 + 写 audit
  - POST /api/admin/reviews/{id}/release     释放
  - GET /api/admin/reviews/{id}/media/{kind} 签名媒体代理（错签/缺图/正常）

DB / proxy 全 monkeypatch；token 用 issue_session 直接签（中间件同 secret 验）。
claim 用真实内存锁，reset_for_test() 隔离用例。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.admin_reviews as mod
import bot.web.api.review_media as media_mod
from bot.config import config
from bot.utils.review_claim import reset_for_test
from bot.web.auth import issue_session, sign_media
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _super(uid: int | None = None) -> str:
    return issue_session(uid or config.super_admin_id, "superadmin", config.bot_token)


def _user(uid: int = 99999999) -> str:
    return issue_session(uid, "user", config.bot_token)


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _review(**over) -> dict:
    r = {
        "id": 5, "teacher_id": 100, "user_id": 12345678,
        "rating": "positive",
        "score_humanphoto": 8.0, "score_appearance": 9.0, "score_body": 7.5,
        "score_service": 8.5, "score_attitude": 9.0, "score_environment": 7.0,
        "overall_score": 8.2, "summary": "过程顺利，体验不错。",
        "status": "pending", "anonymous": 0, "request_reimbursement": 1,
        "booking_screenshot_file_id": "BOOKING_FID",
        "gesture_photo_file_id": "GESTURE_FID",
        "created_at": "2026-06-29 10:00:00",
    }
    r.update(over)
    return r


def _patch_detail_deps(monkeypatch, review: dict, *, teacher=None):
    teacher = teacher if teacher is not None else {"display_name": "小美", "price": "1000P"}

    async def fake_get_review(rid):
        return review if int(rid) == int(review["id"]) else None

    async def fake_get_teacher(tid):
        return teacher

    async def fake_total_points(uid):
        return 10

    async def fake_min_points():
        return 5

    async def fake_get_user(uid):
        return {"username": "holder", "first_name": "H"}

    monkeypatch.setattr(mod, "get_teacher_review", fake_get_review)
    monkeypatch.setattr(mod, "get_teacher", fake_get_teacher)
    monkeypatch.setattr(mod, "get_user_total_points", fake_total_points)
    monkeypatch.setattr(mod, "get_reimbursement_min_points", fake_min_points)
    monkeypatch.setattr(mod, "get_user", fake_get_user)
    monkeypatch.setattr(mod, "compute_reimbursement_amount", lambda price: 200)


# ============ 详情 ============

def test_detail_requires_superadmin(monkeypatch):
    _patch_detail_deps(monkeypatch, _review())

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/admin/reviews/5", headers=_hdr(_user()))
            assert r.status == 403

    _run(_t())


def test_detail_returns_full_fields(monkeypatch):
    reset_for_test()
    _patch_detail_deps(monkeypatch, _review())

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/admin/reviews/5", headers=_hdr(_super()))
            assert r.status == 200
            d = (await r.json())["detail"]
            # 6 维分
            assert d["scores"]["humanphoto"] == 8.0 and d["scores"]["overall"] == 8.2
            assert d["rating"]["label"] == "好评"
            # 半匿名
            assert d["user_masked"].endswith("5678") and d["user_masked"].startswith("*")
            # 媒体签名 URL（两张都在）
            assert "/api/admin/reviews/5/media/booking?sig=" in d["media"]["booking_url"]
            assert "/api/admin/reviews/5/media/gesture?sig=" in d["media"]["gesture_url"]
            # 资格预判：金额 200 > 0，积分 10 >= 门槛 5 → eligible
            assert d["reimbursement"]["amount"] == 200
            assert d["reimbursement"]["eligible"] is True
            assert d["reimbursement"]["requested"] == 1
            # 无人占用
            assert d["claim"]["held_by"] is None and d["claim"]["by_me"] is False

    _run(_t())


def test_detail_gesture_null_hides_url(monkeypatch):
    reset_for_test()
    _patch_detail_deps(monkeypatch, _review(gesture_photo_file_id=None))

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/admin/reviews/5", headers=_hdr(_super()))
            d = (await r.json())["detail"]
            assert d["media"]["booking_url"] is not None
            assert d["media"]["gesture_url"] is None

    _run(_t())


def test_detail_not_found_404(monkeypatch):
    _patch_detail_deps(monkeypatch, _review(id=5))

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/admin/reviews/999", headers=_hdr(_super()))
            assert r.status == 404

    _run(_t())


# ============ claim / force-claim / release ============

def test_claim_acquire_then_conflict(monkeypatch):
    reset_for_test()
    _patch_detail_deps(monkeypatch, _review())
    a, b = 111, 222

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r1 = await c.post("/api/admin/reviews/5/claim", headers=_hdr(_super(a)))
            assert r1.status == 200
            j1 = await r1.json()
            assert j1["ok"] is True and j1["detail"]["claim"]["by_me"] is True
            # B 抢同一条 → 冲突，带 A 的持有信息
            r2 = await c.post("/api/admin/reviews/5/claim", headers=_hdr(_super(b)))
            j2 = await r2.json()
            assert j2["ok"] is False
            assert j2["claim"]["held_by"] == a
            assert j2["claim"]["held_by_name"] == "@holder"

    _run(_t())


def test_force_claim_writes_audit(monkeypatch):
    reset_for_test()
    _patch_detail_deps(monkeypatch, _review())
    audits: list[dict] = []

    async def fake_audit(**kw):
        audits.append(kw)

    monkeypatch.setattr(mod, "log_admin_audit", fake_audit)
    a, b = 111, 222

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            await c.post("/api/admin/reviews/5/claim", headers=_hdr(_super(a)))
            r = await c.post("/api/admin/reviews/5/force-claim", headers=_hdr(_super(b)))
            assert r.status == 200
            d = (await r.json())["detail"]
            assert d["claim"]["held_by"] == b and d["claim"]["by_me"] is True

    _run(_t())
    assert len(audits) == 1
    assert audits[0]["action"] == "rreview_force_claim"
    assert audits[0]["target_type"] == "teacher_review"
    assert audits[0]["target_id"] == "5"
    assert audits[0]["detail"]["previous_holder"] == a


def test_release_frees_lock(monkeypatch):
    reset_for_test()
    _patch_detail_deps(monkeypatch, _review())
    a, b = 111, 222

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            await c.post("/api/admin/reviews/5/claim", headers=_hdr(_super(a)))
            rr = await c.post("/api/admin/reviews/5/release", headers=_hdr(_super(a)))
            assert rr.status == 200 and (await rr.json())["ok"] is True
            # 释放后 B 可顺利接手
            r2 = await c.post("/api/admin/reviews/5/claim", headers=_hdr(_super(b)))
            assert (await r2.json())["ok"] is True

    _run(_t())


# ============ 媒体端点 ============

def _media_sig(review_id: int, kind: str) -> str:
    return sign_media(f"rev{review_id}:{kind}", config.bot_token)


def test_media_bad_signature_403(monkeypatch):
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/admin/reviews/5/media/booking?sig=deadbeef.bad")
            assert r.status == 403

    _run(_t())


def test_media_gesture_null_404(monkeypatch):
    async def fake_get_review(rid):
        return _review(gesture_photo_file_id=None)

    monkeypatch.setattr(media_mod, "get_teacher_review", fake_get_review)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            sig = _media_sig(5, "gesture")
            r = await c.get(f"/api/admin/reviews/5/media/gesture?sig={sig}")
            assert r.status == 404

    _run(_t())


def test_media_ok_returns_image(monkeypatch):
    async def fake_get_review(rid):
        return _review()

    async def fake_proxy(bot, file_id):
        assert file_id == "BOOKING_FID"
        return "image/jpeg", b"\xff\xd8\xff\xe0JFIF"

    monkeypatch.setattr(media_mod, "get_teacher_review", fake_get_review)
    monkeypatch.setattr(media_mod, "proxy_telegram_file", fake_proxy)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            sig = _media_sig(5, "booking")
            r = await c.get(f"/api/admin/reviews/5/media/booking?sig={sig}")
            assert r.status == 200
            assert r.headers["Content-Type"] == "image/jpeg"
            assert (await r.read()).startswith(b"\xff\xd8")

    _run(_t())
