"""schema_migrations P2 baseline 测试。

测试目标（spec §五）：
    1. ensure_schema_migrations_table 可幂等创建 schema_migrations 表
    2. baseline_schema_migrations 把 SCHEMA_MIGRATIONS_BASELINE 全部写入
    3. baseline_schema_migrations 重复执行不会重复插入（INSERT OR IGNORE）
    4. baseline 中包含 reimbursements_queued_status 且 kind='hard'
    5. version 在 baseline 中唯一
    6. baseline 写入的 success 都是 1
    7. baseline 写入的 error 都是 NULL

为避免引入 pytest-asyncio 依赖，所有 async 调用通过 asyncio.run 在普通同步
test function 中执行。使用 aiosqlite 连接 :memory:，绝不访问真实 data/bot.db。
"""

from __future__ import annotations

import asyncio

import aiosqlite

from bot.database import (
    SCHEMA_MIGRATIONS_BASELINE,
    baseline_schema_migrations,
    ensure_schema_migrations_table,
)


# ============ helpers ============


def _run(coro):
    """同步包裹 async 协程，避免引入 pytest-asyncio。"""
    return asyncio.run(coro)


async def _fresh_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    return db


async def _table_exists(db: aiosqlite.Connection, name: str) -> bool:
    cur = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    return (await cur.fetchone()) is not None


# ============ ensure_schema_migrations_table ============


def test_ensure_creates_table():
    async def go():
        db = await _fresh_db()
        try:
            assert not await _table_exists(db, "schema_migrations")
            await ensure_schema_migrations_table(db)
            assert await _table_exists(db, "schema_migrations")
        finally:
            await db.close()
    _run(go())


def test_ensure_is_idempotent():
    """连续调用两次不应抛错。"""
    async def go():
        db = await _fresh_db()
        try:
            await ensure_schema_migrations_table(db)
            await ensure_schema_migrations_table(db)
            await ensure_schema_migrations_table(db)
            assert await _table_exists(db, "schema_migrations")
        finally:
            await db.close()
    _run(go())


def test_ensure_creates_expected_columns():
    """schema_migrations 表必须包含设计文档要求的全部 9 个字段。"""
    async def go():
        db = await _fresh_db()
        try:
            await ensure_schema_migrations_table(db)
            cur = await db.execute("PRAGMA table_info(schema_migrations)")
            cols = {row["name"] for row in await cur.fetchall()}
            expected = {
                "version", "name", "kind", "applied_at",
                "success", "error", "checksum", "duration_ms", "created_at",
            }
            assert expected <= cols, f"missing columns: {expected - cols}"
        finally:
            await db.close()
    _run(go())


# ============ baseline_schema_migrations ============


def test_baseline_inserts_all_rows():
    async def go():
        db = await _fresh_db()
        try:
            await ensure_schema_migrations_table(db)
            await baseline_schema_migrations(db)
            cur = await db.execute("SELECT COUNT(*) AS n FROM schema_migrations")
            row = await cur.fetchone()
            assert row["n"] == len(SCHEMA_MIGRATIONS_BASELINE)
        finally:
            await db.close()
    _run(go())


def test_baseline_is_idempotent():
    """重复 baseline 调用，行数应保持等于 len(SCHEMA_MIGRATIONS_BASELINE)。"""
    async def go():
        db = await _fresh_db()
        try:
            await ensure_schema_migrations_table(db)
            await baseline_schema_migrations(db)
            await baseline_schema_migrations(db)
            await baseline_schema_migrations(db)
            cur = await db.execute("SELECT COUNT(*) AS n FROM schema_migrations")
            row = await cur.fetchone()
            assert row["n"] == len(SCHEMA_MIGRATIONS_BASELINE)
        finally:
            await db.close()
    _run(go())


def test_baseline_inserts_correct_versions_and_kinds():
    """写入的 (version, kind) 必须与 SCHEMA_MIGRATIONS_BASELINE 完全一致。"""
    async def go():
        db = await _fresh_db()
        try:
            await ensure_schema_migrations_table(db)
            await baseline_schema_migrations(db)
            cur = await db.execute(
                "SELECT version, kind FROM schema_migrations ORDER BY version"
            )
            actual = {(r["version"], r["kind"]) for r in await cur.fetchall()}
            expected = {(v, k) for (v, _n, k) in SCHEMA_MIGRATIONS_BASELINE}
            assert actual == expected
        finally:
            await db.close()
    _run(go())


def test_baseline_all_success_one_and_error_null():
    async def go():
        db = await _fresh_db()
        try:
            await ensure_schema_migrations_table(db)
            await baseline_schema_migrations(db)
            cur = await db.execute(
                "SELECT version, success, error FROM schema_migrations"
            )
            rows = await cur.fetchall()
            for r in rows:
                assert r["success"] == 1, f"{r['version']} success != 1"
                assert r["error"] is None, f"{r['version']} error != NULL"
        finally:
            await db.close()
    _run(go())


def test_baseline_includes_reimbursements_queued_as_hard():
    """spec §五 要求：reimbursements_queued_status 必须存在且 kind='hard'。"""
    async def go():
        db = await _fresh_db()
        try:
            await ensure_schema_migrations_table(db)
            await baseline_schema_migrations(db)
            cur = await db.execute(
                "SELECT kind FROM schema_migrations WHERE version LIKE '%reimbursements_queued%'"
            )
            row = await cur.fetchone()
            assert row is not None, "reimbursements_queued_status baseline missing"
            assert row["kind"] == "hard"
        finally:
            await db.close()
    _run(go())


def test_baseline_pre_existing_row_is_not_overwritten():
    """baseline 用 INSERT OR IGNORE，已存在的 version 不应被覆盖。

    场景：未来 P3 阶段如果给某个 version 写入了 success=0 + error 详情，
    重启时 baseline 不能把它"洗白"为 success=1。
    """
    async def go():
        db = await _fresh_db()
        try:
            await ensure_schema_migrations_table(db)
            # 假装这条迁移真实失败过
            target = SCHEMA_MIGRATIONS_BASELINE[0][0]
            await db.execute(
                "INSERT INTO schema_migrations (version, name, kind, success, error) "
                "VALUES (?, ?, ?, 0, ?)",
                (target, "preserved name", "hard", "preserved error msg"),
            )
            await baseline_schema_migrations(db)
            cur = await db.execute(
                "SELECT name, kind, success, error FROM schema_migrations WHERE version=?",
                (target,),
            )
            row = await cur.fetchone()
            assert row["name"] == "preserved name"
            assert row["kind"] == "hard"
            assert row["success"] == 0
            assert row["error"] == "preserved error msg"
        finally:
            await db.close()
    _run(go())


# ============ 常量级断言（无需 DB） ============


def test_baseline_versions_unique():
    versions = [v for (v, _n, _k) in SCHEMA_MIGRATIONS_BASELINE]
    assert len(versions) == len(set(versions))


def test_baseline_versions_sorted_by_string():
    """version 字典序应等于列表中的执行顺序。"""
    versions = [v for (v, _n, _k) in SCHEMA_MIGRATIONS_BASELINE]
    assert versions == sorted(versions)


def test_baseline_kinds_are_only_soft_or_hard():
    for _v, _n, kind in SCHEMA_MIGRATIONS_BASELINE:
        assert kind in {"soft", "hard"}


def test_baseline_has_exactly_one_hard():
    """当前 baseline 仅 reimbursements_queued_status 为 hard。"""
    hard = [v for (v, _n, k) in SCHEMA_MIGRATIONS_BASELINE if k == "hard"]
    assert len(hard) == 1
    assert "reimbursements_queued" in hard[0]
