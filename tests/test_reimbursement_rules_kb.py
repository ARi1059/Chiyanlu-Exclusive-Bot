"""报销规则只读页（admin:reimburse_rules）keyboard 契约测试。

测试范围：
    1. admin_reimburse_rules_kb 只含刷新 + 返回报销配置
    2. 不含任何编辑 / 配置类按钮（§5.3 禁止）
    3. callback_data 长度 ≤ 64 字节

不连接真实 Telegram；纯静态 keyboard 断言。
"""

from __future__ import annotations

from bot.keyboards.admin_kb import admin_reimburse_rules_kb


def _flatten(kb):
    return [b for row in kb.inline_keyboard for b in row]


def _callbacks(kb):
    return [b.callback_data for b in _flatten(kb)]


def test_rules_kb_contains_refresh_and_back():
    """规则页必含刷新 + 返回报销配置。"""
    kb = admin_reimburse_rules_kb()
    cbs = _callbacks(kb)
    assert "admin:reimburse_rules:refresh" in cbs
    assert "admin:reimburse_config" in cbs


def test_rules_kb_contains_announce_button():
    """§5.2.3：规则页必含「📢 复制公告草稿」按钮。"""
    kb = admin_reimburse_rules_kb()
    cbs = _callbacks(kb)
    assert "admin:reimburse_announce" in cbs
    texts = [b.text for b in _flatten(kb)]
    assert any("公告草稿" in t for t in texts)


def test_rules_kb_button_total_count():
    """规则页共 3 按钮：1 公告草稿 + 1 刷新 + 1 返回。"""
    kb = admin_reimburse_rules_kb()
    assert len(_flatten(kb)) == 3


def test_rules_kb_no_edit_buttons():
    """§5.3 禁止：只读页不允许出现任何编辑入口，避免误导。"""
    kb = admin_reimburse_rules_kb()
    cbs = _callbacks(kb)
    for cb in cbs:
        assert not cb.startswith("system:reimburse_"), (
            f"只读页不应直接跳到编辑入口: {cb}"
        )
    texts = " ".join(b.text for b in _flatten(kb))
    for forbidden in ("修改", "编辑", "调整", "设置"):
        assert forbidden not in texts


def test_rules_kb_callbacks_within_telegram_limit():
    kb = admin_reimburse_rules_kb()
    for b in _flatten(kb):
        assert b.callback_data is not None
        assert len(b.callback_data.encode("utf-8")) <= 64
