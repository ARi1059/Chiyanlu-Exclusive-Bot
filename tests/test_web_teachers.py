"""bot/web 老师列表端点测试（P1）。

覆盖 GET /api/teachers：鉴权、可约(今日签到)优先排序、favorited 标记、available
语义、tags 解析；以及照片端点的签名门（无/错签名 403，有效签名放行）。

DB 函数 monkeypatch（:memory: 跨连接不持表）。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.teachers as mod
from bot.config import config
from bot.web.auth import issue_session, sign_photo
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _super() -> str:
    return issue_session(config.super_admin_id, "superadmin", config.bot_token)


def _teacher(uid: int, name: str, photo=None) -> dict:
    return {
        "user_id": uid, "display_name": name, "region": "心岛", "price": "1000P",
        "tags": '["御姐", "颜值车"]', "is_active": 1, "photo_file_id": photo,
    }


def _patch_list(monkeypatch):
    t1, t2, t3 = _teacher(1, "A"), _teacher(2, "B"), _teacher(3, "C")

    async def fake_all(*a, **k):
        return [t1, t2, t3]                       # 入册顺序 1,2,3

    async def fake_checked(date_str):
        return [t2]                               # 仅 2 今日签到

    async def fake_favs(uid):
        return [{"user_id": 1}]                   # 用户收藏了 1

    async def fake_post(tid):
        return {"avg_overall": 9.0, "review_count": 4}

    monkeypatch.setattr(mod, "get_all_teachers", fake_all)
    monkeypatch.setattr(mod, "get_checked_in_teachers", fake_checked)
    monkeypatch.setattr(mod, "list_user_favorites", fake_favs)
    monkeypatch.setattr(mod, "get_teacher_channel_post", fake_post)


def test_teachers_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/teachers")
            assert r.status == 401

    _run(_t())


def test_teachers_available_first_and_flags(monkeypatch):
    _patch_list(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/teachers", headers={"Authorization": f"Bearer {_super()}"})
            assert r.status == 200
            ts = (await r.json())["teachers"]
            assert [t["id"] for t in ts] == [2, 1, 3]        # 可约(2)在前，其余按入册
            by = {t["id"]: t for t in ts}
            assert by[2]["available"] is True                # 今日签到 = 可约
            assert by[1]["available"] is False and by[3]["available"] is False
            assert by[1]["favorited"] is True                # 收藏标记
            assert by[2]["favorited"] is False
            assert by[1]["tags"] == ["御姐", "颜值车"]         # JSON 解析为 list
            assert by[1]["rating"] == {"avg": 9.0, "count": 4}
            assert by[1]["photo_url"] is None                # 无照片

    _run(_t())


# ============ 照片签名门 ============

def test_photo_missing_sig_403():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/teachers/1/photo")          # 无 sig（白名单路径但 handler 校验）
            assert r.status == 403

    _run(_t())


def test_photo_bad_sig_403():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/teachers/1/photo?sig=123.deadbeef")
            assert r.status == 403

    _run(_t())


def test_photo_valid_sig_passes_gate(monkeypatch):
    # 有效签名应过门 → 进入取老师；空库下 get_teacher 返回 None → 404（证明签名通过）
    import bot.web.api.photo as photo_mod

    async def fake_get_teacher(tid):
        return None

    monkeypatch.setattr(photo_mod, "get_teacher", fake_get_teacher)
    sig = sign_photo(1, config.bot_token)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get(f"/api/teachers/1/photo?sig={sig}")
            assert r.status == 404                            # 过了签名门，只是无照片

    _run(_t())


# ============ 老师详情 GET /api/teachers/{id} ============

def test_teacher_detail_no_token_401():
    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/teachers/1")
            assert r.status == 401

    _run(_t())


def test_teacher_detail_not_found_404(monkeypatch):
    async def fake_profile(tid):
        return None                                           # 不存在

    monkeypatch.setattr(mod, "get_teacher_full_profile", fake_profile)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/teachers/999", headers={"Authorization": f"Bearer {_super()}"})
            assert r.status == 404

    _run(_t())


def test_teacher_detail_deleted_404(monkeypatch):
    async def fake_profile(tid):
        return {"user_id": tid, "display_name": "X", "is_deleted": 1, "tags": []}

    monkeypatch.setattr(mod, "get_teacher_full_profile", fake_profile)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/teachers/5", headers={"Authorization": f"Bearer {_super()}"})
            assert r.status == 404                            # 软删除也视为不存在

    _run(_t())


def test_teacher_detail_shape(monkeypatch):
    async def fake_profile(tid):
        # get_teacher_full_profile 把 photo_album 解析为 list（空则回退 [photo_file_id]）
        return {
            "user_id": tid, "display_name": "晚棠", "region": "天府一街",
            "price": "900P", "tags": ["御姐", "大长腿"], "is_active": 1,
            "is_deleted": 0, "photo_file_id": "PH", "photo_album": ["PH1", "PH2", "PH3"],
        }

    async def fake_post(tid):
        return {"avg_overall": 9.2, "review_count": 7}

    async def fake_reviews(tid, limit=20):
        return [
            {"id": 11, "rating": "positive", "summary": "很好", "user_id": 123456, "anonymous": 0, "created_at": "2026-06-20 10:00:00"},
            {"id": 12, "rating": "neutral", "summary": "一般", "user_id": 0, "anonymous": 1, "created_at": "2026-06-21 11:00:00"},
        ]

    async def fake_checked(tid, date_str):
        return True                                           # 今日已签到 → 可约

    monkeypatch.setattr(mod, "get_teacher_full_profile", fake_profile)
    monkeypatch.setattr(mod, "get_teacher_channel_post", fake_post)
    monkeypatch.setattr(mod, "list_approved_reviews", fake_reviews)
    monkeypatch.setattr(mod, "is_checked_in", fake_checked)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=object()))) as c:
            r = await c.get("/api/teachers/7", headers={"Authorization": f"Bearer {_super()}"})
            assert r.status == 200
            d = await r.json()
            assert d["id"] == 7 and d["name"] == "晚棠"
            assert d["region"] == "天府一街" and d["price"] == "900P"
            assert d["available"] is True                     # is_checked_in → 可约
            assert d["rating"] == {"avg": 9.2, "count": 7}
            assert isinstance(d["dims"], list) and len(d["dims"]) > 0
            assert d["photo_url"] and "sig=" in d["photo_url"]  # 有照片 → 签名 URL
            assert len(d["photos"]) == 3 and all("sig=" in p for p in d["photos"])  # 相册轮播
            assert "&i=" in d["photos"][1]                      # 非首张带 index
            assert len(d["reviews"]) == 2
            sigs = {rv["id"]: rv["sig"] for rv in d["reviews"]}
            assert sigs[11] == "****3456"                     # 实名末4位脱敏
            assert sigs[12] == "匿名"                          # 匿名

    _run(_t())
