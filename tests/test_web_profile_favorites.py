"""bot/web 个人页 + 收藏端点测试（P1）。

覆盖：
  - GET  /api/profile      字段含 notify_enabled / points / 计数
  - GET  /api/me/points    流水 reason→中文 label、delta
  - POST /api/me/notify    开关落库（透传 enabled）
  - 收藏 GET(401) / POST(add, 幂等) / POST 坏 body(400) / DELETE(remove)

DB 函数 monkeypatch（:memory: 跨连接不持表）。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.favorites as fav_mod
import bot.web.api.profile as prof_mod
from bot.config import config
from bot.web.auth import issue_session
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _tok(uid: int = 555, role: str = "user") -> str:
    return issue_session(uid, role, config.bot_token)


def _hdr(uid: int = 555) -> dict:
    return {"Authorization": f"Bearer {_tok(uid)}"}


# ============ profile ============

def test_profile_shape(monkeypatch):
    async def fake_user(uid):
        return {"user_id": uid, "username": "chiyan", "first_name": "痴颜",
                "total_points": 1280, "notify_enabled": 1}

    async def fake_review_count(uid, status_filter=None):
        return 8

    async def fake_favs(uid):
        return [{"user_id": 1}, {"user_id": 2}]

    monkeypatch.setattr(prof_mod, "get_user", fake_user)
    monkeypatch.setattr(prof_mod, "count_user_reviews", fake_review_count)
    monkeypatch.setattr(prof_mod, "list_user_favorites", fake_favs)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/profile", headers=_hdr())
            assert r.status == 200
            d = await r.json()
            assert d["username"] == "chiyan"
            assert d["points"] == 1280
            assert d["review_count"] == 8
            assert d["favorite_count"] == 2
            assert d["notify_enabled"] is True

    _run(_t())


def test_profile_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            assert (await c.get("/api/profile")).status == 401

    _run(_t())


def test_my_points_labels(monkeypatch):
    async def fake_txs(uid, limit=50):
        return [
            {"delta": 5, "reason": "review_approved", "note": "包夜", "created_at": "2026-06-20 14:23:00"},
            {"delta": -3, "reason": "admin_revoke", "note": "", "created_at": "2026-06-19 10:00:00"},
        ]

    async def fake_total(uid):
        return 100

    monkeypatch.setattr(prof_mod, "list_user_point_transactions", fake_txs)
    monkeypatch.setattr(prof_mod, "get_user_total_points", fake_total)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/me/points", headers=_hdr())
            assert r.status == 200
            d = await r.json()
            assert d["total"] == 100
            assert d["transactions"][0]["label"] == "评价通过"    # reason→中文
            assert d["transactions"][0]["delta"] == 5
            assert d["transactions"][1]["label"] == "管理员扣分"

    _run(_t())


def test_set_notify_roundtrip(monkeypatch):
    rec: dict = {}

    async def fake_set(uid, enabled):
        rec.update(uid=uid, enabled=enabled)
        return True

    monkeypatch.setattr(prof_mod, "set_user_notify_enabled", fake_set)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/notify", headers=_hdr(uid=777), json={"enabled": False})
            assert r.status == 200
            assert (await r.json())["notify_enabled"] is False

    _run(_t())
    assert rec == {"uid": 777, "enabled": False}


# ============ favorites ============

def test_favorites_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            assert (await c.get("/api/favorites")).status == 401

    _run(_t())


def test_favorite_add(monkeypatch):
    rec: dict = {}

    async def fake_add(uid, tid):
        rec.update(uid=uid, tid=tid)
        return True

    monkeypatch.setattr(fav_mod, "add_favorite", fake_add)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/favorites", headers=_hdr(uid=42), json={"teacher_id": 9})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True and d["favorited"] is True

    _run(_t())
    assert rec == {"uid": 42, "tid": 9}


def test_favorite_add_bad_body_400(monkeypatch):
    async def fake_add(uid, tid):
        raise AssertionError("不应到达 add_favorite")

    monkeypatch.setattr(fav_mod, "add_favorite", fake_add)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/favorites", headers=_hdr(), json={})  # 缺 teacher_id
            assert r.status == 400

    _run(_t())


def test_favorite_delete(monkeypatch):
    rec: dict = {}

    async def fake_remove(uid, tid):
        rec.update(uid=uid, tid=tid)
        return True

    monkeypatch.setattr(fav_mod, "remove_favorite", fake_remove)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.delete("/api/favorites/9", headers=_hdr(uid=42))
            assert r.status == 200
            assert (await r.json())["favorited"] is False

    _run(_t())
    assert rec == {"uid": 42, "tid": 9}


# ============ GET /api/me/reviews ============

def test_my_reviews_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/me/reviews")
            assert r.status == 401

    _run(_t())


def test_my_reviews_shape(monkeypatch):
    async def fake_list(uid, limit=30):
        return [
            {"id": 1, "teacher_id": 100, "rating": "positive", "status": "approved",
             "overall_score": 9.0, "summary": "好", "created_at": "2026-06-20 10:00:00"},
            {"id": 2, "teacher_id": 200, "rating": "neutral", "status": "pending",
             "overall_score": 7.5, "summary": "", "created_at": "2026-06-21 11:00:00"},
        ]

    async def fake_teacher(tid):
        return {"display_name": f"老师{tid}"} if tid == 100 else None

    monkeypatch.setattr(prof_mod, "list_user_reviews_paged", fake_list)
    monkeypatch.setattr(prof_mod, "get_teacher", fake_teacher)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/me/reviews", headers=_hdr(uid=42))
            assert r.status == 200
            revs = (await r.json())["reviews"]
            assert len(revs) == 2
            by = {x["id"]: x for x in revs}
            assert by[1]["teacher"] == "老师100" and by[1]["status"] == "approved"
            assert by[1]["overall_score"] == 9.0 and by[1]["rating"] == "positive"
            assert by[2]["teacher"] == "未知"        # 老师不存在 → 兜底
            assert by[2]["status"] == "pending"

    _run(_t())


def test_my_reviews_empty(monkeypatch):
    async def fake_list(uid, limit=30):
        return []

    monkeypatch.setattr(prof_mod, "list_user_reviews_paged", fake_list)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/me/reviews", headers=_hdr(uid=42))
            assert r.status == 200
            assert (await r.json())["reviews"] == []

    _run(_t())


# ============ 老师签到 POST /api/me/checkin ============

def test_checkin_non_teacher_403():
    """非老师角色 → 403。"""
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/checkin", headers={"Authorization": f"Bearer {_tok(role='user')}"})
            assert r.status == 403

    _run(_t())


def test_checkin_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/checkin")
            assert r.status == 401

    _run(_t())


def test_checkin_inactive_teacher_ok_false(monkeypatch):
    """停用老师 → ok:false（不抛错）。"""
    async def fake_teacher(uid):
        return {"user_id": uid, "is_active": 0, "display_name": "T"}

    monkeypatch.setattr(prof_mod, "get_teacher", fake_teacher)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/checkin", headers={"Authorization": f"Bearer {_tok(role='teacher')}"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False

    _run(_t())


def test_checkin_closed_window_ok_false(monkeypatch):
    """已过 publish_time → ok:false（截止）。publish_time 设 00:00 必然已过。"""
    async def fake_teacher(uid):
        return {"user_id": uid, "is_active": 1, "display_name": "T"}

    async def fake_get_config(key):
        return "00:00" if key == "publish_time" else None

    monkeypatch.setattr(prof_mod, "get_teacher", fake_teacher)
    monkeypatch.setattr(prof_mod, "get_config", fake_get_config)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/checkin", headers={"Authorization": f"Bearer {_tok(role='teacher')}"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False
            assert "截止" in (d.get("error") or "")

    _run(_t())


def test_checkin_success(monkeypatch):
    """窗口内 + 未签 → checkin_teacher 调用，ok:true already:false。"""
    async def fake_teacher(uid):
        return {"user_id": uid, "is_active": 1, "display_name": "T"}

    async def fake_get_config(key):
        return "23:59" if key == "publish_time" else None  # 几乎不会截止

    async def fake_is_checked_in(uid, day):
        return False

    called = {}

    async def fake_checkin(uid, day):
        called["uid"] = uid
        return True

    monkeypatch.setattr(prof_mod, "get_teacher", fake_teacher)
    monkeypatch.setattr(prof_mod, "get_config", fake_get_config)
    monkeypatch.setattr(prof_mod, "is_checked_in", fake_is_checked_in)
    monkeypatch.setattr(prof_mod, "checkin_teacher", fake_checkin)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/checkin", headers={"Authorization": f"Bearer {_tok(uid=777, role='teacher')}"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True
            assert d["already"] is False
            assert called["uid"] == 777

    _run(_t())


def test_checkin_idempotent_already(monkeypatch):
    """已签到 → ok:true already:true，不再调 checkin_teacher。"""
    async def fake_teacher(uid):
        return {"user_id": uid, "is_active": 1, "display_name": "T"}

    async def fake_get_config(key):
        return "23:59" if key == "publish_time" else None

    async def fake_is_checked_in(uid, day):
        return True

    async def boom(uid, day):
        raise AssertionError("已签到不应再调 checkin_teacher")

    monkeypatch.setattr(prof_mod, "get_teacher", fake_teacher)
    monkeypatch.setattr(prof_mod, "get_config", fake_get_config)
    monkeypatch.setattr(prof_mod, "is_checked_in", fake_is_checked_in)
    monkeypatch.setattr(prof_mod, "checkin_teacher", boom)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/me/checkin", headers={"Authorization": f"Bearer {_tok(role='teacher')}"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is True
            assert d["already"] is True

    _run(_t())
