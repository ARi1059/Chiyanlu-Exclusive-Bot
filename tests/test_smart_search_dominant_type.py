"""search_teachers_smart_and 主导类型识别回归测试。

修复前 bug：单个 token 同时是地区和标签（如「心岛」是 14 位老师的地区，又被某 1 位
老师误设为标签）时，函数把它同时塞进 region 组和 tag 组，跨类型 AND 后把结果错误
收窄到「同时满足两者」的那 1 位老师，导致群内地区关键词只回 1 张卡而非全部列表。

修复后：单 token 多类型时取「命中老师数最多」的主导类型（平局 地区>价格>标签），
「心岛」按地区返回全部，多 token 的同类型 OR / 跨类型 AND 语义保持不变。

用真实 :memory: SQLite（monkeypatch bot.database.get_db 共享连接）。
"""
from __future__ import annotations

import asyncio
import json

import aiosqlite

import bot.database as db_mod


def _run(coro):
    return asyncio.run(coro)


async def _fresh_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.execute(
        """
        CREATE TABLE teachers (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT,
            region TEXT,
            price TEXT,
            tags TEXT,
            is_active INTEGER DEFAULT 1,
            is_deleted INTEGER DEFAULT 0,
            created_at TEXT DEFAULT '2026-01-01'
        )
        """
    )
    return db


async def _seed(db: aiosqlite.Connection) -> None:
    """3 位「心岛」老师（其中 T2 的标签里混入「心岛」）+ 1 位「天府」老师。"""
    rows = [
        (1, "甲", "心岛", "1000P", ["御姐"]),
        (2, "乙", "心岛", "1000P", ["心岛", "御姐"]),   # ← 标签里混入地区名「心岛」
        (3, "丙", "心岛", "800P", ["萝莉"]),
        (4, "丁", "天府", "1000P", ["御姐"]),
    ]
    for uid, name, region, price, tags in rows:
        await db.execute(
            "INSERT INTO teachers (user_id, display_name, region, price, tags) "
            "VALUES (?, ?, ?, ?, ?)",
            (uid, name, region, price, json.dumps(tags, ensure_ascii=False)),
        )
    await db.commit()


def _patch_get_db(monkeypatch, db: aiosqlite.Connection):
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


def _names(teachers):
    return {t["display_name"] for t in teachers}


def test_region_tag_collision_returns_all_region_matches(monkeypatch):
    """「心岛」既是地区(3 人)又是某老师标签(1 人) → 按地区返回全部 3 人，而非收窄到 1。"""
    async def go():
        db = await _fresh_db()
        try:
            await _seed(db)
            _patch_get_db(monkeypatch, db)
            teachers, unrec = await db_mod.search_teachers_smart_and(["心岛"])
            assert _names(teachers) == {"甲", "乙", "丙"}  # 3 位心岛老师全在
            assert unrec == []
        finally:
            await db.close()
    _run(go())


def test_pure_tag_token_unaffected(monkeypatch):
    """纯标签 token（不与地区/价格同名）仍按标签 OR 返回全部。"""
    async def go():
        db = await _fresh_db()
        try:
            await _seed(db)
            _patch_get_db(monkeypatch, db)
            teachers, _ = await db_mod.search_teachers_smart_and(["御姐"])
            assert _names(teachers) == {"甲", "乙", "丁"}  # 三位带「御姐」标签
        finally:
            await db.close()
    _run(go())


def test_cross_type_and_preserved(monkeypatch):
    """跨类型 AND 不变：标签「御姐」AND 地区「天府」→ 仅丁。"""
    async def go():
        db = await _fresh_db()
        try:
            await _seed(db)
            _patch_get_db(monkeypatch, db)
            teachers, _ = await db_mod.search_teachers_smart_and(["御姐", "天府"])
            assert _names(teachers) == {"丁"}
        finally:
            await db.close()
    _run(go())


def test_two_regions_or_preserved(monkeypatch):
    """同类型（两个地区）OR 不变：心岛 OR 天府 → 全部 4 人（心岛仍按地区主导）。"""
    async def go():
        db = await _fresh_db()
        try:
            await _seed(db)
            _patch_get_db(monkeypatch, db)
            teachers, _ = await db_mod.search_teachers_smart_and(["心岛", "天府"])
            assert _names(teachers) == {"甲", "乙", "丙", "丁"}
        finally:
            await db.close()
    _run(go())


def test_price_token(monkeypatch):
    """价格 token 按价格返回（1000P → 甲乙丁）。"""
    async def go():
        db = await _fresh_db()
        try:
            await _seed(db)
            _patch_get_db(monkeypatch, db)
            teachers, _ = await db_mod.search_teachers_smart_and(["1000p"])
            assert _names(teachers) == {"甲", "乙", "丁"}
        finally:
            await db.close()
    _run(go())


def test_unrecognized_token(monkeypatch):
    async def go():
        db = await _fresh_db()
        try:
            await _seed(db)
            _patch_get_db(monkeypatch, db)
            teachers, unrec = await db_mod.search_teachers_smart_and(["不存在xyz"])
            assert teachers == []
            assert unrec == ["不存在xyz"]
        finally:
            await db.close()
    _run(go())
