"""卡片证据步条件化测试（2026-05-21）。

覆盖：
    - _evidence_required_count: req=1 时 2 张，req=0 时 1 张
    - _missing_fields: req=0 时仅检查 booking；req=1 时检查 booking + gesture
    - _build_card_text: 证据 label 按 req 渲染（约课记录 1/1 vs 出击证明 2/2）
    - _CARD_FIELDS evidence 项的 _card_field_filled 按 req 判
    - create_teacher_review: gesture_photo_file_id=None 时仍可落库（req=0 路径）
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_evid_{uuid.uuid4().hex}_", suffix=".db",
    )
    os.close(fd)
    from bot.config import config as _config
    original_path = _config.database_path
    _config.database_path = path
    try:
        from bot.database import init_db
        asyncio.run(init_db())
        yield path
    finally:
        _config.database_path = original_path
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass


def _run(coro):
    return asyncio.run(coro)


# ============================================================
# 1. _evidence_required_count
# ============================================================


def test_evidence_count_req_1_is_two():
    from bot.handlers.review_card import _evidence_required_count
    assert _evidence_required_count({"request_reimbursement": 1}) == 2


def test_evidence_count_req_0_is_one():
    from bot.handlers.review_card import _evidence_required_count
    assert _evidence_required_count({"request_reimbursement": 0}) == 1


def test_evidence_count_no_req_defaults_one():
    """state.data 中尚未写 request_reimbursement → 视为 0（普通评价路径）。"""
    from bot.handlers.review_card import _evidence_required_count
    assert _evidence_required_count({}) == 1


# ============================================================
# 2. _missing_fields
# ============================================================


def test_missing_fields_req_0_does_not_require_gesture():
    from bot.handlers.review_card import _missing_fields
    data = {
        "request_reimbursement": 0,
        "booking_screenshot_file_id": "f1",
        # gesture_photo_file_id 缺 → 不应进 missing
        "rating": "good",
        "score_humanphoto": 8, "score_appearance": 8, "score_body": 8,
        "score_service": 8, "score_attitude": 8, "score_environment": 8,
        "summary": "ok ok ok",
    }
    miss = _missing_fields(data)
    assert "🖼 出击证明" not in miss
    assert "🖼 约课记录" not in miss  # booking 已填
    assert miss == []  # 全齐


def test_missing_fields_req_0_requires_booking():
    """req=0 但 booking 缺 → 标签为「约课记录」（不是出击证明）。"""
    from bot.handlers.review_card import _missing_fields
    miss = _missing_fields({"request_reimbursement": 0})
    assert "🖼 约课记录" in miss
    assert "🖼 出击证明" not in miss


def test_missing_fields_req_1_requires_both():
    """req=1 + booking 有 + gesture 缺 → 「出击证明」缺失。"""
    from bot.handlers.review_card import _missing_fields
    miss = _missing_fields({
        "request_reimbursement": 1,
        "booking_screenshot_file_id": "f1",
        # gesture 缺
    })
    assert "🖼 出击证明" in miss


def test_missing_fields_req_1_both_present():
    """req=1 + 两张都齐 → evidence 不在 missing。"""
    from bot.handlers.review_card import _missing_fields
    data = {
        "request_reimbursement": 1,
        "booking_screenshot_file_id": "f1",
        "gesture_photo_file_id": "f2",
        "rating": "good",
        "score_humanphoto": 8, "score_appearance": 8, "score_body": 8,
        "score_service": 8, "score_attitude": 8, "score_environment": 8,
        "summary": "ok ok ok",
    }
    miss = _missing_fields(data)
    assert "🖼 出击证明" not in miss


# ============================================================
# 3. _build_card_text 渲染（label + 路径 banner）
# ============================================================


def test_build_card_text_req_0_shows_booking_label(monkeypatch):
    from bot.handlers import review_card
    fake_state = MagicMock()
    fake_state.get_data = AsyncMock(return_value={
        "teacher_id": 1, "request_reimbursement": 0,
        "booking_screenshot_file_id": "f1",
    })

    async def _fake_get_teacher(tid):
        return {"display_name": "T", "is_active": True}
    monkeypatch.setattr(review_card, "get_teacher", _fake_get_teacher)

    text = _run(review_card._build_card_text(fake_state))
    assert "约课记录" in text
    assert "1/1" in text
    assert "现场手势" not in text  # 不参与路径不应露现场手势字样
    assert "普通评价路径" in text  # 报销 banner


def test_build_card_text_req_1_shows_evidence_label(monkeypatch):
    from bot.handlers import review_card
    fake_state = MagicMock()
    fake_state.get_data = AsyncMock(return_value={
        "teacher_id": 1, "request_reimbursement": 1,
        "booking_screenshot_file_id": "f1",
        "gesture_photo_file_id": "f2",
    })

    async def _fake_get_teacher(tid):
        return {"display_name": "T", "is_active": True}
    monkeypatch.setattr(review_card, "get_teacher", _fake_get_teacher)

    text = _run(review_card._build_card_text(fake_state))
    assert "出击证明" in text
    assert "2/2" in text
    assert "参与" in text  # 报销 banner 含「参与」字样


# ============================================================
# 4. _card_field_filled evidence 项
# ============================================================


def test_card_field_filled_evidence_req_0_booking_only():
    """req=0：仅 booking 在 → evidence 算填齐。"""
    from bot.keyboards.user_kb import _card_field_filled, _CARD_FIELDS
    evidence = _CARD_FIELDS[0]
    data = {"request_reimbursement": 0, "booking_screenshot_file_id": "f1"}
    assert _card_field_filled(data, evidence) is True


def test_card_field_filled_evidence_req_1_needs_both():
    """req=1：仅 booking 在 → evidence 未填齐。"""
    from bot.keyboards.user_kb import _card_field_filled, _CARD_FIELDS
    evidence = _CARD_FIELDS[0]
    data = {"request_reimbursement": 1, "booking_screenshot_file_id": "f1"}
    assert _card_field_filled(data, evidence) is False
    data["gesture_photo_file_id"] = "f2"
    assert _card_field_filled(data, evidence) is True


# ============================================================
# 5. create_teacher_review 允许 gesture=None
# ============================================================


async def _insert_teacher(uid=100):
    from bot.database import get_db
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO teachers
               (user_id, username, display_name, region, price, tags, button_url)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (uid, "u", "T", "成都", "1000P", "[]", "https://t.me/x"),
        )
        await db.commit()
    finally:
        await db.close()


def _base_review_data(teacher_id: int, user_id: int = 1001) -> dict:
    return {
        "teacher_id": teacher_id,
        "user_id": user_id,
        "booking_screenshot_file_id": "f_booking",
        # gesture_photo_file_id 故意不传
        "rating": "good",
        "score_humanphoto": 8, "score_appearance": 8, "score_body": 8,
        "score_service": 8, "score_attitude": 8, "score_environment": 8,
        "overall_score": 8.0,
        "summary": "ok",
        "request_reimbursement": 0,
        "anonymous": 0,
    }


def test_create_teacher_review_accepts_none_gesture(temp_db):
    """req=0 路径，gesture_photo_file_id 不传（即 None）→ 仍可落库。"""
    from bot.database import create_teacher_review, get_teacher_review
    _run(_insert_teacher(100))
    data = _base_review_data(100)
    review_id = _run(create_teacher_review(data))
    assert review_id is not None
    row = _run(get_teacher_review(review_id))
    assert row is not None
    assert row["gesture_photo_file_id"] is None
    assert row["request_reimbursement"] == 0


def test_create_teacher_review_explicit_none_gesture(temp_db):
    """显式传 gesture_photo_file_id=None 也 OK。"""
    from bot.database import create_teacher_review, get_teacher_review
    _run(_insert_teacher(100))
    data = _base_review_data(100)
    data["gesture_photo_file_id"] = None
    review_id = _run(create_teacher_review(data))
    assert review_id is not None
    row = _run(get_teacher_review(review_id))
    assert row["gesture_photo_file_id"] is None


def test_create_teacher_review_with_gesture_still_works(temp_db):
    """req=1 路径（gesture 有值）也应正常落库。"""
    from bot.database import create_teacher_review, get_teacher_review
    _run(_insert_teacher(100))
    data = _base_review_data(100)
    data["gesture_photo_file_id"] = "f_gesture"
    data["request_reimbursement"] = 1
    review_id = _run(create_teacher_review(data))
    assert review_id is not None
    row = _run(get_teacher_review(review_id))
    assert row["gesture_photo_file_id"] == "f_gesture"


def test_create_teacher_review_still_rejects_missing_booking(temp_db):
    """booking_screenshot_file_id 仍是必填——不允许 None。"""
    from bot.database import create_teacher_review
    _run(_insert_teacher(100))
    data = _base_review_data(100)
    data["booking_screenshot_file_id"] = None
    review_id = _run(create_teacher_review(data))
    assert review_id is None


# ============================================================
# 6. Schema：gesture_photo_file_id 已可空
# ============================================================


def test_teacher_reviews_gesture_column_is_nullable(temp_db):
    """init_db 后 PRAGMA table_info 应显示 gesture_photo_file_id notnull=0。"""
    from bot.database import get_db
    async def _check():
        db = await get_db()
        try:
            cur = await db.execute("PRAGMA table_info(teacher_reviews)")
            rows = await cur.fetchall()
            for r in rows:
                if r[1] == "gesture_photo_file_id":
                    # row[3] 是 notnull 列（0 = 允许 NULL）
                    return int(r[3])
            return None
        finally:
            await db.close()
    notnull = _run(_check())
    assert notnull == 0, (
        f"gesture_photo_file_id 应可空（notnull=0），实际 notnull={notnull}"
    )
