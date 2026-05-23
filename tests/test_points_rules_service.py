"""积分规则只读页（admin:points_rules）service 单元测试。

测试范围：
    1. PointsRulesSnapshot dataclass 默认 / 完整构造
    2. MANUAL_GRANT_DELTA_MIN / MAX 常量值
    3. REASON_CATALOG 与 POLICY §3 reason 表一致
    4. _fmt_delta / _fmt_reimburse_min 边界
    5. render_points_rules：含全部章节、N/A 回退、所有 reason 行存在
    6. get_points_rules_snapshot：monkeypatch 报销门槛依赖

为避免引入 pytest-asyncio，async 通过 asyncio.run 同步包裹。
不连接真实数据库；不连接 Telegram。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from bot.services import points_rules as svc_mod
from bot.services.points_rules import (
    MANUAL_GRANT_DELTA_MAX,
    MANUAL_GRANT_DELTA_MIN,
    POINT_CUSTOM_MAX,
    POINT_CUSTOM_MIN,
    POINT_GRANT_REASON_OPTIONS,
    POINT_PACKAGE_OPTIONS,
    PointsRulesSnapshot,
    REASON_CATALOG,
    _fmt_delta,
    _fmt_reimburse_min,
    get_points_rules_snapshot,
    render_points_rules,
)


def _run(coro):
    return asyncio.run(coro)


# ============ 常量 + dataclass ============


def test_manual_grant_constants():
    """与 POLICY §6.3 一致：手动加扣分自定义范围 -100 ~ +100。"""
    assert MANUAL_GRANT_DELTA_MIN == -100
    assert MANUAL_GRANT_DELTA_MAX == 100


def test_review_custom_constants_re_exported():
    """POINT_CUSTOM_MIN/MAX 必须可由 service 引用。"""
    assert POINT_CUSTOM_MIN == 0
    assert POINT_CUSTOM_MAX == 100


def test_reason_catalog_covers_known_reasons():
    """REASON_CATALOG 应覆盖 POLICY §3 表中 reason。

    Phase A0（2026-05-23）：移除 lottery_entry / lottery_refund（抽奖功能整体下线）。
    """
    reasons = {entry["reason"] for entry in REASON_CATALOG}
    assert reasons == {
        "review_approved",
        "admin_grant",
        "admin_revoke",
    }


def test_reason_catalog_delta_signs():
    """每条 reason 应标注 + / - 用于渲染时分组。"""
    for entry in REASON_CATALOG:
        assert entry["delta_sign"] in {"+", "-"}


def test_snapshot_defaults_empty_lists_and_constants():
    s = PointsRulesSnapshot()
    assert s.review_packages == []
    assert s.manual_reason_options == []
    assert s.reason_catalog == []
    assert s.reimburse_min_points is None
    assert s.generated_at is None
    # 常量字段默认值
    assert s.review_custom_min == 0
    assert s.review_custom_max == 100
    assert s.manual_delta_min == -100
    assert s.manual_delta_max == 100


# ============ _fmt_delta ============


def test_fmt_delta_positive_has_plus_sign():
    assert _fmt_delta(5) == "+5"


def test_fmt_delta_zero_no_plus_sign():
    assert _fmt_delta(0) == "0"


def test_fmt_delta_negative_keeps_minus():
    assert _fmt_delta(-3) == "-3"


# ============ _fmt_reimburse_min ============


def test_fmt_reimburse_min_none_references_source():
    s = PointsRulesSnapshot(reimburse_min_points=None)
    text = _fmt_reimburse_min(s)
    assert "N/A" in text
    assert "admin:reimburse_rules" in text


def test_fmt_reimburse_min_zero_means_disabled():
    s = PointsRulesSnapshot(reimburse_min_points=0)
    text = _fmt_reimburse_min(s)
    assert "未启用门槛" in text


def test_fmt_reimburse_min_positive_cross_references_reimburse_page():
    s = PointsRulesSnapshot(reimburse_min_points=10)
    text = _fmt_reimburse_min(s)
    assert "10 分" in text
    assert "报销规则" in text


# ============ render：完整结构 ============


def _full_snapshot(**overrides) -> PointsRulesSnapshot:
    base = PointsRulesSnapshot(
        review_packages=list(POINT_PACKAGE_OPTIONS),
        manual_reason_options=list(POINT_GRANT_REASON_OPTIONS),
        reason_catalog=list(REASON_CATALOG),
        reimburse_min_points=5,
        generated_at=datetime(2026, 5, 20, 14, 30, 0),
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_render_contains_all_section_headers():
    """Phase A0（2026-05-23）：移除「抽奖积分」section（功能整体下线）。"""
    text = render_points_rules(_full_snapshot())
    for header in (
        "📜 积分规则一览",
        "积分流水 reason 取值",
        "评价 / 报告审核加分套餐",
        "管理员手动加扣分",
        "报销最低积分门槛",
        "余额一致性",
    ):
        assert header in text


def test_render_includes_all_reasons():
    """Phase A0（2026-05-23）：移除 lottery_entry / lottery_refund 两个 reason。"""
    text = render_points_rules(_full_snapshot())
    for reason in (
        "review_approved",
        "admin_grant",
        "admin_revoke",
    ):
        assert reason in text


def test_render_includes_all_review_packages():
    """5 个 POINT_PACKAGE_OPTIONS 应全部出现并带 +N 标记。"""
    text = render_points_rules(_full_snapshot())
    for pkg in POINT_PACKAGE_OPTIONS:
        assert f"key={pkg['key']}" in text
        # 0 不带 +；其它正数带 +
        delta = int(pkg["delta"])
        if delta > 0:
            assert f"+{delta}" in text


def test_render_includes_review_custom_range():
    text = render_points_rules(_full_snapshot())
    # custom_min=0（_fmt_delta(0)=="0"），custom_max=100（+100）
    assert "0 ~ +100" in text
    assert "仅加分，不在此处扣分" in text


def test_render_includes_manual_grant_range_and_reason_options():
    text = render_points_rules(_full_snapshot())
    assert "-100" in text  # manual_delta_min
    assert "+100" in text  # manual_delta_max
    for opt in POINT_GRANT_REASON_OPTIONS:
        assert f"key={opt['key']}" in text
        assert f"reason={opt['reason']}" in text


def test_render_warns_about_no_balance_check_on_manual_revoke():
    """POLICY §6.4 已知问题：手动扣分不校验余额。规则页必须明示。"""
    text = render_points_rules(_full_snapshot())
    assert "手动扣分不校验余额" in text or "可能产生负余额" in text


def test_render_cross_references_reimburse_rules_page():
    """避免内容漂移：报销门槛应说明"详见报销规则一览"。"""
    text = render_points_rules(_full_snapshot(reimburse_min_points=8))
    assert "8 分" in text
    assert "报销规则" in text


def test_render_cross_references_reconcile_section_for_balance():
    """余额一致性段引用 §6.2.3（积分异常对账）+ POLICY §7.2。"""
    text = render_points_rules(_full_snapshot())
    assert "users.total_points" in text
    assert "SUM(point_transactions.delta)" in text
    assert "§6.2.3" in text or "POLICY §7.2" in text


def test_render_n_a_fallback_for_empty_packages():
    snap = _full_snapshot(review_packages=[])
    text = render_points_rules(snap)
    assert "POINT_PACKAGE_OPTIONS 为空" in text


def test_render_n_a_fallback_for_empty_reason_options():
    snap = _full_snapshot(manual_reason_options=[])
    text = render_points_rules(snap)
    assert "POINT_GRANT_REASON_OPTIONS 为空" in text


def test_render_marks_readonly_in_header():
    text = render_points_rules(_full_snapshot())
    assert "只读" in text


def test_render_includes_timestamp():
    text = render_points_rules(_full_snapshot())
    assert "快照时间：2026-05-20 14:30:00" in text


# ============ get_points_rules_snapshot：monkeypatch ============


async def _stub_min_points():
    return 10


def test_get_snapshot_assembles_all_lists(monkeypatch):
    monkeypatch.setattr(svc_mod, "get_reimbursement_min_points", _stub_min_points)
    snap = _run(get_points_rules_snapshot())
    assert snap.review_packages == list(POINT_PACKAGE_OPTIONS)
    assert snap.manual_reason_options == list(POINT_GRANT_REASON_OPTIONS)
    assert snap.reason_catalog == list(REASON_CATALOG)
    assert snap.reimburse_min_points == 10
    assert snap.generated_at is not None


def test_get_snapshot_isolates_lists_from_module_constants(monkeypatch):
    """snapshot 内的 review_packages 应是浅拷贝；外部修改不影响模块常量。"""
    monkeypatch.setattr(svc_mod, "get_reimbursement_min_points", _stub_min_points)
    snap = _run(get_points_rules_snapshot())
    snap.review_packages.append({"key": "x", "label": "test", "delta": 999})
    # 模块常量未被修改
    assert all(p.get("key") != "x" for p in POINT_PACKAGE_OPTIONS)


def test_get_snapshot_handles_min_points_failure(monkeypatch):
    """get_reimbursement_min_points 抛异常 → 降级为 None，不影响其它字段。"""
    async def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(svc_mod, "get_reimbursement_min_points", _boom)
    snap = _run(get_points_rules_snapshot())
    assert snap.reimburse_min_points is None
    # 其它字段仍可用
    assert snap.review_packages == list(POINT_PACKAGE_OPTIONS)


def test_get_snapshot_handles_zero_min_points(monkeypatch):
    """min_points=0 是合法值（未启用门槛），不是 None。"""
    async def _zero():
        return 0
    monkeypatch.setattr(svc_mod, "get_reimbursement_min_points", _zero)
    snap = _run(get_points_rules_snapshot())
    assert snap.reimburse_min_points == 0
