"""抽奖参与对账（admin:lottery_reconcile）keyboard 契约测试。

测试范围：
    1. admin_dashboard_kb 默认（is_super=False）渲染 3 个看板 + 返回后台（既有口径）
    2. admin_dashboard_kb(is_super=True) 增加「📊 抽奖对账」第 4 按钮
    3. admin_lottery_reconcile_kb 空列表只有刷新 + 返回
    4. admin_lottery_reconcile_kb 多 item 每个生成 admin:lottery_reconcile:item:<lid>
    5. 平账活动按钮带 ✅，异常活动带 ⚠️
    6. admin_lottery_reconcile_detail_kb 仅含刷新与返回，不含"异常用户列表"按钮
    7. 所有 callback_data 长度 ≤ 64 字节（Telegram 限制）

不连接真实 Telegram；纯静态 keyboard 断言。
"""

from __future__ import annotations

from bot.keyboards.admin_kb import (
    admin_dashboard_kb,
    admin_lottery_reconcile_kb,
    admin_lottery_reconcile_detail_kb,
)
from bot.services.lottery_reconcile import LotteryReconcileItem


def _flatten(kb):
    return [b for row in kb.inline_keyboard for b in row]


def _callbacks(kb):
    return [b.callback_data for b in _flatten(kb)]


def _balanced_item(lid: int = 1, name: str = "平账活动") -> LotteryReconcileItem:
    return LotteryReconcileItem(
        id=lid, name=name, status="drawn",
        entry_cost_points=10, entry_count=5, winner_count=1,
        expected_deduct=50, actual_deduct=50, refunded=0, net_deduct=50, diff=0,
        anomaly_count_a=0, anomaly_count_b=0, anomaly_count_d=0,
        anomaly_users=0,
    )


def _diverging_item(lid: int = 2, name: str = "差异活动") -> LotteryReconcileItem:
    return LotteryReconcileItem(
        id=lid, name=name, status="active",
        entry_cost_points=10, entry_count=3, winner_count=0,
        expected_deduct=30, actual_deduct=20, refunded=0, net_deduct=20, diff=10,
        anomaly_count_a=1, anomaly_count_b=0, anomaly_count_d=0,
        anomaly_users=1,
    )


# ============ admin_dashboard_kb: 超管 / 非超管分支 ============


def test_admin_dashboard_kb_default_three_buttons_plus_back():
    """默认（非超管）不应出现「📊 抽奖对账」入口。"""
    kb = admin_dashboard_kb()
    cbs = _callbacks(kb)
    assert "admin:overview" in cbs
    assert "admin:reimbursement_pool" in cbs
    assert "admin:lottery_status" in cbs
    assert "menu:main" in cbs
    assert "admin:lottery_reconcile" not in cbs  # 普通管理员不可见
    # 共 4 按钮（3 看板 + 返回后台）
    assert len(_flatten(kb)) == 4


def test_admin_dashboard_kb_is_super_false_explicit():
    kb = admin_dashboard_kb(is_super=False)
    cbs = _callbacks(kb)
    assert "admin:lottery_reconcile" not in cbs
    assert len(_flatten(kb)) == 4


def test_admin_dashboard_kb_is_super_true_adds_reconcile_button():
    kb = admin_dashboard_kb(is_super=True)
    cbs = _callbacks(kb)
    assert "admin:overview" in cbs
    assert "admin:reimbursement_pool" in cbs
    assert "admin:lottery_status" in cbs
    assert "admin:lottery_reconcile" in cbs
    assert "menu:main" in cbs
    # 共 5 按钮（4 看板 + 返回后台）
    assert len(_flatten(kb)) == 5


def test_admin_dashboard_kb_reconcile_button_text_contains_label():
    kb = admin_dashboard_kb(is_super=True)
    texts = [b.text for b in _flatten(kb)]
    assert any("抽奖对账" in t for t in texts)


# ============ admin_lottery_reconcile_kb：列表 ============


def test_reconcile_list_empty_only_refresh_and_back():
    kb = admin_lottery_reconcile_kb([])
    cbs = _callbacks(kb)
    assert "admin:lottery_reconcile:refresh" in cbs
    assert "admin:dashboard" in cbs
    # 没有任何 item 按钮
    assert not any(c.startswith("admin:lottery_reconcile:item:") for c in cbs)
    assert len(_flatten(kb)) == 2


def test_reconcile_list_multiple_items_generate_item_callbacks():
    items = [_balanced_item(lid=10), _diverging_item(lid=20)]
    kb = admin_lottery_reconcile_kb(items)
    cbs = _callbacks(kb)
    assert "admin:lottery_reconcile:item:10" in cbs
    assert "admin:lottery_reconcile:item:20" in cbs
    assert "admin:lottery_reconcile:refresh" in cbs
    assert "admin:dashboard" in cbs


def test_reconcile_list_balanced_item_has_check_emoji():
    items = [_balanced_item(lid=10, name="春节抽奖")]
    kb = admin_lottery_reconcile_kb(items)
    item_button = next(
        b for b in _flatten(kb)
        if (b.callback_data or "").startswith("admin:lottery_reconcile:item:")
    )
    assert "✅" in item_button.text
    assert "#10" in item_button.text


def test_reconcile_list_diverging_item_has_warning_emoji():
    items = [_diverging_item(lid=20)]
    kb = admin_lottery_reconcile_kb(items)
    item_button = next(
        b for b in _flatten(kb)
        if (b.callback_data or "").startswith("admin:lottery_reconcile:item:")
    )
    assert "⚠️" in item_button.text
    assert "#20" in item_button.text


def test_reconcile_list_long_name_truncated_with_ellipsis():
    long_name = "活动" * 15  # 30 个中文字符
    items = [_balanced_item(lid=1, name=long_name)]
    kb = admin_lottery_reconcile_kb(items)
    item_button = next(
        b for b in _flatten(kb)
        if (b.callback_data or "").startswith("admin:lottery_reconcile:item:")
    )
    # 按钮 text 截断后含省略号
    assert "…" in item_button.text


# ============ admin_lottery_reconcile_detail_kb：详情 ============


def test_reconcile_detail_kb_only_refresh_and_back():
    item = _balanced_item(lid=42)
    kb = admin_lottery_reconcile_detail_kb(item)
    cbs = _callbacks(kb)
    assert "admin:lottery_reconcile:item:42:refresh" in cbs
    assert "admin:lottery_reconcile" in cbs
    assert len(_flatten(kb)) == 2


def test_reconcile_detail_kb_no_anomaly_users_button_yet():
    """§4.2.2 异常用户列表是下一个 PR；本 PR 不应提前出现。"""
    item = _diverging_item(lid=99)
    kb = admin_lottery_reconcile_detail_kb(item)
    cbs = _callbacks(kb)
    # 没有任何 anomaly / users / copy 类按钮
    assert not any("anomaly" in (c or "") for c in cbs)
    assert not any("copy" in (c or "") for c in cbs)


def test_reconcile_detail_kb_no_repair_buttons():
    """§4.3 禁止：不允许"修复 / 补偿 / 一键修正"按钮。"""
    item = _diverging_item(lid=99)
    kb = admin_lottery_reconcile_detail_kb(item)
    texts = " ".join(b.text for b in _flatten(kb))
    for forbidden in ("修复", "补偿", "修正", "一键", "退分", "扣分"):
        assert forbidden not in texts


# ============ callback_data 字节数限制 ============


def test_all_callbacks_within_telegram_limit():
    """Telegram 限 64 字节。"""
    items = [
        _balanced_item(lid=999999999),  # 最长 lid 边界
        _diverging_item(lid=888888888),
    ]
    targets = [
        admin_dashboard_kb(is_super=True),
        admin_lottery_reconcile_kb(items),
        admin_lottery_reconcile_detail_kb(items[0]),
    ]
    for kb in targets:
        for b in _flatten(kb):
            assert b.callback_data is not None
            assert len(b.callback_data.encode("utf-8")) <= 64, (
                f"callback_data 超 64B: {b.callback_data!r}"
            )
