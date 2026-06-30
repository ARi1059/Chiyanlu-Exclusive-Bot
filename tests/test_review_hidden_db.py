"""评价隐藏 DB 层单测（真库）：list_approved_reviews 排除 hidden + set_review_hidden。"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

import pytest


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(prefix=f"test_hidden_{uuid.uuid4().hex}_", suffix=".db")
    os.close(fd)
    from bot.config import config as _c
    orig = _c.database_path
    _c.database_path = path
    try:
        from bot.database import init_db
        asyncio.run(init_db())
        yield path
    finally:
        _c.database_path = orig
        for s in ("", "-wal", "-shm"):
            try:
                os.remove(path + s)
            except FileNotFoundError:
                pass


def _run(coro):
    return asyncio.run(coro)


async def _seed_teacher(teacher_id):
    """插一条老师（满足 teacher_reviews 的 FK）。"""
    from bot.database import get_db
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO teachers
               (user_id, username, display_name, region, price, tags, button_url)
               VALUES (?,?,?,?,?,?,?)""",
            (teacher_id, "t", "小美", "心岛", "1000P", "[]", "https://t.me/x"),
        )
        await db.commit()
    finally:
        await db.close()


async def _seed_review(teacher_id, user_id, overall, status="approved", hidden=0):
    """直插一条 review（绕过 create 的必填校验，仅测可见性过滤）。"""
    await _seed_teacher(teacher_id)
    from bot.database import get_db
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO teacher_reviews
               (teacher_id, user_id, booking_screenshot_file_id, rating,
                score_humanphoto, score_appearance, score_body, score_service,
                score_attitude, score_environment, overall_score, summary,
                status, hidden)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (teacher_id, user_id, "FID", "positive",
             overall, overall, overall, overall, overall, overall, overall,
             "x", status, hidden),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


def test_list_approved_excludes_hidden(temp_db):
    from bot.database import list_approved_reviews

    async def _t():
        await _seed_review(100, 1, 9.0, status="approved", hidden=0)
        await _seed_review(100, 2, 8.0, status="approved", hidden=1)  # 隐藏
        await _seed_review(100, 3, 7.0, status="approved", hidden=0)
        rows = await list_approved_reviews(100, limit=50)
        return rows

    rows = _run(_t())
    assert len(rows) == 2  # 隐藏的不在列表
    assert all(int(r.get("hidden") or 0) == 0 for r in rows)


def test_set_review_hidden_toggles(temp_db):
    from bot.database import set_review_hidden, get_teacher_review, list_approved_reviews

    async def _t():
        rid = await _seed_review(100, 1, 9.0, status="approved", hidden=0)
        # 初始可见
        assert len(await list_approved_reviews(100)) == 1
        # 隐藏
        ok = await set_review_hidden(rid, True)
        assert ok
        assert int((await get_teacher_review(rid))["hidden"]) == 1
        assert len(await list_approved_reviews(100)) == 0  # 隐藏后消失
        # 取消隐藏
        await set_review_hidden(rid, False)
        assert len(await list_approved_reviews(100)) == 1  # 恢复

    _run(_t())


def test_recalc_still_counts_hidden(temp_db):
    """数据照常：隐藏评价仍计入老师评分统计（recalc 不看 hidden）。"""
    from bot.database import recalculate_teacher_review_stats

    async def _t():
        await _seed_review(100, 1, 9.0, status="approved", hidden=0)
        await _seed_review(100, 2, 8.0, status="approved", hidden=1)  # 隐藏但仍算
        stats = await recalculate_teacher_review_stats(100)
        return stats

    stats = _run(_t())
    # 两条 approved 都计入（含隐藏的）
    assert int(stats.get("review_count") or 0) == 2
