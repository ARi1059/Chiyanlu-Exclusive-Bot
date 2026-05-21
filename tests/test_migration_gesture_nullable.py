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
    """1) 手动建一个 gesture_photo_file_id NOT NULL 的旧表，插一条数据；
       2) 跑迁移；
       3) 验证 NOT NULL 已放宽 + 旧数据保留。"""
    import aiosqlite

    async def _go():
        async with aiosqlite.connect(fresh_db_path) as db:
            db.row_factory = aiosqlite.Row
            # 模拟旧 schema（仅 NOT NULL 与新 schema 不同）
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
                    published_at TEXT
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
