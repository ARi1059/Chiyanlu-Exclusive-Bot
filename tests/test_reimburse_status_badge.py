"""Sprint UX-8 第二项（UX-8.2）：报销详情决策色块 + 用户月度池预警契约测试。

范围：
    - bot.handlers.admin_reimburse._render_reimbursement_detail
      顶部新增决策色块（✅可批 / ⚠️需消耗 voucher / 🛑超月池 / 🛑周配额满）
    - bot.handlers.user_reimburse.cb_user_reimburse 报销总览页
      月度池剩余 < 100 元时显示 ⚠️ 即将耗尽预警

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §4.2 痛点 5/10 + §11.3）：
    - 超管审核详情页 13 行同字号文本，"本周已批 / 月池剩余"等决策信息被无关字段
      挤在中部；详情顶部色块让一眼可读决策状态。
    - 用户在总览页看不到月度池剩余金额，无法主动错峰申请；剩余 < 100 时预警。

约束：
    - 仅 pending 状态显示决策色块；已 approved/rejected/cancelled 的不显示
    - 不改 callback_data / FSM / 提交业务
    - 月度池预警阈值固定 100 元（与文档 §11.3 范围一致）
    - 不引入 schema 迁移
"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


# ============ helpers ============


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_badge_{uuid.uuid4().hex}_", suffix=".db",
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


def _src(module) -> str:
    return inspect.getsource(module)


# ============================================================
# 1. admin_reimburse 详情色块（静态契约）
# ============================================================


def test_detail_has_pending_only_badge_logic():
    """详情渲染应仅在 pending 状态计算 badge_line。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def _render_reimbursement_detail(")
    end = src.find("\n\n\n", idx) if src.find("\n\n\n", idx) > 0 else idx + 4000
    body = src[idx:end]
    # 必须有 reimb["status"] == "pending" 判断
    assert 'reimb["status"] == "pending"' in body
    # 四类 badge 都应出现
    assert "🛑 超月池" in body
    assert "⚠️ 需消耗 voucher" in body
    assert "🛑 周配额已满" in body
    assert "✅ 可批" in body


def test_detail_badge_inserted_after_title_before_separator():
    """badge_line 应插在标题与第一条分隔线之间（视觉头部）。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    idx = src.find("async def _render_reimbursement_detail(")
    end = src.find("\n\n\n", idx) if src.find("\n\n\n", idx) > 0 else idx + 4000
    body = src[idx:end]
    # "💰 报销申请 #" 出现后，紧跟 if badge_line; 之后才是 ━ 分隔线
    title_pos = body.find('"💰 报销申请 #')
    badge_pos = body.find("if badge_line")
    sep_pos = body.find('━━━━━━━━━━━━━━━')
    assert 0 < title_pos < badge_pos < sep_pos


# ============================================================
# 2. admin_reimburse 详情色块（端到端：build & verify）
# ============================================================


async def _ensure_teacher(teacher_id: int = 99) -> None:
    """确保 teachers 表里有该 teacher（避免 FK 阻塞）。"""
    from bot.database import get_db
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO teachers
               (user_id, username, display_name, region, price, tags, button_url)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (teacher_id, f"t{teacher_id}", "测试老师", "北京", "300", "[]", "https://t.me/x"),
        )
        await db.commit()
    finally:
        await db.close()


async def _ensure_review(review_id: int, *, teacher_id: int = 99, user_id: int = 1001) -> None:
    """确保 teacher_reviews 表里有该 review（避免 FK 阻塞）。"""
    from bot.database import get_db
    await _ensure_teacher(teacher_id)
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO teacher_reviews
               (id, teacher_id, user_id,
                booking_screenshot_file_id, gesture_photo_file_id,
                rating,
                score_humanphoto, score_appearance, score_body,
                score_service, score_attitude, score_environment,
                overall_score, summary, status)
               VALUES (?, ?, ?, 'a', 'b', 'positive',
                       9, 9, 9, 9, 9, 9, 9, 'ok', 'approved')""",
            (review_id, teacher_id, user_id),
        )
        await db.commit()
    finally:
        await db.close()


_review_id_counter: dict[str, int] = {"next": 1}


async def _make_reimbursement(
    *, status="pending", amount=80, user_id=1001, teacher_id=99,
    week_key="2026-21", month_key="2026-05",
) -> int:
    """便利：插入一条 reimbursement，自动准备 teacher + review 满足 FK。"""
    from bot.database import get_db

    # 每次自动用一个新 review_id（UNIQUE 约束）
    review_id = _review_id_counter["next"]
    _review_id_counter["next"] += 1
    await _ensure_review(review_id, teacher_id=teacher_id, user_id=user_id)

    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO reimbursements
               (review_id, user_id, teacher_id, amount, status,
                week_key, month_key)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (review_id, user_id, teacher_id, amount, status, week_key, month_key),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


def test_detail_renders_ok_badge_when_pool_and_week_clean(temp_db):
    from bot.database import get_reimbursement, set_config
    from bot.handlers.admin_reimburse import _render_reimbursement_detail

    rid = _run(_make_reimbursement(amount=80))
    _run(set_config("reimbursement_monthly_pool", "1000"))
    reimb = _run(get_reimbursement(rid))
    text = _run(_render_reimbursement_detail(reimb))
    assert "✅ 可批" in text


def test_detail_renders_over_pool_badge(temp_db):
    """月池剩余 50，本次需要 80 → 🛑 超月池。"""
    from bot.database import get_reimbursement, set_config
    from bot.handlers.admin_reimburse import _render_reimbursement_detail

    # 已用 950 → 剩 50；本条 80 > 50
    _run(set_config("reimbursement_monthly_pool", "1000"))
    # 插入一条已 approved 凑出"已用 950"
    _run(_make_reimbursement(
        status="approved", amount=950, user_id=9001,
        week_key="2026-20", month_key="2026-05",
    ))
    rid = _run(_make_reimbursement(amount=80))
    reimb = _run(get_reimbursement(rid))
    text = _run(_render_reimbursement_detail(reimb))
    assert "🛑 超月池" in text


def test_detail_renders_week_full_no_voucher_badge(temp_db):
    """同用户本周已批 1 次 + 无 voucher → 🛑 周配额已满。"""
    from bot.database import get_reimbursement
    from bot.handlers.admin_reimburse import _render_reimbursement_detail

    user = 1001
    week_key = "2026-21"
    _run(_make_reimbursement(
        status="approved", amount=80, user_id=user, week_key=week_key,
    ))
    rid = _run(_make_reimbursement(
        status="pending", amount=80, user_id=user, week_key=week_key,
    ))
    reimb = _run(get_reimbursement(rid))
    text = _run(_render_reimbursement_detail(reimb))
    assert "🛑 周配额已满" in text


def test_detail_renders_voucher_badge_when_reset_available(temp_db):
    """同用户本周已批 1 次 + 持有 voucher → ⚠️ 需消耗 voucher。"""
    from bot.database import (
        get_reimbursement, grant_reimbursement_reset,
    )
    from bot.handlers.admin_reimburse import _render_reimbursement_detail

    user = 1001
    week_key = "2026-21"
    _run(_make_reimbursement(
        status="approved", amount=80, user_id=user, week_key=week_key,
    ))
    # 授予 voucher
    _run(grant_reimbursement_reset(user, admin_id=999))
    rid = _run(_make_reimbursement(
        status="pending", amount=80, user_id=user, week_key=week_key,
    ))
    reimb = _run(get_reimbursement(rid))
    text = _run(_render_reimbursement_detail(reimb))
    assert "⚠️ 需消耗 voucher" in text


def test_detail_no_badge_for_approved_status(temp_db):
    """status='approved' 时不应有任何决策色块（已审完不需要提示）。"""
    from bot.database import get_reimbursement
    from bot.handlers.admin_reimburse import _render_reimbursement_detail

    rid = _run(_make_reimbursement(status="approved"))
    reimb = _run(get_reimbursement(rid))
    text = _run(_render_reimbursement_detail(reimb))
    assert "🛑 超月池" not in text
    assert "⚠️ 需消耗 voucher" not in text
    assert "🛑 周配额已满" not in text
    assert "✅ 可批" not in text


def test_detail_no_badge_for_rejected_status(temp_db):
    from bot.database import get_reimbursement
    from bot.handlers.admin_reimburse import _render_reimbursement_detail

    rid = _run(_make_reimbursement(status="rejected"))
    reimb = _run(get_reimbursement(rid))
    text = _run(_render_reimbursement_detail(reimb))
    assert "✅ 可批" not in text
    assert "🛑" not in text or "🛑 超月池" not in text


# ============================================================
# 3. user_reimburse 月度池预警
# ============================================================


def test_user_overview_no_warning_when_pool_unset(temp_db):
    """池未配置 → 显示"池不限"，不应有 ⚠️。"""
    from bot.handlers.user_reimburse import cb_user_reimburse

    cb = MagicMock()
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.message.answer = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    _run(cb_user_reimburse(cb))
    text = cb.message.edit_text.await_args.args[0]
    assert "池不限" in text
    assert "⚠️ 即将耗尽" not in text


def test_user_overview_shows_remaining_when_pool_set(temp_db):
    """池配置后显示"剩余 N 元"。"""
    from bot.database import set_config
    from bot.handlers.user_reimburse import cb_user_reimburse

    _run(set_config("reimbursement_monthly_pool", "1000"))
    cb = MagicMock()
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    _run(cb_user_reimburse(cb))
    text = cb.message.edit_text.await_args.args[0]
    # 池 1000 + 月已用 0 → 剩 1000
    assert "池 1000 元" in text
    assert "剩 1000 元" in text


def test_user_overview_warns_when_remaining_below_100(temp_db):
    """剩余 < 100 元时显示 ⚠️ 即将耗尽。"""
    from bot.database import set_config
    from bot.handlers.user_reimburse import cb_user_reimburse

    _run(set_config("reimbursement_monthly_pool", "1000"))
    # 已用 950 → 剩 50（< 100）
    _run(_make_reimbursement(
        status="approved", amount=950, user_id=9001,
        week_key="2026-20", month_key="2026-05",
    ))
    cb = MagicMock()
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    _run(cb_user_reimburse(cb))
    text = cb.message.edit_text.await_args.args[0]
    assert "⚠️ 即将耗尽" in text


def test_user_overview_no_warning_when_remaining_at_or_above_100(temp_db):
    """剩余 = 100 元时仍**不**显示预警（严格 < 100）。"""
    from bot.database import set_config
    from bot.handlers.user_reimburse import cb_user_reimburse

    _run(set_config("reimbursement_monthly_pool", "1000"))
    _run(_make_reimbursement(
        status="approved", amount=900, user_id=9001,
        week_key="2026-20", month_key="2026-05",
    ))
    cb = MagicMock()
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    _run(cb_user_reimburse(cb))
    text = cb.message.edit_text.await_args.args[0]
    assert "⚠️ 即将耗尽" not in text


def test_user_overview_handles_over_used_pool_gracefully(temp_db):
    """已用 > 池（极端情况）：剩余应 max(0, ...)，不应显示负数。"""
    from bot.database import set_config
    from bot.handlers.user_reimburse import cb_user_reimburse

    _run(set_config("reimbursement_monthly_pool", "100"))
    _run(_make_reimbursement(
        status="approved", amount=150, user_id=9001,
        week_key="2026-20", month_key="2026-05",
    ))
    cb = MagicMock()
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    _run(cb_user_reimburse(cb))
    text = cb.message.edit_text.await_args.args[0]
    # 不应出现 "剩 -50 元" 之类
    assert "剩 -" not in text
    # 应是 "剩 0 元"
    assert "剩 0 元" in text


# ============================================================
# 4. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states"}
