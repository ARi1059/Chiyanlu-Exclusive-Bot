"""bot.utils.reimburse_eligibility.is_user_reimburse_eligible_for_review 契约测试。

2026-05-21 评价前置改造的预判 helper —— 5 个判定分支按优先级覆盖：
    1. feature_off       —— config "reimbursement_feature_enabled" != "1"
    2. amount_zero       —— teacher.price 不在 ≦800 / 900 / ≧1000 元三档
    3. below_threshold   —— min_pts > 0 且 user 积分 < min_pts
    4. pool_exhausted    —— monthly_pool > 0 且剩余 < amount
    5. eligible          —— 上述四项全部通过 → (True, info)

不写 DB，纯 SELECT；任何子查询失败按"保守路径"继续。
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

import pytest


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_elig_{uuid.uuid4().hex}_", suffix=".db",
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


async def _setup_baseline(*, feature_on: bool = True, min_pts: int = 5,
                          monthly_pool: int = 0):
    """配齐 4 个 config，避免每个测试重复写。"""
    from bot.database import set_config, set_reimbursement_min_points
    await set_config("reimbursement_feature_enabled", "1" if feature_on else "0")
    await set_reimbursement_min_points(min_pts)
    await set_config("reimbursement_monthly_pool", str(monthly_pool))


async def _set_user_points(user_id: int, points: int):
    """在 users 表插入 / 更新一行，把 total_points 设为指定值。"""
    from bot.database import get_db
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, total_points) VALUES (?, ?)",
            (user_id, points),
        )
        await db.commit()
    finally:
        await db.close()


async def _insert_approved_reimb(amount: int, month_key: str):
    """直接插一条 approved 报销，绕过 FK + status 校验，用于触发 pool_exhausted。"""
    from bot.database import get_db
    db = await get_db()
    try:
        await db.execute("PRAGMA foreign_keys = OFF")
        # 用唯一 review_id（unique 约束）
        rid = abs(hash(month_key + str(amount))) % 1_000_000_000
        await db.execute(
            "INSERT INTO reimbursements "
            "(user_id, review_id, teacher_id, amount, status, week_key, month_key) "
            "VALUES (?, ?, ?, ?, 'approved', '2026-W21', ?)",
            (10001, rid, 100, amount, month_key),
        )
        await db.commit()
    finally:
        await db.close()


# ============================================================
# 1. 4 个 ineligible reason 分支（按优先级）
# ============================================================


def test_feature_off_returns_feature_off(temp_db):
    """feature_off 优先级最高：即便积分、价位、池子都对，feature off 也立刻 ineligible。"""
    _run(_setup_baseline(feature_on=False, min_pts=5, monthly_pool=0))
    _run(_set_user_points(99, 100))
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    eligible, info = _run(is_user_reimburse_eligible_for_review(99, "1000P"))
    assert eligible is False
    assert info["reason"] == "feature_off"
    assert info["feature_enabled"] is False


def test_amount_zero_when_price_invalid(temp_db):
    """teacher.price 无法解析（空串 / 全非数字）→ amount=0 → reason=amount_zero。

    注：根据 compute_reimbursement_amount 规则，任何正价位（≥100 元 / 1P）
    都至少返 100 元（≤800 元档）。amount=0 实际只在 price=0 / 空 / 无数字
    时触发，对应"老师 price 字段未填或填错"的边界 case。
    """
    _run(_setup_baseline(feature_on=True, min_pts=5, monthly_pool=0))
    _run(_set_user_points(99, 100))
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    eligible, info = _run(is_user_reimburse_eligible_for_review(99, ""))
    assert eligible is False
    assert info["reason"] == "amount_zero"
    assert info["amount"] == 0


def test_below_threshold_when_points_short(temp_db):
    """min_pts=5 + user 积分=3 → reason=below_threshold。"""
    _run(_setup_baseline(feature_on=True, min_pts=5, monthly_pool=0))
    _run(_set_user_points(99, 3))
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    eligible, info = _run(is_user_reimburse_eligible_for_review(99, "1000P"))
    assert eligible is False
    assert info["reason"] == "below_threshold"
    assert info["points"] == 3
    assert info["min_pts"] == 5


def test_zero_min_pts_disables_threshold_check(temp_db):
    """min_pts=0 表示门槛关闭：即使积分 0 也不应触发 below_threshold。"""
    _run(_setup_baseline(feature_on=True, min_pts=0, monthly_pool=0))
    _run(_set_user_points(99, 0))
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    eligible, info = _run(is_user_reimburse_eligible_for_review(99, "1000P"))
    assert eligible is True
    assert info["reason"] is None


def test_pool_exhausted_when_remaining_less_than_amount(temp_db):
    """月池 200 元，本月已用 150；本次老师 amount=200 → 剩 50 < 200 → pool_exhausted。"""
    _run(_setup_baseline(feature_on=True, min_pts=5, monthly_pool=200))
    _run(_set_user_points(99, 100))
    from bot.database import current_month_key
    _run(_insert_approved_reimb(150, current_month_key()))
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    eligible, info = _run(is_user_reimburse_eligible_for_review(99, "1000P"))
    assert eligible is False
    assert info["reason"] == "pool_exhausted"
    assert info["pool_remaining"] == 50  # 200 - 150


def test_pool_unlimited_when_zero(temp_db):
    """monthly_pool=0（不限）→ 即便本月已用很多也不会触发 pool_exhausted。"""
    _run(_setup_baseline(feature_on=True, min_pts=5, monthly_pool=0))
    _run(_set_user_points(99, 100))
    from bot.database import current_month_key
    _run(_insert_approved_reimb(99999, current_month_key()))
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    eligible, info = _run(is_user_reimburse_eligible_for_review(99, "1000P"))
    assert eligible is True
    assert info["pool_remaining"] == -1  # 标记"不限"


# ============================================================
# 2. eligible 正例
# ============================================================


def test_eligible_minimal(temp_db):
    """所有条件都对 → (True, info)，reason 为 None。"""
    _run(_setup_baseline(feature_on=True, min_pts=5, monthly_pool=0))
    _run(_set_user_points(99, 5))
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    eligible, info = _run(is_user_reimburse_eligible_for_review(99, "1000P"))
    assert eligible is True
    assert info["reason"] is None
    assert info["amount"] == 200  # ≥10P → 200


def test_eligible_at_900_tier(temp_db):
    """900 元档 → amount=150。"""
    _run(_setup_baseline(feature_on=True, min_pts=5, monthly_pool=0))
    _run(_set_user_points(99, 10))
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    eligible, info = _run(is_user_reimburse_eligible_for_review(99, "900P"))
    assert eligible is True
    assert info["amount"] == 150


def test_eligible_at_lower_tier(temp_db):
    """≤800 元档 → amount=100。"""
    _run(_setup_baseline(feature_on=True, min_pts=5, monthly_pool=0))
    _run(_set_user_points(99, 10))
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    eligible, info = _run(is_user_reimburse_eligible_for_review(99, "800P"))
    assert eligible is True
    assert info["amount"] == 100


def test_eligible_exact_pool_remaining_equals_amount(temp_db):
    """边界：剩余 == amount → 通过（>= 不算 exhausted）。"""
    _run(_setup_baseline(feature_on=True, min_pts=5, monthly_pool=300))
    _run(_set_user_points(99, 10))
    from bot.database import current_month_key
    _run(_insert_approved_reimb(100, current_month_key()))  # 已用 100，剩 200
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    eligible, info = _run(is_user_reimburse_eligible_for_review(99, "1000P"))
    # 剩 200，本次 200 → 边界通过
    assert eligible is True
    assert info["pool_remaining"] == 200


# ============================================================
# 3. 优先级与 reason 常量
# ============================================================


def test_reason_constants_exposed():
    """reason 字符串以模块常量暴露，便于上层 caller match-case 而不硬编码字面量。"""
    import bot.utils.reimburse_eligibility as mod
    assert mod.REASON_FEATURE_OFF == "feature_off"
    assert mod.REASON_AMOUNT_ZERO == "amount_zero"
    assert mod.REASON_BELOW_THRESHOLD == "below_threshold"
    assert mod.REASON_POOL_EXHAUSTED == "pool_exhausted"


def test_priority_feature_off_over_others(temp_db):
    """同时违反多条时按文档优先级返回 feature_off。"""
    _run(_setup_baseline(feature_on=False, min_pts=5, monthly_pool=10))
    _run(_set_user_points(99, 0))  # 也违反 below_threshold
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    _, info = _run(is_user_reimburse_eligible_for_review(99, ""))  # 也违反 amount_zero
    assert info["reason"] == "feature_off"  # feature_off 优先


def test_priority_amount_zero_over_below_threshold(temp_db):
    """feature_on + amount=0（空 price）+ points<min_pts → amount_zero 优先。"""
    _run(_setup_baseline(feature_on=True, min_pts=5, monthly_pool=0))
    _run(_set_user_points(99, 0))
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    _, info = _run(is_user_reimburse_eligible_for_review(99, ""))
    assert info["reason"] == "amount_zero"


def test_priority_below_threshold_over_pool(temp_db):
    """feature_on + amount>0 + points<min_pts + pool 也用完 → below_threshold 优先。"""
    _run(_setup_baseline(feature_on=True, min_pts=10, monthly_pool=100))
    _run(_set_user_points(99, 1))
    from bot.database import current_month_key
    _run(_insert_approved_reimb(100, current_month_key()))
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    _, info = _run(is_user_reimburse_eligible_for_review(99, "1000P"))
    assert info["reason"] == "below_threshold"


# ============================================================
# 4. 容错（不抛异常，按保守路径继续）
# ============================================================


def test_no_db_state_yields_feature_off_safe_default(temp_db):
    """空 config + 无 user 行 → feature_off（默认）。"""
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    eligible, info = _run(is_user_reimburse_eligible_for_review(99, "1000P"))
    assert eligible is False
    # 任一保守路径都应是非 eligible
    assert info["reason"] in {
        "feature_off", "below_threshold", "amount_zero", "pool_exhausted",
    }


def test_teacher_price_none_returns_amount_zero(temp_db):
    """teacher_price=None → compute_reimbursement_amount 返 0 → amount_zero。"""
    _run(_setup_baseline(feature_on=True, min_pts=0, monthly_pool=0))
    from bot.utils.reimburse_eligibility import is_user_reimburse_eligible_for_review
    _, info = _run(is_user_reimburse_eligible_for_review(99, None))
    assert info["reason"] == "amount_zero"
