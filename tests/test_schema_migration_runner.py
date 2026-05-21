"""schema_migrations P3 注册器执行测试（run_registered_migrations）。

覆盖 spec §四 中列出的全部行为：
    - 空 MIGRATIONS 不报错
    - 已成功的 version 被跳过
    - 新 soft / hard migration 成功后写 success=1
    - soft 失败：写 success=0 + error，不 raise
    - hard 失败：写 success=0 + error，raise
    - error 字段被截断
    - duration_ms 被写入
    - version 重复 raise ValueError
    - kind 非 soft/hard raise ValueError
    - 执行顺序按 version 字典序
    - success=0 旧记录重试成功后 error 被清空

为避免引入 pytest-asyncio：所有 async 通过 asyncio.run 包裹。
使用 aiosqlite.connect(":memory:")，不触碰真实 DB。
"""

from __future__ import annotations

import asyncio

import aiosqlite
import pytest

import bot.database as db_mod
from bot.database import (
    Migration,
    ensure_schema_migrations_table,
    run_registered_migrations,
    _MIGRATION_ERROR_MAX_LEN,
)


# ============ helpers ============


def _run(coro):
    return asyncio.run(coro)


async def _fresh_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await ensure_schema_migrations_table(db)
    return db


async def _all_rows(db: aiosqlite.Connection):
    cur = await db.execute(
        "SELECT version, name, kind, success, error, duration_ms "
        "FROM schema_migrations ORDER BY version"
    )
    return await cur.fetchall()


def _noop_mig(version: str, kind: str = "soft", name: str | None = None) -> Migration:
    async def _fn(db):  # pragma: no cover - touched by Migration.func
        pass
    return Migration(version=version, name=name or version, kind=kind, func=_fn)


def _raising_mig(
    version: str, exc: Exception, kind: str = "soft", name: str | None = None
) -> Migration:
    async def _fn(db):
        raise exc
    return Migration(version=version, name=name or version, kind=kind, func=_fn)


# ============ empty MIGRATIONS ============


def test_empty_migrations_is_noop(monkeypatch):
    """生产当前 MIGRATIONS=[]，run_registered_migrations 必须无副作用。"""
    monkeypatch.setattr(db_mod, "MIGRATIONS", [])

    async def go():
        db = await _fresh_db()
        try:
            await run_registered_migrations(db)
            rows = await _all_rows(db)
            assert rows == []
        finally:
            await db.close()
    _run(go())


def test_module_level_migrations_is_baseline():
    """生产代码 MIGRATIONS 应是 list；UX-9.3 引入第一条 baseline，
    UX-9.1（20260520_002_quick_entry_keywords）追加第二条；
    2026-05-21 评价前置改造追加第三条（teacher_reviews.gesture_photo_file_id 改可空）。"""
    assert isinstance(db_mod.MIGRATIONS, list)
    assert {m.version for m in db_mod.MIGRATIONS} == {
        "20260520_001_teacher_draft_states",
        "20260520_002_quick_entry_keywords",
        "20260521_001_teacher_reviews_gesture_nullable",
    }


# ============ 成功路径 ============


def test_soft_migration_success_records_success_1(monkeypatch):
    monkeypatch.setattr(db_mod, "MIGRATIONS", [
        _noop_mig("20260601_001_test_soft", kind="soft", name="test soft"),
    ])

    async def go():
        db = await _fresh_db()
        try:
            await run_registered_migrations(db)
            rows = await _all_rows(db)
            assert len(rows) == 1
            r = rows[0]
            assert r["version"] == "20260601_001_test_soft"
            assert r["name"] == "test soft"
            assert r["kind"] == "soft"
            assert r["success"] == 1
            assert r["error"] is None
            assert r["duration_ms"] is not None
            assert r["duration_ms"] >= 0
        finally:
            await db.close()
    _run(go())


def test_hard_migration_success_records_success_1(monkeypatch):
    monkeypatch.setattr(db_mod, "MIGRATIONS", [
        _noop_mig("20260601_002_test_hard", kind="hard"),
    ])

    async def go():
        db = await _fresh_db()
        try:
            await run_registered_migrations(db)
            rows = await _all_rows(db)
            assert len(rows) == 1
            assert rows[0]["kind"] == "hard"
            assert rows[0]["success"] == 1
        finally:
            await db.close()
    _run(go())


def test_already_success_is_skipped(monkeypatch):
    """version 已经在 schema_migrations 中 success=1 → 不再执行 func。"""
    calls = {"count": 0}

    async def fn(db):
        calls["count"] += 1

    mig = Migration(version="20260601_003_skip", name="skip", kind="soft", func=fn)
    monkeypatch.setattr(db_mod, "MIGRATIONS", [mig])

    async def go():
        db = await _fresh_db()
        try:
            # 跑两次
            await run_registered_migrations(db)
            assert calls["count"] == 1
            await run_registered_migrations(db)
            assert calls["count"] == 1  # 第二次跳过
            rows = await _all_rows(db)
            assert len(rows) == 1
            assert rows[0]["success"] == 1
        finally:
            await db.close()
    _run(go())


# ============ 失败路径 ============


def test_soft_failure_records_success_0_does_not_raise(monkeypatch):
    monkeypatch.setattr(db_mod, "MIGRATIONS", [
        _raising_mig("20260601_010_soft_fail", RuntimeError("simulated soft error"),
                     kind="soft"),
    ])

    async def go():
        db = await _fresh_db()
        try:
            # 不应 raise
            await run_registered_migrations(db)
            rows = await _all_rows(db)
            assert len(rows) == 1
            r = rows[0]
            assert r["success"] == 0
            assert r["error"] is not None
            assert "simulated soft error" in r["error"]
            assert r["duration_ms"] is not None
        finally:
            await db.close()
    _run(go())


def test_hard_failure_records_success_0_and_raises(monkeypatch):
    monkeypatch.setattr(db_mod, "MIGRATIONS", [
        _raising_mig("20260601_020_hard_fail", RuntimeError("simulated hard error"),
                     kind="hard"),
    ])

    async def go():
        db = await _fresh_db()
        try:
            with pytest.raises(RuntimeError, match="simulated hard error"):
                await run_registered_migrations(db)
            rows = await _all_rows(db)
            assert len(rows) == 1
            r = rows[0]
            assert r["success"] == 0
            assert "simulated hard error" in r["error"]
        finally:
            await db.close()
    _run(go())


def test_error_message_truncated(monkeypatch):
    """超长 traceback 应被截断到 _MIGRATION_ERROR_MAX_LEN（默认 500）。"""
    huge_msg = "x" * 5000
    monkeypatch.setattr(db_mod, "MIGRATIONS", [
        _raising_mig("20260601_030_huge_err", RuntimeError(huge_msg), kind="soft"),
    ])

    async def go():
        db = await _fresh_db()
        try:
            await run_registered_migrations(db)
            rows = await _all_rows(db)
            assert len(rows) == 1
            assert rows[0]["error"] is not None
            assert len(rows[0]["error"]) <= _MIGRATION_ERROR_MAX_LEN
        finally:
            await db.close()
    _run(go())


# ============ 静态校验 ============


def test_duplicate_version_raises_value_error(monkeypatch):
    monkeypatch.setattr(db_mod, "MIGRATIONS", [
        _noop_mig("20260601_dup"),
        _noop_mig("20260601_dup"),
    ])

    async def go():
        db = await _fresh_db()
        try:
            with pytest.raises(ValueError, match="重复 version"):
                await run_registered_migrations(db)
        finally:
            await db.close()
    _run(go())


def test_invalid_kind_raises_value_error(monkeypatch):
    monkeypatch.setattr(db_mod, "MIGRATIONS", [
        _noop_mig("20260601_badkind", kind="medium"),
    ])

    async def go():
        db = await _fresh_db()
        try:
            with pytest.raises(ValueError, match="kind"):
                await run_registered_migrations(db)
        finally:
            await db.close()
    _run(go())


# ============ 顺序与重试 ============


def test_execution_order_is_version_sorted_not_list_order(monkeypatch):
    """乱序追加到 MIGRATIONS，执行顺序仍按 version 字典序。"""
    order: list[str] = []

    def make(v: str) -> Migration:
        async def fn(db, _v=v):
            order.append(_v)
        return Migration(version=v, name=v, kind="soft", func=fn)

    # 乱序追加
    monkeypatch.setattr(db_mod, "MIGRATIONS", [
        make("20260601_003_c"),
        make("20260601_001_a"),
        make("20260601_002_b"),
    ])

    async def go():
        db = await _fresh_db()
        try:
            await run_registered_migrations(db)
            assert order == ["20260601_001_a", "20260601_002_b", "20260601_003_c"]
        finally:
            await db.close()
    _run(go())


def test_failed_migration_retries_next_run(monkeypatch):
    """soft 失败的记录会在下次跑时被重试。"""
    attempts = {"count": 0}

    async def fn(db):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("first attempt fails")
        # 第 2 次成功，no-op

    mig = Migration(version="20260601_040_retry", name="retry", kind="soft", func=fn)
    monkeypatch.setattr(db_mod, "MIGRATIONS", [mig])

    async def go():
        db = await _fresh_db()
        try:
            # 第 1 次：失败 → success=0 + error
            await run_registered_migrations(db)
            rows = await _all_rows(db)
            assert len(rows) == 1
            assert rows[0]["success"] == 0
            assert rows[0]["error"] is not None

            # 第 2 次：重试成功 → success=1 + error 被清空
            await run_registered_migrations(db)
            assert attempts["count"] == 2

            rows = await _all_rows(db)
            assert len(rows) == 1  # 仍然 1 行（UPSERT，不是 INSERT 新行）
            assert rows[0]["success"] == 1
            assert rows[0]["error"] is None
        finally:
            await db.close()
    _run(go())


def test_hard_failure_blocks_subsequent_migrations(monkeypatch):
    """hard migration 失败时立刻 raise，后续 migration 不应被执行。"""
    executed: list[str] = []

    async def hard_fail(db):
        raise RuntimeError("hard boom")

    async def later_noop(db):
        executed.append("later")

    monkeypatch.setattr(db_mod, "MIGRATIONS", [
        Migration("20260601_050_a_hard", "a", "hard", hard_fail),
        Migration("20260601_050_b_later", "b", "soft", later_noop),
    ])

    async def go():
        db = await _fresh_db()
        try:
            with pytest.raises(RuntimeError, match="hard boom"):
                await run_registered_migrations(db)
            # b 不应被执行
            assert executed == []
            # 但 a 应该有 success=0 记录
            rows = await _all_rows(db)
            versions = [r["version"] for r in rows]
            assert "20260601_050_a_hard" in versions
            assert "20260601_050_b_later" not in versions
        finally:
            await db.close()
    _run(go())


# ============ Migration dataclass 本身 ============


def test_migration_is_frozen_dataclass():
    """Migration 实例不可变 —— 防止运行时被改写 version/kind。"""
    m = _noop_mig("20260601_frozen")
    with pytest.raises(Exception):  # FrozenInstanceError 或类似
        m.version = "tampered"  # type: ignore[misc]


def test_migrations_list_is_typed_correctly():
    """MIGRATIONS 必须是 list 类型；UX-9.3 已引入 baseline，本测试现仅校验类型。"""
    assert isinstance(db_mod.MIGRATIONS, list)
    # 所有元素应是 Migration 实例
    from bot.database import Migration
    for m in db_mod.MIGRATIONS:
        assert isinstance(m, Migration)
