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
