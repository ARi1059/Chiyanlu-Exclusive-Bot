"""报销门槛 + 本月报销池手动重置 - 完整契约测试（2026-05）。

覆盖 spec §10 测试要求 1-38：
    报销门槛配置 (1-10)
    报销门槛生效 (11-16)
    本月报销池重置 (17-27)
    审批一致性 (28-31)
    隔离性 (32-38)
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import tempfile
import uuid

import pytest


# ============ helpers ============


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_reimset_{uuid.uuid4().hex}_", suffix=".db",
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


def _cbs(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


_reimb_review_id_seq = 100000


async def _insert_approved_reimb(amount: int, month_key: str):
    """便利函数：在 temp_db 里插入一条 approved 报销记录。

    review_id 有 FK 到 teacher_reviews(id)；测试中临时关闭 FK 直接 INSERT。
    每次调用使用递增 review_id 保证 UNIQUE。
    """
    global _reimb_review_id_seq
    _reimb_review_id_seq += 1
    review_id = _reimb_review_id_seq
    from bot.database import get_db
    db = await get_db()
    try:
        await db.execute("PRAGMA foreign_keys = OFF")
        await db.execute(
            "INSERT INTO reimbursements "
            "(user_id, review_id, teacher_id, amount, status, week_key, month_key) "
            "VALUES (?, ?, ?, ?, 'approved', '2026-W21', ?)",
            (10001, review_id, 100, amount, month_key),
        )
        await db.commit()
    finally:
        await db.close()


# ============================================================
# 1-10. 报销门槛配置
# ============================================================


def test_reimburse_min_points_default_is_5(temp_db):
    """无 config 时默认 5（与既有 fallback 一致）。"""
    from bot.database import get_reimbursement_min_points, REIMBURSE_MIN_POINTS_DEFAULT
    assert REIMBURSE_MIN_POINTS_DEFAULT == 5
    assert _run(get_reimbursement_min_points()) == 5


def test_reimburse_min_points_zero_is_legal(temp_db):
    """0 表示不启用门槛——合法值。"""
    from bot.database import (
        set_reimbursement_min_points, get_reimbursement_min_points,
    )
    _run(set_reimbursement_min_points(0))
    assert _run(get_reimbursement_min_points()) == 0


def test_set_reimburse_min_points_negative_rejected(temp_db):
    """负数拒绝（ValueError）。"""
    from bot.database import set_reimbursement_min_points
    with pytest.raises(ValueError):
        _run(set_reimbursement_min_points(-1))


def test_set_reimburse_min_points_over_max_rejected(temp_db):
    """超上限拒绝。"""
    from bot.database import set_reimbursement_min_points, REIMBURSE_MIN_POINTS_MAX
    with pytest.raises(ValueError):
        _run(set_reimbursement_min_points(REIMBURSE_MIN_POINTS_MAX + 1))


def test_get_reimburse_min_points_safe_on_invalid_value(temp_db):
    """config value 非整数 / 越界 → 回落默认 5。"""
    from bot.database import set_config, get_reimbursement_min_points
    _run(set_config("reimbursement_min_points", "abc"))
    assert _run(get_reimbursement_min_points()) == 5
    _run(set_config("reimbursement_min_points", "999"))  # 越界
    assert _run(get_reimbursement_min_points()) == 5
    _run(set_config("reimbursement_min_points", "-3"))  # 负数
    assert _run(get_reimbursement_min_points()) == 5


def test_set_then_get_reimburse_min_points_roundtrip(temp_db):
    from bot.database import set_reimbursement_min_points, get_reimbursement_min_points
    for v in (0, 3, 10, 50, 100):
        _run(set_reimbursement_min_points(v))
        assert _run(get_reimbursement_min_points()) == v


def test_min_points_admin_handlers_use_super_admin_required():
    """4 个 min_points handler 都用 _super_admin_required。"""
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    for fn in (
        "cb_min_points_menu",
        "cb_min_points_edit",
        "step_min_points_value",
        "cb_min_points_confirm",
    ):
        idx = src.find(f"async def {fn}(")
        assert idx > 0, f"找不到 {fn}"
        window = src[max(0, idx - 300):idx]
        assert "@_super_admin_required" in window


def test_min_points_callbacks_present_in_module():
    """4 个 callback 字面量都在模块中。"""
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    assert '"system:reimburse_min_points"' in src
    assert '"system:reimburse_min_points:edit"' in src
    assert '"system:reimburse_min_points:confirm"' in src


def test_min_points_audit_log_on_confirm():
    """确认修改后必须写 log_admin_audit。"""
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    idx = src.find("async def cb_min_points_confirm(")
    assert idx > 0
    body = src[idx:idx + 2500]
    assert "log_admin_audit" in body
    assert "reimburse_min_points_set" in body


def test_admin_reimburse_config_kb_contains_min_points_entry():
    """2026-05-20：5 项报销直入口已从 menu:system 迁到 admin:reimburse_config
    聚合页，避免与聚合页重复。本测试改为校验聚合页含 🎚 报销门槛设置入口。"""
    from bot.keyboards.admin_kb import admin_reimburse_config_kb
    cbs = _cbs(admin_reimburse_config_kb())
    assert "system:reimburse_min_points" in cbs


# ============================================================
# 11-16. 报销门槛生效
# ============================================================


def test_review_card_uses_get_reimbursement_min_points_helper():
    """2026-05-21：review_card 不再直接调 get_reimbursement_min_points
    （前置预判已封装到 is_user_reimburse_eligible_for_review，由 eligibility
    helper 调用 get_reimbursement_min_points）。本测试改为校验：
      - review_card 不内联 get_config('reimbursement_min_points')
      - eligibility helper 仍正确使用门槛 helper
    """
    import bot.handlers.review_card as mod
    import bot.utils.reimburse_eligibility as elig
    rc_src = _src(mod)
    elig_src = _src(elig)
    # review_card 不应再直接 inline 读 config key
    assert "min_pts_raw = await get_config" not in rc_src
    assert 'get_config("reimbursement_min_points"' not in rc_src
    # eligibility helper 必须用 helper（不内联 SQL）
    assert "get_reimbursement_min_points" in elig_src


def test_rreview_admin_uses_get_reimbursement_min_points_helper():
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    assert "get_reimbursement_min_points" in src
    assert "min_pts_raw = await get_config" not in src


# 注：旧 test_review_submit_uses_get_reimbursement_min_points_helper +
# test_review_submit_gates_zero_threshold_passes 已于 Sprint 7 §9.1
# 第 3 批 ReviewSubmitStates 删除中清理（review_submit.py 不再含报销
# gate 逻辑）。等价契约由 review_card / rreview_admin 路径覆盖。


def test_review_card_gates_zero_threshold_passes():
    """2026-05-21：min_pts > 0 判定已搬到 is_user_reimburse_eligible_for_review。
    review_card 通过该 helper 间接做 zero-threshold 放行；本测试改为校验
    helper 中包含正确的 zero-threshold 判定形式。"""
    import bot.utils.reimburse_eligibility as mod
    src = _src(mod)
    # zero-threshold（min_pts == 0）应不阻止 eligibility 通过：
    # 实现形式应是 `if min_pts > 0 and points < min_pts:` 才视为不通过
    assert "min_pts > 0" in src and "points < min_pts" in src


def test_rreview_admin_gates_zero_threshold_passes():
    """rreview_admin 应允许 min_pts=0 通过。"""
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    # 形式应是 `min_pts == 0 or effective_pts >= min_pts`
    assert "min_pts == 0" in src


# ============================================================
# 17-21. 本月报销池 reset baseline 逻辑
# ============================================================


def test_reset_baseline_uses_correct_config_key():
    from bot.database import REIMBURSE_POOL_RESET_BASELINES_KEY
    assert REIMBURSE_POOL_RESET_BASELINES_KEY == "reimbursement_monthly_pool_reset_baselines"


def test_get_reimburse_pool_reset_baselines_empty_default(temp_db):
    """无 config → 空 dict。"""
    from bot.database import get_reimburse_pool_reset_baselines
    assert _run(get_reimburse_pool_reset_baselines()) == {}


def test_get_reimburse_pool_reset_baselines_safe_on_invalid_json(temp_db):
    """JSON 异常 → 空 dict。"""
    from bot.database import set_config, get_reimburse_pool_reset_baselines
    _run(set_config("reimbursement_monthly_pool_reset_baselines", "not json"))
    assert _run(get_reimburse_pool_reset_baselines()) == {}


def test_set_reset_baseline_writes_to_config(temp_db):
    from bot.database import (
        set_reimburse_pool_reset_baseline,
        get_reimburse_pool_reset_baselines,
        get_config,
    )
    entry = _run(set_reimburse_pool_reset_baseline(
        month_key="2026-05",
        baseline_amount=1200,
        admin_id=123,
        reason="月池追加预算",
    ))
    assert entry["baseline_amount"] == 1200
    assert entry["admin_id"] == 123
    assert entry["reason"] == "月池追加预算"
    assert entry["reset_at"]  # 非空
    # 通过 get helper 读回
    all_baselines = _run(get_reimburse_pool_reset_baselines())
    assert "2026-05" in all_baselines
    assert all_baselines["2026-05"]["baseline_amount"] == 1200


def test_pool_usage_with_no_reset(temp_db):
    """无 reset → effective_used = raw_used。"""
    from bot.database import get_reimbursement_monthly_pool_usage
    _run(_insert_approved_reimb(500, "2026-05"))
    _run(_insert_approved_reimb(700, "2026-05"))
    usage = _run(get_reimbursement_monthly_pool_usage("2026-05"))
    assert usage["raw_used"] == 1200
    assert usage["reset_baseline"] == 0
    assert usage["effective_used"] == 1200


def test_pool_usage_after_reset(temp_db):
    """reset 后 effective_used = raw_used - baseline。"""
    from bot.database import (
        get_reimbursement_monthly_pool_usage,
        set_reimburse_pool_reset_baseline,
    )
    _run(_insert_approved_reimb(1200, "2026-05"))
    # 重置 baseline = 1200
    _run(set_reimburse_pool_reset_baseline(
        month_key="2026-05", baseline_amount=1200, admin_id=1, reason="reset",
    ))
    usage = _run(get_reimbursement_monthly_pool_usage("2026-05"))
    assert usage["raw_used"] == 1200
    assert usage["reset_baseline"] == 1200
    assert usage["effective_used"] == 0
    # 之后新增 500 → effective_used = 500
    _run(_insert_approved_reimb(500, "2026-05"))
    usage2 = _run(get_reimbursement_monthly_pool_usage("2026-05"))
    assert usage2["raw_used"] == 1700
    assert usage2["effective_used"] == 500


def test_reset_does_not_modify_reimbursements_table(temp_db):
    """reset 操作只动 config，不删 / 不改 reimbursements 历史记录。"""
    from bot.database import get_db, set_reimburse_pool_reset_baseline

    async def count_rows():
        d = await get_db()
        try:
            cur = await d.execute(
                "SELECT COUNT(*) FROM reimbursements "
                "WHERE month_key='2026-05' AND status='approved'"
            )
            row = await cur.fetchone()
            return int(row[0])
        finally:
            await d.close()

    _run(_insert_approved_reimb(800, "2026-05"))
    before = _run(count_rows())
    _run(set_reimburse_pool_reset_baseline(
        month_key="2026-05", baseline_amount=800, admin_id=1, reason="r",
    ))
    after = _run(count_rows())
    assert before == after == 1  # 行数未变


def test_reset_next_month_unaffected_by_this_month_reset(temp_db):
    """下个月不受本月 reset 影响。"""
    from bot.database import (
        get_reimbursement_monthly_pool_usage,
        set_reimburse_pool_reset_baseline,
    )
    _run(_insert_approved_reimb(1000, "2026-05"))
    _run(_insert_approved_reimb(300, "2026-06"))
    _run(set_reimburse_pool_reset_baseline(
        month_key="2026-05", baseline_amount=1000, admin_id=1, reason="r",
    ))
    # 5 月有效用量 = 0
    u5 = _run(get_reimbursement_monthly_pool_usage("2026-05"))
    assert u5["effective_used"] == 0
    # 6 月不受影响
    u6 = _run(get_reimbursement_monthly_pool_usage("2026-06"))
    assert u6["raw_used"] == 300
    assert u6["reset_baseline"] == 0
    assert u6["effective_used"] == 300


# ============================================================
# 22-27. 重置 handler 行为 + 权限 + 入口
# ============================================================


def test_pool_reset_handlers_use_super_admin_required():
    """3 个 pool_reset handler 都用 _super_admin_required。"""
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    for fn in (
        "cb_pool_reset_menu",
        "step_pool_reset_reason",
        "cb_pool_reset_confirm",
    ):
        idx = src.find(f"async def {fn}(")
        assert idx > 0
        window = src[max(0, idx - 300):idx]
        assert "@_super_admin_required" in window


def test_pool_reset_callbacks_present():
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    assert '"system:reimburse_pool_reset"' in src
    assert '"system:reimburse_pool_reset:confirm"' in src


def test_pool_reset_writes_audit_log_on_confirm():
    """重置确认必须写 log_admin_audit。"""
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    idx = src.find("async def cb_pool_reset_confirm(")
    assert idx > 0
    body = src[idx:idx + 3000]
    assert "log_admin_audit" in body
    assert "reimburse_pool_reset" in body


def test_pool_reset_requires_reason_static():
    """step_pool_reset_reason 必须校验空原因。"""
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    idx = src.find("async def step_pool_reset_reason(")
    assert idx > 0
    body = src[idx:idx + 2000]
    assert "不能为空" in body


def test_pool_reset_has_two_step_confirmation():
    """流程：waiting_reason → confirming → confirm callback。"""
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    assert "ReimbursePoolResetStates.waiting_reason" in src
    assert "ReimbursePoolResetStates.confirming" in src


def test_admin_reimburse_config_kb_contains_pool_reset_entry():
    """2026-05-20：本批次起，入口源在 admin:reimburse_config 聚合页。"""
    from bot.keyboards.admin_kb import admin_reimburse_config_kb
    cbs = _cbs(admin_reimburse_config_kb())
    assert "system:reimburse_pool_reset" in cbs


# ============================================================
# 28-31. 审批一致性：effective_used 口径
# ============================================================


def test_admin_reimburse_uses_get_reimbursement_monthly_pool_usage():
    """admin_reimburse.py 月池校验改用 get_reimbursement_monthly_pool_usage。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    assert "get_reimbursement_monthly_pool_usage" in src
    # 不再直接调 sum_approved_reimbursements_in_month
    # （仍保留 import 是为了向后兼容其它路径，但月池决策处不用它）


def test_reimbursement_pool_service_uses_effective_used():
    """reimbursement_pool service 使用 get_reimbursement_monthly_pool_usage。"""
    import bot.services.reimbursement_pool as mod
    src = _src(mod)
    assert "get_reimbursement_monthly_pool_usage" in src


def test_reimbursement_pool_stats_has_raw_used_field():
    """ReimbursementPoolStats 新增 raw_used_this_month / reset_baseline_this_month。"""
    from dataclasses import fields
    from bot.services.reimbursement_pool import ReimbursementPoolStats
    field_names = {f.name for f in fields(ReimbursementPoolStats)}
    assert "raw_used_this_month" in field_names
    assert "reset_baseline_this_month" in field_names


def test_pool_check_consistency_after_reset(temp_db):
    """reset 后 admin_reimburse 审批 + service 状态页都用 effective_used。

    场景：raw_used=1200，reset_baseline=1200 → effective_used=0
    pool=600 → raw 已超过 pool，但 effective 未超 → 应允许新批准。
    """
    from bot.database import (
        get_reimbursement_monthly_pool_usage, set_reimburse_pool_reset_baseline,
        set_config, current_month_key,
    )
    month_key = current_month_key()
    _run(_insert_approved_reimb(1200, month_key))  # raw_used = 1200
    _run(set_reimburse_pool_reset_baseline(
        month_key=month_key, baseline_amount=1200,
        admin_id=1, reason="reset",
    ))
    _run(set_config("reimbursement_monthly_pool", "600"))
    usage = _run(get_reimbursement_monthly_pool_usage(month_key))
    assert usage["effective_used"] == 0
    # 模拟 admin_reimburse 判断逻辑：pool=600, effective=0, 新申请 300
    pool = 600
    if pool > 0:
        new_amount = 300
        assert usage["effective_used"] + new_amount <= pool, (
            "reset 后 effective+amount 不应超过 pool —— 允许批准"
        )


def test_pool_check_blocks_when_effective_plus_amount_exceeds(temp_db):
    """reset 后 effective + amount 仍超 pool → 应拒绝。"""
    from bot.database import (
        get_reimbursement_monthly_pool_usage, set_reimburse_pool_reset_baseline,
        set_config, current_month_key,
    )
    month_key = current_month_key()
    _run(_insert_approved_reimb(1000, month_key))
    _run(set_reimburse_pool_reset_baseline(
        month_key=month_key, baseline_amount=500,
        admin_id=1, reason="reset",
    ))
    _run(set_config("reimbursement_monthly_pool", "600"))
    usage = _run(get_reimbursement_monthly_pool_usage(month_key))
    # raw=1000, baseline=500, effective=500
    assert usage["effective_used"] == 500
    new_amount = 200
    # pool=600, effective=500, +200 = 700 > 600 → 拒绝
    assert usage["effective_used"] + new_amount > 600


# ============================================================
# 32-38. 隔离性
# ============================================================


def test_compute_reimbursement_amount_unchanged():
    from bot.database import compute_reimbursement_amount
    assert callable(compute_reimbursement_amount)


def test_payout_flow_helpers_unchanged():
    """支付宝口令流程 helper 未触动。"""
    from bot.utils.reimburse_notify import (
        safe_send_user_payout,
        notify_supers_reimburse_pending,
        mask_token,
        POWERED_BY_FOOTER,
    )
    for fn in (safe_send_user_payout, notify_supers_reimburse_pending, mask_token):
        assert callable(fn)
    assert POWERED_BY_FOOTER == "✳ Powered by @CDCChiYanLog"


def test_reimburse_subreq_helpers_unchanged():
    """报销专用必关配置 helper 未触动。"""
    from bot.database import (
        get_reimburse_required_chats,
        set_reimburse_required_chats,
        add_reimburse_required_chat,
        remove_reimburse_required_chat,
    )
    for fn in (
        get_reimburse_required_chats, set_reimburse_required_chats,
        add_reimburse_required_chat, remove_reimburse_required_chat,
    ):
        assert callable(fn)


def test_global_required_channels_unchanged():
    """全局必关订阅 helper 未触动。"""
    from bot.utils.required_channels import check_user_subscribed
    from bot.database import list_required_subscriptions
    assert callable(check_user_subscribed)
    assert callable(list_required_subscriptions)


# Phase A0（2026-05-23）已下线：test_lottery_helpers_unchanged（抽奖功能整体下线）


def test_point_helpers_unchanged():
    from bot.database import add_point_transaction, get_user_total_points
    assert callable(add_point_transaction)
    assert callable(get_user_total_points)


def test_schema_migrations_baseline_unchanged():
    """本批仅复用 config 表，不动 schema。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    from _migration_baseline import EXPECTED_MIGRATION_VERSIONS
    assert {m.version for m in MIGRATIONS} == EXPECTED_MIGRATION_VERSIONS


def test_approve_reimbursement_db_function_unchanged():
    """approve_reimbursement DB 函数体未触动。"""
    from bot.database import approve_reimbursement
    src = inspect.getsource(approve_reimbursement)
    assert "approved" in src
    assert "pending" in src


def test_reimburse_payout_states_still_present():
    from bot.states.teacher_states import ReimbursePayoutStates
    assert ReimbursePayoutStates.waiting_token is not None
    assert ReimbursePayoutStates.confirming is not None


def test_new_fsm_states_independent():
    """新 FSM 与既有不同。"""
    from bot.states.teacher_states import (
        ReimbursePayoutStates,
        ReimburseMinPointsStates,
        ReimbursePoolResetStates,
        ReimburseRejectStates,
        ReimburseSubReqAddStates,
    )
    classes = [
        ReimbursePayoutStates, ReimburseMinPointsStates, ReimbursePoolResetStates,
        ReimburseRejectStates, ReimburseSubReqAddStates,
    ]
    # 所有 5 个类应互相独立
    assert len({id(c) for c in classes}) == 5


def test_settings_router_registered():
    """reimburse_settings_admin_router 已注册。"""
    import bot.routers as routers_mod
    src = _src(routers_mod)
    assert "reimburse_settings_admin_router" in src
    assert "include_router(reimburse_settings_admin_router)" in src


def test_admin_audit_helper_callable():
    """log_admin_audit 仍可 import + callable。"""
    from bot.database import log_admin_audit
    assert callable(log_admin_audit)


# ============================================================
# Keyboard contracts
# ============================================================


def test_min_points_menu_kb_buttons():
    from bot.keyboards.admin_kb import reimburse_min_points_menu_kb
    cbs = _cbs(reimburse_min_points_menu_kb())
    assert "system:reimburse_min_points:edit" in cbs
    assert "menu:system" in cbs


def test_min_points_confirm_kb_buttons():
    from bot.keyboards.admin_kb import reimburse_min_points_confirm_kb
    cbs = _cbs(reimburse_min_points_confirm_kb())
    assert "system:reimburse_min_points:confirm" in cbs
    assert "system:reimburse_min_points" in cbs


def test_pool_reset_confirm_kb_buttons():
    from bot.keyboards.admin_kb import reimburse_pool_reset_confirm_kb
    cbs = _cbs(reimburse_pool_reset_confirm_kb())
    assert "system:reimburse_pool_reset:confirm" in cbs
    assert "system:reimburse_pool_reset" in cbs


def test_pool_reset_done_kb_buttons():
    from bot.keyboards.admin_kb import reimburse_pool_reset_done_kb
    cbs = _cbs(reimburse_pool_reset_done_kb())
    assert "system:reimburse_pool" in cbs
    assert "admin:reimbursement_pool" in cbs
    assert "menu:system" in cbs
