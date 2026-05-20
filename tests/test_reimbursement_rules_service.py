"""报销规则只读页（admin:reimburse_rules）service 单元测试。

测试范围：
    1. ReimbursementRulesSnapshot dataclass 默认 / 完整构造
    2. WEEKLY_APPROVED_LIMIT 常量值
    3. _parse_monthly_pool 边界
    4. _fmt_pool / _fmt_min_points / _fmt_required_chats / _fmt_queued_mode
    5. render_reimbursement_rules：含全部规则项、N/A 回退、reset baseline 渲染
    6. get_reimbursement_rules_snapshot：monkeypatch 全部依赖函数

为避免引入 pytest-asyncio，async 通过 asyncio.run 同步包裹。
不连接真实数据库；不连接 Telegram。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from bot.services import reimbursement_rules as svc_mod
from bot.services.reimbursement_rules import (
    REIMBURSE_MIN_POINTS_DEFAULT,
    REIMBURSE_MIN_POINTS_MAX,
    ReimbursementRulesSnapshot,
    WEEKLY_APPROVED_LIMIT,
    _fmt_feature,
    _fmt_min_points,
    _fmt_pool,
    _fmt_queued_mode,
    _fmt_required_chats,
    _parse_monthly_pool,
    get_reimbursement_rules_snapshot,
    render_reimbursement_rules,
)


def _run(coro):
    return asyncio.run(coro)


# ============ 常量 + dataclass ============


def test_weekly_limit_constant():
    """POLICY §6.1 硬编码 1 次/周。"""
    assert WEEKLY_APPROVED_LIMIT == 1


def test_min_points_defaults_re_exported():
    """REIMBURSE_MIN_POINTS_DEFAULT / MAX 必须由 service 暴露，避免漂移。"""
    assert REIMBURSE_MIN_POINTS_DEFAULT == 5
    assert REIMBURSE_MIN_POINTS_MAX == 100


def test_snapshot_defaults_all_none():
    s = ReimbursementRulesSnapshot()
    assert s.feature_enabled is None
    assert s.monthly_pool is None
    assert s.min_points is None
    assert s.queued_count is None
    assert s.required_chats_total is None
    assert s.required_chats_enabled is None
    assert s.current_month_reset_baseline is None
    assert s.generated_at is None
    # 硬编码默认
    assert s.weekly_approved_limit == 1
    assert s.min_points_default == 5
    assert s.min_points_max == 100


# ============ _parse_monthly_pool ============


def test_parse_monthly_pool_none_returns_none():
    assert _parse_monthly_pool(None) is None


def test_parse_monthly_pool_empty_string_returns_none():
    assert _parse_monthly_pool("") is None


def test_parse_monthly_pool_zero_kept_as_zero():
    """0 是合法值（=不限），不应被改写为 None。"""
    assert _parse_monthly_pool("0") == 0


def test_parse_monthly_pool_positive():
    assert _parse_monthly_pool("5000") == 5000


def test_parse_monthly_pool_invalid_string():
    assert _parse_monthly_pool("abc") is None


# ============ 格式化 helper ============


def test_fmt_feature_enabled():
    assert "开启" in _fmt_feature(True)
    assert "关闭" in _fmt_feature(False)
    assert "N/A" in _fmt_feature(None)


def test_fmt_pool_branches():
    assert _fmt_pool(None) == "N/A"
    assert _fmt_pool(0) == "不限（0 元）"
    assert _fmt_pool(3000) == "3000 元"


def test_fmt_min_points_zero_means_disabled():
    s = ReimbursementRulesSnapshot(min_points=0)
    text = _fmt_min_points(s)
    assert "0 分" in text
    assert "未启用" in text


def test_fmt_min_points_positive_shows_default_and_max():
    s = ReimbursementRulesSnapshot(min_points=10)
    text = _fmt_min_points(s)
    assert "10 分" in text
    assert "默认 5" in text
    assert "上限 100" in text


def test_fmt_min_points_none():
    s = ReimbursementRulesSnapshot(min_points=None)
    assert _fmt_min_points(s) == "N/A"


def test_fmt_required_chats_zero_no_block():
    s = ReimbursementRulesSnapshot(
        required_chats_total=0, required_chats_enabled=0,
    )
    assert "无" in _fmt_required_chats(s)
    assert "不拦截" in _fmt_required_chats(s)


def test_fmt_required_chats_some_enabled():
    s = ReimbursementRulesSnapshot(
        required_chats_total=5, required_chats_enabled=3,
    )
    text = _fmt_required_chats(s)
    assert "共 5 个" in text
    assert "启用 3" in text


def test_fmt_required_chats_none():
    s = ReimbursementRulesSnapshot(
        required_chats_total=None, required_chats_enabled=None,
    )
    assert _fmt_required_chats(s) == "N/A"


def test_fmt_queued_mode_feature_on():
    s = ReimbursementRulesSnapshot(feature_enabled=True, queued_count=2)
    text = _fmt_queued_mode(s)
    assert "不入队" in text
    assert "queued 名单 2 条" in text


def test_fmt_queued_mode_feature_off():
    s = ReimbursementRulesSnapshot(feature_enabled=False, queued_count=7)
    text = _fmt_queued_mode(s)
    assert "进 queued" in text
    assert "queued 名单 7 条" in text


def test_fmt_queued_mode_feature_unset():
    s = ReimbursementRulesSnapshot(feature_enabled=None, queued_count=0)
    text = _fmt_queued_mode(s)
    assert "N/A" in text


# ============ render：完整结构 ============


def _full_snapshot(**overrides) -> ReimbursementRulesSnapshot:
    base = ReimbursementRulesSnapshot(
        feature_enabled=True,
        monthly_pool=3000,
        current_month_key="2026-05",
        current_month_reset_baseline=None,
        min_points=10,
        queued_count=4,
        current_week_key="2026-W21",
        required_chats_total=2,
        required_chats_enabled=2,
        generated_at=datetime(2026, 5, 20, 14, 30, 0),
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_render_contains_all_rule_sections():
    text = render_reimbursement_rules(_full_snapshot())
    for section in (
        "📜 报销规则一览",
        "功能开关",
        "月度报销池",
        "积分门槛",
        "每周限制",
        "queued 名单模式",
        "报销必关频道",
    ):
        assert section in text


def test_render_includes_all_data_fields():
    text = render_reimbursement_rules(_full_snapshot())
    assert "开启" in text  # feature_enabled=True
    assert "3000 元" in text  # monthly_pool=3000
    assert "10 分" in text  # min_points=10
    assert "queued 名单 4 条" in text
    assert "2026-05" in text
    assert "2026-W21" in text
    assert "共 2 个" in text
    assert "快照时间：2026-05-20 14:30:00" in text


def test_render_weekly_limit_hardcoded_1():
    text = render_reimbursement_rules(_full_snapshot())
    assert "每用户每周 approved 上限：1 次" in text
    assert "硬编码" in text


def test_render_reset_voucher_explanation_present():
    text = render_reimbursement_rules(_full_snapshot())
    assert "reset voucher" in text
    assert "一次性" in text
    assert "不增加永久额度" in text


def test_render_n_a_fallback_for_unset_config():
    snap = ReimbursementRulesSnapshot(
        generated_at=datetime(2026, 5, 20, 14, 30, 0),
    )
    text = render_reimbursement_rules(snap)
    # 关键字段必须 N/A，不抛异常
    assert "N/A" in text
    # 必关频道 N/A
    assert "报销必关频道" in text


def test_render_pool_zero_means_unlimited():
    text = render_reimbursement_rules(_full_snapshot(monthly_pool=0))
    assert "不限" in text


def test_render_reset_baseline_when_set():
    text = render_reimbursement_rules(_full_snapshot(
        current_month_reset_baseline=500,
    ))
    assert "重置基线：500 元" in text


def test_render_reset_baseline_not_set_explicitly_states_so():
    """未设置 baseline 时应明确说明，避免歧义。"""
    text = render_reimbursement_rules(_full_snapshot(
        current_month_reset_baseline=None,
    ))
    assert "未设置重置基线" in text


def test_render_marks_readonly_in_header():
    """页头必须说明这是只读页（避免误以为可点击编辑）。"""
    text = render_reimbursement_rules(_full_snapshot())
    assert "只读" in text


# ============ get_reimbursement_rules_snapshot：monkeypatch 集成 ============


async def _stub_get_config(key):
    return {
        "reimbursement_feature_enabled": "1",
        "reimbursement_monthly_pool": "5000",
    }.get(key)


async def _stub_count_queued():
    return 3


async def _stub_min_points():
    return 8


async def _stub_required_chats():
    return [
        {"chat_id": 1, "enabled": True},
        {"chat_id": 2, "enabled": True},
        {"chat_id": 3, "enabled": False},
    ]


async def _stub_baselines():
    return {"2026-05": {
        "baseline_amount": 200,
        "reset_at": "2026-05-01 00:00:00",
        "admin_id": 1,
        "reason": "月初重置",
    }}


def _install_stubs(monkeypatch):
    monkeypatch.setattr(svc_mod, "get_config", _stub_get_config)
    monkeypatch.setattr(svc_mod, "count_queued_reimbursements", _stub_count_queued)
    monkeypatch.setattr(svc_mod, "get_reimbursement_min_points", _stub_min_points)
    monkeypatch.setattr(svc_mod, "get_reimburse_required_chats", _stub_required_chats)
    monkeypatch.setattr(svc_mod, "get_reimburse_pool_reset_baselines", _stub_baselines)


def test_get_snapshot_assembles_all_fields(monkeypatch):
    _install_stubs(monkeypatch)
    snap = _run(get_reimbursement_rules_snapshot())
    assert snap.feature_enabled is True
    assert snap.monthly_pool == 5000
    assert snap.min_points == 8
    assert snap.queued_count == 3
    assert snap.required_chats_total == 3
    assert snap.required_chats_enabled == 2
    assert snap.current_month_reset_baseline == 200
    assert snap.current_month_key  # 由 current_month_key() 真实生成
    assert snap.current_week_key  # 由 current_week_key() 真实生成


def test_get_snapshot_feature_off_when_zero(monkeypatch):
    async def _stub_get_config_off(key):
        return "0" if key == "reimbursement_feature_enabled" else None
    monkeypatch.setattr(svc_mod, "get_config", _stub_get_config_off)
    monkeypatch.setattr(svc_mod, "count_queued_reimbursements", _stub_count_queued)
    monkeypatch.setattr(svc_mod, "get_reimbursement_min_points", _stub_min_points)
    monkeypatch.setattr(svc_mod, "get_reimburse_required_chats", _stub_required_chats)
    monkeypatch.setattr(svc_mod, "get_reimburse_pool_reset_baselines", _stub_baselines)
    snap = _run(get_reimbursement_rules_snapshot())
    assert snap.feature_enabled is False
    # monthly_pool 缺失时 None
    assert snap.monthly_pool is None


def test_get_snapshot_feature_none_when_config_missing(monkeypatch):
    """config key 不存在 → feature_enabled=None（与 '0' 区分）。"""
    async def _stub_all_none(key):
        return None
    monkeypatch.setattr(svc_mod, "get_config", _stub_all_none)
    monkeypatch.setattr(svc_mod, "count_queued_reimbursements", _stub_count_queued)
    monkeypatch.setattr(svc_mod, "get_reimbursement_min_points", _stub_min_points)
    monkeypatch.setattr(svc_mod, "get_reimburse_required_chats", _stub_required_chats)
    monkeypatch.setattr(svc_mod, "get_reimburse_pool_reset_baselines", _stub_baselines)
    snap = _run(get_reimbursement_rules_snapshot())
    assert snap.feature_enabled is None


def test_get_snapshot_handles_required_chats_empty(monkeypatch):
    async def _empty_chats():
        return []
    monkeypatch.setattr(svc_mod, "get_config", _stub_get_config)
    monkeypatch.setattr(svc_mod, "count_queued_reimbursements", _stub_count_queued)
    monkeypatch.setattr(svc_mod, "get_reimbursement_min_points", _stub_min_points)
    monkeypatch.setattr(svc_mod, "get_reimburse_required_chats", _empty_chats)
    monkeypatch.setattr(svc_mod, "get_reimburse_pool_reset_baselines", _stub_baselines)
    snap = _run(get_reimbursement_rules_snapshot())
    assert snap.required_chats_total == 0
    assert snap.required_chats_enabled == 0


def test_get_snapshot_handles_min_points_failure(monkeypatch):
    """get_reimbursement_min_points 异常 → min_points None，不应崩溃。"""
    async def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(svc_mod, "get_config", _stub_get_config)
    monkeypatch.setattr(svc_mod, "count_queued_reimbursements", _stub_count_queued)
    monkeypatch.setattr(svc_mod, "get_reimbursement_min_points", _boom)
    monkeypatch.setattr(svc_mod, "get_reimburse_required_chats", _stub_required_chats)
    monkeypatch.setattr(svc_mod, "get_reimburse_pool_reset_baselines", _stub_baselines)
    snap = _run(get_reimbursement_rules_snapshot())
    assert snap.min_points is None
    # 其它字段仍可用
    assert snap.feature_enabled is True


def test_get_snapshot_handles_no_baseline_for_current_month(monkeypatch):
    async def _no_baseline_for_now():
        return {"2099-12": {"baseline_amount": 999, "reset_at": "", "admin_id": 1, "reason": ""}}
    monkeypatch.setattr(svc_mod, "get_config", _stub_get_config)
    monkeypatch.setattr(svc_mod, "count_queued_reimbursements", _stub_count_queued)
    monkeypatch.setattr(svc_mod, "get_reimbursement_min_points", _stub_min_points)
    monkeypatch.setattr(svc_mod, "get_reimburse_required_chats", _stub_required_chats)
    monkeypatch.setattr(svc_mod, "get_reimburse_pool_reset_baselines", _no_baseline_for_now)
    snap = _run(get_reimbursement_rules_snapshot())
    # 本月没有 baseline → None
    assert snap.current_month_reset_baseline is None
