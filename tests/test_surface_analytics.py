"""双轨埋点 + 占比统计测试（§16.4）。

覆盖：
  - log_surface_event：写入 user_events，event_type = "{surface}:{action}"
  - get_surface_split：按 web:/非 web: 分轨，DISTINCT 用户数 + 事件数；今日档

用真实 :memory: SQLite（patch bot.database.get_db 返回共享不真关连接），
建最小 user_events 表，验证分轨聚合正确。
"""
from __future__ import annotations

import asyncio

import aiosqlite

import bot.database as db_mod


def _run(coro):
    return asyncio.run(coro)


async def _fresh_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.execute(
        """
        CREATE TABLE user_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.commit()
    return db


def _patch_get_db(monkeypatch, db: aiosqlite.Connection):
    """劫持 db_mod.get_db → 返回不真关 wrapper（多次 get_db 拿同一连接）。
    用 monkeypatch 注册，测试结束自动还原，避免污染其它用例。"""
    async def _fake_get_db():
        class _W:
            def __init__(self, r):
                self._r = r
            def __getattr__(self, n):
                return getattr(self._r, n)
            async def close(self):
                pass
        return _W(db)
    monkeypatch.setattr(db_mod, "get_db", _fake_get_db)


def test_log_surface_event_writes_prefixed_type(monkeypatch):
    async def go():
        db = await _fresh_db()
        try:
            _patch_get_db(monkeypatch, db)
            await db_mod.log_surface_event(111, "web", "active", {"path": "/api/me"})
            await db_mod.log_surface_event(222, "bot", "open")

            cur = await db.execute(
                "SELECT user_id, event_type FROM user_events ORDER BY id"
            )
            rows = [dict(r) for r in await cur.fetchall()]
            assert rows[0]["event_type"] == "web:active"
            assert rows[0]["user_id"] == 111
            assert rows[1]["event_type"] == "bot:open"
        finally:
            await db.close()

    _run(go())


def test_get_surface_split_partitions_by_track(monkeypatch):
    async def go():
        db = await _fresh_db()
        try:
            _patch_get_db(monkeypatch, db)
            # web 轨：用户 1、2（2 条 web 事件 user1 + 1 条 user2）
            await db_mod.log_surface_event(1, "web", "active")
            await db_mod.log_surface_event(1, "web", "active")
            await db_mod.log_surface_event(2, "web", "active")
            # bot 轨：用户 3（log_surface_event）+ 用户 4（历史无前缀事件）
            await db_mod.log_surface_event(3, "bot", "open")
            await db_mod.log_user_event(4, "search", {"q": "御姐"})

            split = await db_mod.get_surface_split(window_days=7)
            today = split["today"]
            assert today["web_users"] == 2     # user1, user2
            assert today["web_events"] == 3     # 3 条 web:active
            assert today["bot_users"] == 2     # user3(bot:open) + user4(search 无前缀)
            assert today["bot_events"] == 2
            assert split["window_days"] == 7
            # week 档至少覆盖今日，应 ≥ today
            assert split["week"]["web_users"] >= 2
        finally:
            await db.close()

    _run(go())


def test_get_surface_split_empty(monkeypatch):
    async def go():
        db = await _fresh_db()
        try:
            _patch_get_db(monkeypatch, db)
            split = await db_mod.get_surface_split()
            assert split["today"] == {
                "web_users": 0, "bot_users": 0, "web_events": 0, "bot_events": 0,
            }
        finally:
            await db.close()

    _run(go())
