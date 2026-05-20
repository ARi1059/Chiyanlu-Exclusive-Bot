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
    _announce_min_points_line,
    _announce_pool_line,
    _announce_required_chats_line,
    _fmt_feature,
    _fmt_min_points,
    _fmt_pool,
    _fmt_queued_mode,
    _fmt_required_chats,
    _parse_monthly_pool,
    get_reimbursement_rules_snapshot,
    render_reimbursement_announcement_draft,
    render_reimbursement_rules,
    wrap_announcement_html,
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


# ============ §5.2.3 公告草稿生成 ============


def _announce_snap(**overrides) -> ReimbursementRulesSnapshot:
    base = ReimbursementRulesSnapshot(
        feature_enabled=True,
        monthly_pool=3000,
        current_month_key="2026-05",
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


# ---- _announce_*_line helpers ----


def test_announce_pool_line_branches():
    assert "配置未设置" in _announce_pool_line(_announce_snap(monthly_pool=None))
    assert "不限额度" in _announce_pool_line(_announce_snap(monthly_pool=0))
    assert "3000 元" in _announce_pool_line(_announce_snap(monthly_pool=3000))


def test_announce_min_points_line_branches():
    assert "配置未设置" in _announce_min_points_line(
        _announce_snap(min_points=None),
    )
    assert "无门槛" in _announce_min_points_line(_announce_snap(min_points=0))
    assert "10 分" in _announce_min_points_line(_announce_snap(min_points=10))


def test_announce_required_chats_line_branches():
    s_none = _announce_snap(required_chats_total=None, required_chats_enabled=None)
    assert "配置未设置" in _announce_required_chats_line(s_none)

    s_zero = _announce_snap(required_chats_total=0, required_chats_enabled=0)
    assert "无" in _announce_required_chats_line(s_zero)
    assert "不拦截" in _announce_required_chats_line(s_zero)

    # total > 0 但 enabled = 0 应视为"无"（不会拦截）
    s_disabled = _announce_snap(required_chats_total=3, required_chats_enabled=0)
    assert "无" in _announce_required_chats_line(s_disabled)

    s_some = _announce_snap(required_chats_total=5, required_chats_enabled=3)
    line = _announce_required_chats_line(s_some)
    assert "3 个" in line
    assert "请确保已加入" in line


# ---- 公告标题与首段：feature_enabled 三态 ----


def test_announce_feature_on_title_and_opening():
    text = render_reimbursement_announcement_draft(_announce_snap(feature_enabled=True))
    assert "【报销规则公告】2026-05-20" in text
    assert "已开放" in text
    # 不应误用关闭态的措辞
    assert "暂未开放" not in text


def test_announce_feature_off_title_and_opening():
    text = render_reimbursement_announcement_draft(_announce_snap(feature_enabled=False))
    assert "【报销暂未开放】2026-05-20" in text
    assert "queued" in text  # 名单留底说明
    assert "由超管激活" in text


def test_announce_feature_none_marks_internal_only():
    text = render_reimbursement_announcement_draft(_announce_snap(feature_enabled=None))
    assert "配置异常" in text
    assert "不应直接发布给用户" in text


# ---- 公告内容：全部规则要点出现 ----


def test_announce_contains_all_rule_bullets():
    text = render_reimbursement_announcement_draft(_announce_snap())
    assert "3000 元" in text
    assert "10 分" in text
    assert "每用户每周最多 1 次" in text
    assert "2 个" in text


def test_announce_weekly_limit_uses_constant():
    """公告中的"每周最多 N 次"必须读自 snap，不应硬编码 1。"""
    snap = _announce_snap()
    snap.weekly_approved_limit = 2  # 假设未来 config 化
    text = render_reimbursement_announcement_draft(snap)
    assert "每用户每周最多 2 次" in text


def test_announce_no_emoji_decoration():
    """公告应无 emoji 装饰，便于粘贴到群里复制。"""
    text = render_reimbursement_announcement_draft(_announce_snap())
    for emoji in ("📜", "📊", "🎲", "💰", "✅", "⚠️", "📋"):
        assert emoji not in text


def test_announce_no_technical_fields():
    """公告面向用户，不应包含 month_key / week_key / baseline 等技术字段。"""
    text = render_reimbursement_announcement_draft(_announce_snap(
        current_month_reset_baseline=500,
    ))
    assert "month_key" not in text
    assert "week_key" not in text
    assert "baseline" not in text
    assert "2026-W21" not in text


def test_announce_includes_timestamp_for_version_tracking():
    """公告底部应带生成时间戳，提示是某一时间点的快照。"""
    text = render_reimbursement_announcement_draft(_announce_snap())
    assert "2026-05-20 14:30:00" in text
    assert "重新生成" in text


def test_announce_explains_reset_voucher_in_user_friendly_terms():
    """reset voucher 在用户公告中应有简单解释，不直接用'voucher'裸词。"""
    text = render_reimbursement_announcement_draft(_announce_snap())
    assert "额外审批名额" in text or "reset voucher" in text


def test_announce_text_within_telegram_limit():
    """公告纯文本应远低于 4096 字节限制（Telegram 消息上限）。"""
    text = render_reimbursement_announcement_draft(_announce_snap())
    assert len(text.encode("utf-8")) < 2000


# ---- wrap_announcement_html: HTML escape + <pre> 包裹 ----


def test_wrap_announcement_html_pre_block():
    wrapped = wrap_announcement_html("hello")
    assert wrapped.startswith("<pre>")
    assert wrapped.endswith("</pre>")
    assert "hello" in wrapped


def test_wrap_announcement_html_escapes_special_chars():
    wrapped = wrap_announcement_html("a < b & c > d")
    assert "&lt;" in wrapped
    assert "&gt;" in wrapped
    assert "&amp;" in wrapped
    # 内层不含原始 < / > / & 字符
    inner = wrapped[len("<pre>"):-len("</pre>")]
    assert "<" not in inner
    assert ">" not in inner


def test_wrap_announcement_html_safe_with_full_draft():
    """完整公告草稿包装后应是合法 HTML（无未转义的 < / >）。"""
    text = render_reimbursement_announcement_draft(_announce_snap())
    wrapped = wrap_announcement_html(text)
    inner = wrapped[len("<pre>"):-len("</pre>")]
    assert "<" not in inner
    assert ">" not in inner
