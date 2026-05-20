"""积分对账（admin:points_reconcile）keyboard 契约测试。

测试范围：
    1. admin_points_menu_kb 包含「📊 积分对账」入口
    2. admin_points_reconcile_overview_kb：
       - anomaly_users=0 → 仅刷新 + 返回
       - anomaly_users>0 → 含「📋 异常用户列表 (N)」入口
    3. admin_points_reconcile_anomaly_kb：4 分页边界（单页 / 首页 / 中间 / 末页）
    4. 防御性：无修正 / 修复 / 加扣分按钮（§6.3 禁止）
    5. callback_data ≤ 64 字节

不连接真实 Telegram；纯静态 keyboard 断言。
"""

from __future__ import annotations

from bot.keyboards.admin_kb import (
    admin_points_menu_kb,
    admin_points_reconcile_anomaly_kb,
    admin_points_reconcile_overview_kb,
)


def _flatten(kb):
    return [b for row in kb.inline_keyboard for b in row]


def _callbacks(kb):
    return [b.callback_data for b in _flatten(kb)]


# ============ admin_points_menu_kb：新增对账入口 ============


def test_menu_kb_has_reconcile_entry():
    kb = admin_points_menu_kb()
    cbs = _callbacks(kb)
    assert "admin:points_reconcile" in cbs


def test_menu_kb_reconcile_after_rules():
    """对账入口位于规则入口之后、子动作之前（Sprint 4 §6.1 "先只读"纪律）。"""
    kb = admin_points_menu_kb()
    rows = kb.inline_keyboard
    # 第一行：规则；第二行：对账
    assert rows[0][0].callback_data == "admin:points_rules"
    assert rows[1][0].callback_data == "admin:points_reconcile"
    # 之后才是查询/加分/总览
    assert rows[2][0].callback_data == "admin:points:query"


# ============ admin_points_reconcile_overview_kb ============


def test_overview_kb_no_anomaly_only_refresh_and_back():
    kb = admin_points_reconcile_overview_kb(anomaly_users=0)
    cbs = _callbacks(kb)
    assert "admin:points_reconcile:refresh" in cbs
    assert "admin:points" in cbs
    # 不显示异常列表入口
    assert not any(
        (c or "").startswith("admin:points_reconcile:anomaly:")
        for c in cbs
    )
    assert len(_flatten(kb)) == 2


def test_overview_kb_anomaly_shows_list_button_with_count():
    kb = admin_points_reconcile_overview_kb(anomaly_users=5)
    cbs = _callbacks(kb)
    assert "admin:points_reconcile:anomaly:1" in cbs
    texts = [b.text for b in _flatten(kb)]
    assert any("异常用户列表" in t and "(5)" in t for t in texts)
    # 仍有刷新 + 返回
    assert "admin:points_reconcile:refresh" in cbs
    assert "admin:points" in cbs


def test_overview_kb_no_repair_buttons():
    """§6.3 禁止：对账概览不允许出现任何修正 / 修复 / 加扣分按钮。"""
    kb = admin_points_reconcile_overview_kb(anomaly_users=10)
    cbs = _callbacks(kb)
    for cb in cbs:
        assert "admin:points:grant" not in (cb or "")
    texts = " ".join(b.text for b in _flatten(kb))
    for forbidden in ("修正", "修复", "补偿", "一键", "加分", "扣分", "导出"):
        assert forbidden not in texts


# ============ admin_points_reconcile_anomaly_kb：4 分页边界 ============


def test_anomaly_kb_single_page_no_prev_no_next():
    kb = admin_points_reconcile_anomaly_kb(page=1, total_pages=1)
    cbs = _callbacks(kb)
    texts = [b.text for b in _flatten(kb)]
    assert "admin:points_reconcile:anomaly:1" in cbs  # 刷新当前
    assert "admin:points_reconcile" in cbs  # 返回概览
    assert not any("上一页" in t for t in texts)
    assert not any("下一页" in t for t in texts)


def test_anomaly_kb_first_page_has_next_no_prev():
    kb = admin_points_reconcile_anomaly_kb(page=1, total_pages=3)
    cbs = _callbacks(kb)
    texts = [b.text for b in _flatten(kb)]
    assert "admin:points_reconcile:anomaly:2" in cbs
    assert any("下一页" in t for t in texts)
    assert not any("上一页" in t for t in texts)


def test_anomaly_kb_middle_page_has_both():
    kb = admin_points_reconcile_anomaly_kb(page=2, total_pages=3)
    cbs = _callbacks(kb)
    texts = [b.text for b in _flatten(kb)]
    assert "admin:points_reconcile:anomaly:1" in cbs  # prev
    assert "admin:points_reconcile:anomaly:3" in cbs  # next
    assert any("上一页" in t for t in texts)
    assert any("下一页" in t for t in texts)


def test_anomaly_kb_last_page_has_prev_no_next():
    kb = admin_points_reconcile_anomaly_kb(page=3, total_pages=3)
    cbs = _callbacks(kb)
    texts = [b.text for b in _flatten(kb)]
    assert "admin:points_reconcile:anomaly:2" in cbs
    assert any("上一页" in t for t in texts)
    assert not any("下一页" in t for t in texts)


def test_anomaly_kb_back_button_targets_overview():
    kb = admin_points_reconcile_anomaly_kb(page=1, total_pages=1)
    cbs = _callbacks(kb)
    assert "admin:points_reconcile" in cbs


def test_anomaly_kb_no_repair_buttons():
    """§6.3 禁止：异常列表也不允许修正/修复/加扣分按钮。"""
    kb = admin_points_reconcile_anomaly_kb(page=2, total_pages=5)
    cbs = _callbacks(kb)
    for cb in cbs:
        assert "admin:points:grant" not in (cb or "")
    texts = " ".join(b.text for b in _flatten(kb))
    for forbidden in ("修正", "修复", "补偿", "一键", "加分", "扣分", "导出"):
        assert forbidden not in texts


def test_all_callbacks_within_telegram_limit():
    """callback_data 字节数限制：64B。"""
    targets = [
        admin_points_menu_kb(),
        admin_points_reconcile_overview_kb(anomaly_users=99999),
        admin_points_reconcile_anomaly_kb(page=1, total_pages=1),
        admin_points_reconcile_anomaly_kb(page=999, total_pages=999),
    ]
    for kb in targets:
        for b in _flatten(kb):
            assert b.callback_data is not None
            assert len(b.callback_data.encode("utf-8")) <= 64
