"""Sprint UX-2 第三项第二批：「报销池状态 / 抽奖状态异常快捷跳转」契约测试。

背景：
    UX-2 第三项第二批要求在 admin:reimbursement_pool（报销池状态）与
    admin:lottery_status（抽奖状态）页面底部按钮区，根据各自 Stats 与权限
    渲染快捷跳转，减少管理员"看完看板 → 翻菜单 → 找入口"的点击。

设计：
    - 两个 kb 函数均改签名 `(stats=None, *, is_super=False)`，stats=None 兼容旧调用
    - 报销池状态快捷跳转（仅超管）：
        💰 报销审核 (pending_count)  → reimburse:enter
        📋 报销名单 (queued_count)   → reimburse:queued:0
    - 抽奖状态快捷跳转（仅超管）：
        🎲 抽奖管理 (active+scheduled) → admin:lottery
    - count = 0 / None 时整体不显示；刷新 + 返回按钮始终保留
    - 两个 Stats **未新增字段**——复用既有 pending_count / queued_count /
      active_count / scheduled_count

不连接真实 Telegram；不访问生产 DB；纯静态 / keyboard 断言。
"""

from __future__ import annotations

import inspect


# ============ helpers ============


def _make_pool_stats(**kwargs):
    from bot.services.reimbursement_pool import ReimbursementPoolStats
    return ReimbursementPoolStats(**kwargs)


def _make_lottery_stats(**kwargs):
    from bot.services.lottery_status import LotteryStatusStats
    return LotteryStatusStats(**kwargs)


def _cbs(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


# ============================================================
# 1. 报销池状态快捷跳转
# ============================================================


def test_reimbursement_pool_kb_shows_pending_review_shortcut_for_super():
    """超管 + pending_count > 0：显示 reimburse:enter 快捷按钮。"""
    from bot.keyboards.admin_kb import admin_reimbursement_pool_kb
    kb = admin_reimbursement_pool_kb(
        _make_pool_stats(pending_count=3),
        is_super=True,
    )
    cbs = _cbs(kb)
    assert "reimburse:enter" in cbs
    btn = next(b for row in kb.inline_keyboard for b in row
               if b.callback_data == "reimburse:enter")
    assert "(3)" in btn.text
    assert "报销审核" in btn.text


def test_reimbursement_pool_kb_shows_queued_shortcut_for_super():
    """超管 + queued_count > 0：显示 reimburse:queued:0 快捷按钮。"""
    from bot.keyboards.admin_kb import admin_reimbursement_pool_kb
    kb = admin_reimbursement_pool_kb(
        _make_pool_stats(queued_count=5),
        is_super=True,
    )
    cbs = _cbs(kb)
    assert "reimburse:queued:0" in cbs
    btn = next(b for row in kb.inline_keyboard for b in row
               if b.callback_data == "reimburse:queued:0")
    assert "(5)" in btn.text
    assert "报销名单" in btn.text


def test_reimbursement_pool_kb_hides_shortcuts_when_zero():
    """pending = queued = 0 时两个快捷按钮整体不显示。"""
    from bot.keyboards.admin_kb import admin_reimbursement_pool_kb
    kb = admin_reimbursement_pool_kb(
        _make_pool_stats(pending_count=0, queued_count=0),
        is_super=True,
    )
    cbs = _cbs(kb)
    assert "reimburse:enter" not in cbs
    assert "reimburse:queued:0" not in cbs
    # 兜底按钮仍在
    assert "admin:reimbursement_pool:refresh" in cbs
    assert "admin:dashboard" in cbs


def test_reimbursement_pool_kb_treats_none_counts_as_zero():
    """None count（统计失败回落）视为 0，对应快捷整体不显示。"""
    from bot.keyboards.admin_kb import admin_reimbursement_pool_kb
    kb = admin_reimbursement_pool_kb(_make_pool_stats(), is_super=True)  # 全 None
    cbs = _cbs(kb)
    assert "reimburse:enter" not in cbs
    assert "reimburse:queued:0" not in cbs
    assert "admin:reimbursement_pool:refresh" in cbs
    assert "admin:dashboard" in cbs


def test_reimbursement_pool_kb_hides_shortcuts_for_non_super():
    """非超管即便 count > 0 也不应看到任何快捷跳转。"""
    from bot.keyboards.admin_kb import admin_reimbursement_pool_kb
    kb = admin_reimbursement_pool_kb(
        _make_pool_stats(pending_count=99, queued_count=99),
        is_super=False,
    )
    cbs = _cbs(kb)
    assert "reimburse:enter" not in cbs
    assert "reimburse:queued:0" not in cbs
    # 兜底按钮仍在
    assert "admin:reimbursement_pool:refresh" in cbs
    assert "admin:dashboard" in cbs


def test_reimbursement_pool_kb_refresh_and_back_always_present():
    """刷新 + 返回按钮在所有 stats/权限组合下都存在。"""
    from bot.keyboards.admin_kb import admin_reimbursement_pool_kb
    cases = [
        admin_reimbursement_pool_kb(),  # 旧无参兼容
        admin_reimbursement_pool_kb(None, is_super=True),
        admin_reimbursement_pool_kb(_make_pool_stats(), is_super=False),
        admin_reimbursement_pool_kb(
            _make_pool_stats(pending_count=10, queued_count=10),
            is_super=True,
        ),
    ]
    for kb in cases:
        cbs = _cbs(kb)
        assert "admin:reimbursement_pool:refresh" in cbs
        assert "admin:dashboard" in cbs


def test_reimbursement_pool_kb_no_args_returns_only_refresh_and_back():
    """无参 admin_reimbursement_pool_kb()：仅含兜底（旧调用兼容）。"""
    from bot.keyboards.admin_kb import admin_reimbursement_pool_kb
    kb = admin_reimbursement_pool_kb()
    assert _cbs(kb) == ["admin:reimbursement_pool:refresh", "admin:dashboard"]


def test_reimbursement_pool_kb_shortcuts_never_trigger_approve_reject():
    """报销池快捷按钮 callback 必须是导航类，不应触发 approve/reject。"""
    from bot.keyboards.admin_kb import admin_reimbursement_pool_kb
    kb = admin_reimbursement_pool_kb(
        _make_pool_stats(pending_count=1, queued_count=1),
        is_super=True,
    )
    for cb in _cbs(kb):
        for forbidden in (":approve", ":reject", ":delete", ":cancel"):
            assert forbidden not in cb, (
                f"报销池快捷按钮 callback 不应含 {forbidden}：{cb}"
            )


# ============================================================
# 2. 抽奖状态快捷跳转
# ============================================================


def test_lottery_status_kb_shows_lottery_shortcut_when_active():
    """超管 + active_count > 0：显示 admin:lottery 快捷按钮。"""
    from bot.keyboards.admin_kb import admin_lottery_status_kb
    kb = admin_lottery_status_kb(
        _make_lottery_stats(active_count=2),
        is_super=True,
    )
    cbs = _cbs(kb)
    assert "admin:lottery" in cbs
    btn = next(b for row in kb.inline_keyboard for b in row
               if b.callback_data == "admin:lottery")
    assert "(2)" in btn.text
    assert "抽奖管理" in btn.text


def test_lottery_status_kb_shows_lottery_shortcut_when_scheduled():
    """超管 + scheduled_count > 0（active=0）：仍显示 admin:lottery。"""
    from bot.keyboards.admin_kb import admin_lottery_status_kb
    kb = admin_lottery_status_kb(
        _make_lottery_stats(scheduled_count=3),
        is_super=True,
    )
    cbs = _cbs(kb)
    assert "admin:lottery" in cbs
    btn = next(b for row in kb.inline_keyboard for b in row
               if b.callback_data == "admin:lottery")
    assert "(3)" in btn.text


def test_lottery_status_kb_aggregates_active_and_scheduled():
    """N = active_count + scheduled_count（与运营总览口径一致）。"""
    from bot.keyboards.admin_kb import admin_lottery_status_kb
    kb = admin_lottery_status_kb(
        _make_lottery_stats(active_count=2, scheduled_count=3),
        is_super=True,
    )
    btn = next(b for row in kb.inline_keyboard for b in row
               if b.callback_data == "admin:lottery")
    assert "(5)" in btn.text  # 2 + 3


def test_lottery_status_kb_hides_shortcut_when_zero():
    """active = scheduled = 0：快捷按钮整体不显示。"""
    from bot.keyboards.admin_kb import admin_lottery_status_kb
    kb = admin_lottery_status_kb(
        _make_lottery_stats(active_count=0, scheduled_count=0),
        is_super=True,
    )
    cbs = _cbs(kb)
    assert "admin:lottery" not in cbs
    # 兜底按钮仍在
    assert "admin:lottery_status:refresh" in cbs
    assert "admin:dashboard" in cbs


def test_lottery_status_kb_treats_none_counts_as_zero():
    """None count 视为 0，快捷整体不显示。"""
    from bot.keyboards.admin_kb import admin_lottery_status_kb
    kb = admin_lottery_status_kb(_make_lottery_stats(), is_super=True)
    cbs = _cbs(kb)
    assert "admin:lottery" not in cbs


def test_lottery_status_kb_hides_shortcut_for_non_super():
    """非超管即便 count > 0 也不应看到抽奖管理快捷入口。"""
    from bot.keyboards.admin_kb import admin_lottery_status_kb
    kb = admin_lottery_status_kb(
        _make_lottery_stats(active_count=99, scheduled_count=99),
        is_super=False,
    )
    cbs = _cbs(kb)
    assert "admin:lottery" not in cbs
    # 兜底按钮仍在
    assert "admin:lottery_status:refresh" in cbs
    assert "admin:dashboard" in cbs


def test_lottery_status_kb_refresh_and_back_always_present():
    from bot.keyboards.admin_kb import admin_lottery_status_kb
    cases = [
        admin_lottery_status_kb(),
        admin_lottery_status_kb(None, is_super=True),
        admin_lottery_status_kb(_make_lottery_stats(), is_super=False),
        admin_lottery_status_kb(
            _make_lottery_stats(active_count=5, scheduled_count=5),
            is_super=True,
        ),
    ]
    for kb in cases:
        cbs = _cbs(kb)
        assert "admin:lottery_status:refresh" in cbs
        assert "admin:dashboard" in cbs


def test_lottery_status_kb_no_args_returns_only_refresh_and_back():
    from bot.keyboards.admin_kb import admin_lottery_status_kb
    kb = admin_lottery_status_kb()
    assert _cbs(kb) == ["admin:lottery_status:refresh", "admin:dashboard"]


def test_lottery_status_kb_shortcut_never_triggers_draw_or_cancel():
    """抽奖状态快捷按钮 callback 必须是导航类，不应触发开奖/取消等高风险动作。"""
    from bot.keyboards.admin_kb import admin_lottery_status_kb
    kb = admin_lottery_status_kb(
        _make_lottery_stats(active_count=1, scheduled_count=1),
        is_super=True,
    )
    for cb in _cbs(kb):
        for forbidden in (":draw", ":cancel", ":delete", ":approve", ":reject",
                          ":publish_ok", ":repost_ok"):
            assert forbidden not in cb, (
                f"抽奖状态快捷按钮 callback 不应含 {forbidden}：{cb}"
            )


# ============================================================
# 3. handler wiring：注入 stats + is_super
# ============================================================


def _admin_panel_source() -> str:
    import bot.handlers.admin_panel as ap
    return inspect.getsource(ap)


def test_cb_admin_reimbursement_pool_passes_stats_and_is_super_to_kb():
    """cb_admin_reimbursement_pool 必须把 stats + is_super 传给 kb。"""
    src = _admin_panel_source()
    idx = src.find("async def cb_admin_reimbursement_pool(")
    assert idx > 0
    body = src[idx:idx + 1500]
    assert "is_super" in body
    assert "admin_reimbursement_pool_kb(stats" in body
    assert "is_super=is_super" in body


def test_cb_admin_reimbursement_pool_refresh_passes_stats_and_is_super():
    """cb_admin_reimbursement_pool_refresh 同样应注入 stats + is_super。"""
    src = _admin_panel_source()
    idx = src.find("async def cb_admin_reimbursement_pool_refresh(")
    assert idx > 0
    body = src[idx:idx + 1500]
    assert "is_super" in body
    assert "admin_reimbursement_pool_kb(stats" in body
    assert "is_super=is_super" in body


def test_cb_admin_lottery_status_passes_stats_and_is_super_to_kb():
    src = _admin_panel_source()
    idx = src.find("async def cb_admin_lottery_status(")
    assert idx > 0
    body = src[idx:idx + 1500]
    assert "is_super" in body
    assert "admin_lottery_status_kb(stats" in body
    assert "is_super=is_super" in body


def test_cb_admin_lottery_status_refresh_passes_stats_and_is_super():
    src = _admin_panel_source()
    idx = src.find("async def cb_admin_lottery_status_refresh(")
    assert idx > 0
    body = src[idx:idx + 1500]
    assert "is_super" in body
    assert "admin_lottery_status_kb(stats" in body
    assert "is_super=is_super" in body


# ============================================================
# 4. Stats 未新增字段 + service 未改业务口径
# ============================================================


def test_reimbursement_pool_stats_fields_include_original_set():
    """ReimbursementPoolStats 必须保留 UX-2 第三项第二批的字段集；
    后续可以追加新字段（如 2026-05 reset baseline 相关），但不应删除既有字段。
    """
    from dataclasses import fields
    from bot.services.reimbursement_pool import ReimbursementPoolStats
    field_names = {f.name for f in fields(ReimbursementPoolStats)}
    required = {
        "feature_enabled", "monthly_pool", "month_key", "week_key",
        "approved_amount_this_month", "remaining_pool",
        "pending_count", "queued_count",
        "approved_count_this_month", "rejected_count_this_month",
        "approved_users_this_week", "approved_amount_this_week",
        "reset_vouchers_used_this_week", "generated_at",
    }
    missing = required - field_names
    assert not missing, (
        f"ReimbursementPoolStats 必须保留以下字段；缺：{missing}"
    )


def test_lottery_status_stats_fields_unchanged():
    """LotteryStatusStats 字段集应未被本批改变。"""
    from dataclasses import fields
    from bot.services.lottery_status import LotteryStatusStats
    field_names = {f.name for f in fields(LotteryStatusStats)}
    expected = {
        "draft_count", "scheduled_count", "active_count", "drawn_count",
        "no_entries_count", "cancelled_count",
        "waiting_publish_count", "waiting_draw_count",
        "active_without_entries_count", "paid_lottery_count",
        "recent_lotteries", "generated_at",
    }
    assert field_names == expected, (
        f"LotteryStatusStats 字段集应保持不变；"
        f"多出：{field_names - expected}；少了：{expected - field_names}"
    )


# ============================================================
# 5. callback 字面量 + 业务 handler 未删
# ============================================================


def test_dashboard_callbacks_still_present_in_admin_panel():
    src = _admin_panel_source()
    assert '"admin:reimbursement_pool"' in src
    assert '"admin:reimbursement_pool:refresh"' in src
    assert '"admin:lottery_status"' in src
    assert '"admin:lottery_status:refresh"' in src


def test_shortcut_target_handlers_still_importable():
    """快捷跳转目标 handler 仍可正常 import；router 非空。"""
    from bot.handlers.admin_reimburse import router as r1
    from bot.handlers.admin_lottery import router as r2
    assert r1 is not None
    assert r2 is not None


def test_shortcut_target_callbacks_still_in_their_handlers():
    """reimburse:enter / reimburse:queued / admin:lottery callback 字面量
    仍存在于对应 handler 源码中。"""
    import inspect
    import bot.handlers.admin_reimburse as ari
    import bot.handlers.admin_lottery as al
    ari_src = inspect.getsource(ari)
    al_src = inspect.getsource(al)
    assert '"reimburse:enter"' in ari_src
    assert "reimburse:queued" in ari_src  # 以 startswith 形式注册
    assert '"admin:lottery"' in al_src


# ============================================================
# 6. schema / 业务保护
# ============================================================


def test_schema_migrations_baseline_unchanged():
    """UX-2 第三项第二批不动 schema。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable"}


def test_compute_reimbursement_amount_unchanged():
    """报销金额计算函数仍 importable + callable。"""
    from bot.database import compute_reimbursement_amount
    assert callable(compute_reimbursement_amount)


def test_existing_dashboard_return_path_still_admin_dashboard():
    """UX-1 第一批的契约不被本批破坏：两个 kb 的返回按钮仍指向 admin:dashboard。"""
    from bot.keyboards.admin_kb import (
        admin_reimbursement_pool_kb, admin_lottery_status_kb,
    )
    for kb in (admin_reimbursement_pool_kb(), admin_lottery_status_kb()):
        cbs = _cbs(kb)
        assert "admin:dashboard" in cbs
        assert "menu:main" not in cbs
