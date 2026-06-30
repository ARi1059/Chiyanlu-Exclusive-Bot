"""评级自动判定（derive_rating）+ 回填迁移契约测试（2026-06-30）。

覆盖：
  - derive_rating 边界：<6 差评 / [6,7.5] 中评 / >7.5 好评 / 异常→中评
  - _migrate_006_rating_from_overall：全量按 overall 重判 rating（含 pending/approved/
    rejected）+ 重算 teacher_channel_posts 的 approved 三级计数；幂等可重跑。
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

import pytest

from bot.database import derive_rating


def _run(coro):
    return asyncio.run(coro)


# ============ derive_rating 边界 ============

@pytest.mark.parametrize("score,expected", [
    (0, "negative"), (5.9, "negative"), (5.99, "negative"),
    (6.0, "neutral"), (7.0, "neutral"), (7.5, "neutral"),
    (7.51, "positive"), (8.2, "positive"), (10, "positive"),
])
def test_derive_rating_boundaries(score, expected):
    assert derive_rating(score) == expected


def test_derive_rating_invalid_to_neutral():
    assert derive_rating(None) == "neutral"
    assert derive_rating("oops") == "neutral"


# ============ 回填迁移 ============

@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(prefix=f"test_rating_{uuid.uuid4().hex}_", suffix=".db")
    os.close(fd)
    from bot.config import config as _c
    orig = _c.database_path
    _c.database_path = path
    try:
        yield path
    finally:
        _c.database_path = orig
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(path + s)
            except FileNotFoundError:
                pass


async def _seed_review(db, *, rid, teacher_id, overall, rating, status):
    """直接插一条 review（rating 故意写成与 overall 不符，验证回填会纠正）。"""
    await db.execute(
        """INSERT INTO teacher_reviews
           (id, teacher_id, user_id, booking_screenshot_file_id, rating,
            score_humanphoto, score_appearance, score_body, score_service,
            score_attitude, score_environment, overall_score, status)
           VALUES (?, ?, ?, 'BK', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (rid, teacher_id, 1000 + rid, rating,
         overall, overall, overall, overall, overall, overall, overall, status),
    )


def test_migration_backfills_rating_and_counts(db_path):
    from bot.database import init_db, get_db, _migrate_006_rating_from_overall

    async def scenario():
        await init_db()
        db = await get_db()
        try:
            # 老师 + 频道帖（计数初值故意写错）
            await db.execute(
                "INSERT INTO teachers (user_id, username, display_name, region, price, tags, button_url) "
                "VALUES (1, 'u', 'T', 'R', '1000P', '[]', 'https://t.me/x')"
            )
            await db.execute(
                "INSERT INTO teacher_channel_posts (teacher_id, channel_chat_id, channel_msg_id, "
                "positive_count, neutral_count, negative_count) VALUES (1, -100, 5, 99, 99, 99)"
            )
            # 5 条评价：rating 全故意写错
            await _seed_review(db, rid=1, teacher_id=1, overall=4.0, rating="positive", status="approved")  # →neg
            await _seed_review(db, rid=2, teacher_id=1, overall=7.0, rating="positive", status="approved")  # →neu
            await _seed_review(db, rid=3, teacher_id=1, overall=9.0, rating="negative", status="approved")  # →pos
            await _seed_review(db, rid=4, teacher_id=1, overall=9.0, rating="neutral",  status="pending")   # →pos（非 approved，不计数）
            await _seed_review(db, rid=5, teacher_id=1, overall=2.0, rating="positive", status="rejected")  # →neg（不计数）
            await db.commit()

            # 跑回填迁移
            await _migrate_006_rating_from_overall(db)

            # ① 全量 rating 按 overall 重判（含 pending/rejected）
            cur = await db.execute("SELECT id, rating FROM teacher_reviews ORDER BY id")
            got = {r[0]: r[1] for r in await cur.fetchall()}
            assert got == {1: "negative", 2: "neutral", 3: "positive", 4: "positive", 5: "negative"}

            # ② teacher_channel_posts 只统计 approved（1 neg / 2 neu / 3 pos）
            cur = await db.execute(
                "SELECT positive_count, neutral_count, negative_count "
                "FROM teacher_channel_posts WHERE teacher_id = 1"
            )
            pos, neu, neg = await cur.fetchone()
            assert (pos, neu, neg) == (1, 1, 1)

            # ③ 幂等：再跑一次结果不变
            await _migrate_006_rating_from_overall(db)
            cur = await db.execute(
                "SELECT positive_count, neutral_count, negative_count "
                "FROM teacher_channel_posts WHERE teacher_id = 1"
            )
            assert tuple(await cur.fetchone()) == (1, 1, 1)
        finally:
            await db.close()

    _run(scenario())
