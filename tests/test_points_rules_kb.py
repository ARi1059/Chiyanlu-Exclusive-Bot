"""积分规则只读页（admin:points_rules）keyboard 契约测试。

测试范围：
    1. admin_points_menu_kb 顶部新增「📜 积分规则一览」入口
    2. admin_points_rules_kb 只含刷新 + 返回积分管理
    3. 不含任何编辑 / 加扣分按钮（§6.3 禁止）
    4. callback_data 长度 ≤ 64 字节
"""

from __future__ import annotations

from bot.keyboards.admin_kb import (
    admin_points_menu_kb,
    admin_points_rules_kb,
)


def _flatten(kb):
    return [b for row in kb.inline_keyboard for b in row]


def _callbacks(kb):
    return [b.callback_data for b in _flatten(kb)]


# ============ admin_points_menu_kb：新增只读入口 ============


def test_admin_points_menu_kb_has_rules_entry():
    kb = admin_points_menu_kb()
    cbs = _callbacks(kb)
    assert "admin:points_rules" in cbs


def test_admin_points_menu_kb_rules_is_first_row():
    """§6.1 原则「优先做只读」：规则入口应在子动作之前。"""
    kb = admin_points_menu_kb()
    first_row = kb.inline_keyboard[0]
    assert first_row[0].callback_data == "admin:points_rules"
    assert "积分规则" in first_row[0].text or "规则一览" in first_row[0].text


def test_admin_points_menu_kb_button_count_now_six():
    """规则一览 + 对账 + 查询 + 加分 + 总览 + 返回 = 6 按钮（Sprint 4 §6.2.3 加入对账入口）。"""
    kb = admin_points_menu_kb()
    assert len(_flatten(kb)) == 6


# ============ admin_points_rules_kb ============


def test_rules_kb_only_refresh_and_back():
    kb = admin_points_rules_kb()
    cbs = _callbacks(kb)
    assert "admin:points_rules:refresh" in cbs
    assert "admin:points" in cbs
    assert len(_flatten(kb)) == 2


def test_rules_kb_no_edit_buttons():
    """§6.3 禁止：积分规则只读页不允许出现任何加扣分入口。"""
    kb = admin_points_rules_kb()
    cbs = _callbacks(kb)
    for cb in cbs:
        assert "admin:points:grant" not in (cb or "")
        assert "admin:points:query" not in (cb or "")
        assert "admin:points:overview" not in (cb or "")
    texts = " ".join(b.text for b in _flatten(kb))
    for forbidden in ("加分", "扣分", "修改", "编辑", "调整", "修复"):
        assert forbidden not in texts


def test_rules_kb_callbacks_within_telegram_limit():
    kb = admin_points_rules_kb()
    for b in _flatten(kb):
        assert b.callback_data is not None
        assert len(b.callback_data.encode("utf-8")) <= 64
