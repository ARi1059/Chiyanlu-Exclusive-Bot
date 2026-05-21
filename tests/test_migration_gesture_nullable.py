"""Migration 20260521_001_teacher_reviews_gesture_nullable 契约测试。

覆盖：
    - 既有旧 DB（gesture_photo_file_id NOT NULL）跑迁移后变为 nullable
    - 已有评价行数据 + 索引保留
    - 已迁移过的 DB（已 nullable）再跑一次是 no-op（幂等）
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

import pytest


def _run(coro):
    return asyncio.run(coro)


async def _gesture_notnull(db) -> int:
    """读 PRAGMA table_info 拿 gesture_photo_file_id 的 notnull 标志。"""
    cur = await db.execute("PRAGMA table_info(teacher_reviews)")
    rows = await cur.fetchall()
    for r in rows:
        if r[1] == "gesture_photo_file_id":
            return int(r[3])
    return -1


async def _row_count(db, table="teacher_reviews") -> int:
    cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
    row = await cur.fetchone()
    return int(row[0]) if row else 0


@pytest.fixture
def fresh_db_path():
    fd, path = tempfile.mkstemp(
        prefix=f"test_migr_{uuid.uuid4().hex}_", suffix=".db",
    )
    os.close(fd)
    yield path
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass


def test_migration_relaxes_not_null(fresh_db_path):
    """1) 手动建一个 gesture_photo_file_id NOT NULL 的旧表 + teachers 外键依赖；
       2) 跑迁移；
       3) 验证 NOT NULL 已放宽 + 旧数据保留。"""
    import aiosqlite

    async def _go():
        async with aiosqlite.connect(fresh_db_path) as db:
            db.row_factory = aiosqlite.Row
            # teachers 表（被 teacher_reviews FK 引用）
            await db.execute(
                "CREATE TABLE teachers (user_id INTEGER PRIMARY KEY, "
                "display_name TEXT)"
            )
            await db.execute(
                "INSERT INTO teachers (user_id, display_name) VALUES (1, 'T')"
            )
            # 模拟旧 schema（带 FK 到 teachers，与生产一致）
            await db.execute(
                """CREATE TABLE teacher_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    teacher_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    booking_screenshot_file_id TEXT NOT NULL,
                    gesture_photo_file_id TEXT NOT NULL,
                    rating TEXT NOT NULL,
                    score_humanphoto REAL NOT NULL,
                    score_appearance REAL NOT NULL,
                    score_body REAL NOT NULL,
                    score_service REAL NOT NULL,
                    score_attitude REAL NOT NULL,
                    score_environment REAL NOT NULL,
                    overall_score REAL NOT NULL,
                    summary TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewer_id INTEGER,
                    reject_reason TEXT,
                    discussion_chat_id INTEGER,
                    discussion_msg_id INTEGER,
                    request_reimbursement INTEGER NOT NULL DEFAULT 0,
                    anonymous INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TEXT,
                    published_at TEXT,
                    FOREIGN KEY (teacher_id) REFERENCES teachers(user_id) ON DELETE CASCADE
                )"""
            )
            # 写入测试数据 + 索引
            await db.execute(
                """INSERT INTO teacher_reviews
                   (teacher_id, user_id, booking_screenshot_file_id, gesture_photo_file_id,
                    rating, score_humanphoto, score_appearance, score_body,
                    score_service, score_attitude, score_environment, overall_score,
                    summary, request_reimbursement, anonymous)
                   VALUES (1, 100, 'fb', 'fg', 'good', 8,8,8,8,8,8, 8.0, 'ok', 1, 0)""",
            )
            await db.commit()

            before = await _gesture_notnull(db)
            assert before == 1  # 旧 schema 是 NOT NULL

            # 跑迁移
            from bot.database import _migrate_003_teacher_reviews_gesture_nullable
            await _migrate_003_teacher_reviews_gesture_nullable(db)

            after = await _gesture_notnull(db)
            assert after == 0  # 已放宽

            # 数据保留
            n = await _row_count(db)
            assert n == 1
            cur = await db.execute("SELECT gesture_photo_file_id FROM teacher_reviews")
            row = await cur.fetchone()
            assert row[0] == "fg"

            # 索引重建：抽样检查一个
            cur = await db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='teacher_reviews'"
            )
            idx_names = {r[0] for r in await cur.fetchall()}
            assert "idx_reviews_teacher_status" in idx_names

    _run(_go())


def test_migration_with_active_foreign_key_from_reimbursements(fresh_db_path):
    """生产场景：reimbursements.review_id FK → teacher_reviews(id) ON DELETE CASCADE，
    且连接 PRAGMA foreign_keys=ON。迁移必须先关 FK 再 DROP/RENAME，否则
    DROP TABLE teacher_reviews 会被拒绝或级联清空 reimbursements。

    2026-05-21 修复回归：原版未关 FK 导致 update 时 hard migration 失败。
    """
    import aiosqlite

    async def _go():
        async with aiosqlite.connect(fresh_db_path) as db:
            # 模拟生产连接的 PRAGMA
            await db.execute("PRAGMA foreign_keys = ON")
            db.row_factory = aiosqlite.Row

            # 旧 schema：teacher_reviews + 关联表 reimbursements（CASCADE FK）
            await db.execute("""
                CREATE TABLE teachers (
                    user_id INTEGER PRIMARY KEY, display_name TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE teacher_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    teacher_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    booking_screenshot_file_id TEXT NOT NULL,
                    gesture_photo_file_id TEXT NOT NULL,
                    rating TEXT NOT NULL,
                    score_humanphoto REAL NOT NULL,
                    score_appearance REAL NOT NULL,
                    score_body REAL NOT NULL,
                    score_service REAL NOT NULL,
                    score_attitude REAL NOT NULL,
                    score_environment REAL NOT NULL,
                    overall_score REAL NOT NULL,
                    summary TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewer_id INTEGER,
                    reject_reason TEXT,
                    discussion_chat_id INTEGER,
                    discussion_msg_id INTEGER,
                    request_reimbursement INTEGER NOT NULL DEFAULT 0,
                    anonymous INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TEXT,
                    published_at TEXT,
                    FOREIGN KEY (teacher_id) REFERENCES teachers(user_id) ON DELETE CASCADE
                )
            """)
            # 关键：reimbursements.review_id FK → teacher_reviews(id) ON DELETE CASCADE
            await db.execute("""
                CREATE TABLE reimbursements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    review_id INTEGER NOT NULL UNIQUE,
                    teacher_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    week_key TEXT NOT NULL,
                    month_key TEXT NOT NULL,
                    FOREIGN KEY (review_id) REFERENCES teacher_reviews(id) ON DELETE CASCADE
                )
            """)
            # 写一条评价 + 一条关联报销
            await db.execute(
                "INSERT INTO teachers (user_id, display_name) VALUES (1, 'T')",
            )
            await db.execute("""
                INSERT INTO teacher_reviews
                  (id, teacher_id, user_id, booking_screenshot_file_id,
                   gesture_photo_file_id, rating,
                   score_humanphoto, score_appearance, score_body,
                   score_service, score_attitude, score_environment, overall_score,
                   request_reimbursement, anonymous)
                VALUES (42, 1, 100, 'fb', 'fg', 'good',
                        8,8,8,8,8,8, 8.0, 1, 0)
            """)
            await db.execute("""
                INSERT INTO reimbursements
                  (user_id, review_id, teacher_id, amount, status, week_key, month_key)
                VALUES (100, 42, 1, 200, 'pending', '2026-W21', '2026-05')
            """)
            await db.commit()

            # 迁移前快照
            cur = await db.execute("SELECT COUNT(*) FROM reimbursements")
            reimb_before = (await cur.fetchone())[0]
            assert reimb_before == 1

            # 跑迁移
            from bot.database import _migrate_003_teacher_reviews_gesture_nullable
            await _migrate_003_teacher_reviews_gesture_nullable(db)

            # 验证 1：gesture 列可空
            cur = await db.execute("PRAGMA table_info(teacher_reviews)")
            cols = await cur.fetchall()
            for c in cols:
                if c[1] == "gesture_photo_file_id":
                    assert int(c[3]) == 0, "gesture_photo_file_id 应可空"
                    break

            # 验证 2：reimbursements 行 **未被级联清空**
            cur = await db.execute("SELECT COUNT(*) FROM reimbursements")
            reimb_after = (await cur.fetchone())[0]
            assert reimb_after == 1, (
                f"reimbursements 行数从 {reimb_before} 变为 {reimb_after}，"
                "意味着 DROP TABLE 触发了 CASCADE—— FK 没有被正确关掉！"
            )

            # 验证 3：FK 仍然指向新表（teacher_reviews id=42 仍在）+ 完整
            cur = await db.execute(
                "SELECT review_id FROM reimbursements WHERE id = 1"
            )
            assert (await cur.fetchone())[0] == 42

            # 验证 4：foreign_keys 恢复 ON
            cur = await db.execute("PRAGMA foreign_keys")
            assert (await cur.fetchone())[0] == 1

    _run(_go())


def test_migration_is_idempotent_when_already_nullable(fresh_db_path):
    """已经是 nullable schema 的库再跑一次迁移应直接 return，不重建表。"""
    import aiosqlite

    async def _go():
        async with aiosqlite.connect(fresh_db_path) as db:
            # 直接建新 schema（gesture nullable）
            await db.execute(
                """CREATE TABLE teacher_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    teacher_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    booking_screenshot_file_id TEXT NOT NULL,
                    gesture_photo_file_id TEXT,
                    rating TEXT NOT NULL,
                    score_humanphoto REAL NOT NULL,
                    score_appearance REAL NOT NULL,
                    score_body REAL NOT NULL,
                    score_service REAL NOT NULL,
                    score_attitude REAL NOT NULL,
                    score_environment REAL NOT NULL,
                    overall_score REAL NOT NULL,
                    summary TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewer_id INTEGER,
                    reject_reason TEXT,
                    discussion_chat_id INTEGER,
                    discussion_msg_id INTEGER,
                    request_reimbursement INTEGER NOT NULL DEFAULT 0,
                    anonymous INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TEXT,
                    published_at TEXT
                )"""
            )
            await db.commit()

            before = await _gesture_notnull(db)
            assert before == 0  # 已是 nullable

            from bot.database import _migrate_003_teacher_reviews_gesture_nullable
            await _migrate_003_teacher_reviews_gesture_nullable(db)

            # 仍是 nullable，且未崩溃
            after = await _gesture_notnull(db)
            assert after == 0

    _run(_go())
