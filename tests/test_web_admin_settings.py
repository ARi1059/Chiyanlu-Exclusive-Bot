"""bot/web 档案发布配置端点测试（阶段2）。

  GET  /api/admin/settings/archive   非 admin→403；shape（含 effective + 回退）
  POST /api/admin/settings/archive   逐项校验落库；空键不动；非法→ok:false

DB 叶子函数（get_config / set_config / get_archive_channel_id / set_archive_channel_id）
在 admin_settings 模块命名空间，monkeypatch。
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

import bot.web.api.admin_settings as as_mod
from bot.config import config
from bot.web.auth import issue_session
from bot.web.server import create_web_app


def _run(coro):
    return asyncio.run(coro)


def _hdr(uid: int = 7, role: str = "admin") -> dict:
    return {"Authorization": f"Bearer {issue_session(uid, role, config.bot_token)}"}


def _patch(monkeypatch, *, store=None):
    """fake config KV（内存 store）+ 记录 set_archive_channel_id 调用。"""
    cfg = dict(store or {})
    calls = {"set_config": [], "set_archive": []}

    async def fake_get_config(key):
        return cfg.get(key)

    async def fake_set_config(key, value):
        cfg[key] = value
        calls["set_config"].append((key, value))

    async def fake_get_archive():
        raw = cfg.get("archive_channel_id")
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass
        fb = cfg.get("publish_channel_id")
        if fb:
            try:
                return int(fb.split(",")[0])
            except ValueError:
                pass
        return None

    async def fake_set_archive(chat_id):
        cfg["archive_channel_id"] = str(int(chat_id))
        calls["set_archive"].append(int(chat_id))

    monkeypatch.setattr(as_mod, "get_config", fake_get_config)
    monkeypatch.setattr(as_mod, "set_config", fake_set_config)
    monkeypatch.setattr(as_mod, "get_archive_channel_id", fake_get_archive)
    monkeypatch.setattr(as_mod, "set_archive_channel_id", fake_set_archive)
    return cfg, calls


# ============ GET ============

def test_get_requires_admin(monkeypatch):
    _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/settings/archive", headers=_hdr(role="user"))
            assert r.status == 403
    _run(_t())


def test_get_no_token_401(monkeypatch):
    _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            assert (await c.get("/api/admin/settings/archive")).status == 401
    _run(_t())


def test_get_shape_with_fallback(monkeypatch):
    # 无独立 archive_channel_id，但有 publish_channel_id → effective 回退
    _patch(monkeypatch, store={"publish_channel_id": "-100999", "archive_brand_name": "测试录"})

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.get("/api/admin/settings/archive", headers=_hdr())
            assert r.status == 200
            d = await r.json()
            assert d["channel_id"] == ""              # 无独立配置
            assert d["effective_channel_id"] == -100999  # 回退生效
            assert d["brand_name"] == "测试录"
            assert d["brand_name_default"] == "《痴颜录》"
    _run(_t())


# ============ POST ============

def test_post_requires_admin(monkeypatch):
    _, calls = _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/settings/archive", headers=_hdr(role="user"),
                             json={"brand_name": "x"})
            assert r.status == 403
    _run(_t())
    assert calls["set_config"] == []


def test_post_channel_id_number(monkeypatch):
    _, calls = _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/settings/archive", headers=_hdr(),
                             json={"channel_id": "-100123"})
            assert r.status == 200 and (await r.json())["ok"] is True
    _run(_t())
    assert calls["set_archive"] == [-100123]


def test_post_channel_id_empty_clears(monkeypatch):
    cfg, calls = _patch(monkeypatch, store={"archive_channel_id": "-100999"})

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/settings/archive", headers=_hdr(),
                             json={"channel_id": ""})
            assert r.status == 200 and (await r.json())["ok"] is True
    _run(_t())
    # 空串 → set_config 清空（非 set_archive_channel_id）
    assert ("archive_channel_id", "") in calls["set_config"]
    assert calls["set_archive"] == []


def test_post_channel_id_bad(monkeypatch):
    _, calls = _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/settings/archive", headers=_hdr(),
                             json={"channel_id": "abc"})
            assert r.status == 200
            d = await r.json()
            assert d["ok"] is False and d["error"] == "bad_channel_id" and d["field"] == "channel_id"
    _run(_t())
    assert calls["set_archive"] == []  # 非法不落库


def test_post_brand_name_ok(monkeypatch):
    cfg, _ = _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/settings/archive", headers=_hdr(),
                             json={"brand_name": "新品牌"})
            assert (await r.json())["ok"] is True
    _run(_t())
    assert cfg["archive_brand_name"] == "新品牌"


def test_post_brand_name_too_long(monkeypatch):
    _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/settings/archive", headers=_hdr(),
                             json={"brand_name": "名" * 31})
            d = await r.json()
            assert d["ok"] is False and d["error"] == "bad_brand_name"
    _run(_t())


def test_post_brand_channels_bad_at(monkeypatch):
    _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/settings/archive", headers=_hdr(),
                             json={"brand_channels": "@ok badone"})
            d = await r.json()
            assert d["ok"] is False and d["error"] == "bad_brand_channels"
    _run(_t())


def test_post_brand_channels_too_long(monkeypatch):
    _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/settings/archive", headers=_hdr(),
                             json={"brand_channels": "@" + "a" * 200})
            d = await r.json()
            assert d["ok"] is False and d["error"] == "too_long"
    _run(_t())


def test_post_brand_channels_ok(monkeypatch):
    cfg, _ = _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/settings/archive", headers=_hdr(),
                             json={"brand_channels": "@chan1 @chan2"})
            assert (await r.json())["ok"] is True
    _run(_t())
    assert cfg["archive_brand_channels"] == "@chan1 @chan2"


def test_post_partial_only_touches_given(monkeypatch):
    # 只传 brand_name → 不动 channel / brand_channels
    cfg, calls = _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/settings/archive", headers=_hdr(),
                             json={"brand_name": "仅改名"})
            assert (await r.json())["ok"] is True
    _run(_t())
    keys = [k for k, _ in calls["set_config"]]
    assert keys == ["archive_brand_name"]
    assert calls["set_archive"] == []


def test_post_bad_json_400(monkeypatch):
    _patch(monkeypatch)

    async def _t():
        async with TestClient(TestServer(create_web_app(bot=None))) as c:
            r = await c.post("/api/admin/settings/archive", headers=_hdr(), data="not json")
            assert r.status == 400
    _run(_t())
