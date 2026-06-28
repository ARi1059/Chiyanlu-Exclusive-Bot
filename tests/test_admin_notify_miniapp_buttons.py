"""审核类 bot 通知的「📲 打开小程序处理」按钮契约（阶段1）。

三类审核通知点开直达 MiniApp 管理台(startapp=admin)；同时保留 bot 内审核入口
(向后兼容)。helper miniapp_admin_url_button 缺 username 时返回 None。
"""
from __future__ import annotations


def _flat(kb):
    return [b for row in kb.inline_keyboard for b in row]


def test_miniapp_admin_url_button_helper():
    from bot.keyboards.common_kb import miniapp_admin_url_button
    assert miniapp_admin_url_button(None) is None
    assert miniapp_admin_url_button("") is None
    btn = miniapp_admin_url_button("mybot")
    assert btn.url == "https://t.me/mybot?startapp=admin"
    assert "小程序" in btn.text


def test_rreview_push_kb_has_miniapp_and_keeps_callback():
    from bot.keyboards.admin_kb import rreview_push_action_kb
    # 有 username：含小程序深链 + 保留 bot 审核入口
    cbs = [(b.url or b.callback_data) for b in _flat(rreview_push_action_kb("mybot"))]
    assert any("startapp=admin" in (c or "") for c in cbs)
    assert "rreview:enter" in cbs
    # 无 username：仅保留 bot 入口（不崩、graceful）
    cbs2 = [(b.url or b.callback_data) for b in _flat(rreview_push_action_kb(None))]
    assert not any("startapp=admin" in (c or "") for c in cbs2)
    assert "rreview:enter" in cbs2


def test_reimburse_notice_kb_has_miniapp_and_keeps_callbacks():
    from bot.keyboards.admin_kb import reimburse_pending_super_notice_kb
    cbs = [(b.url or b.callback_data) for b in _flat(reimburse_pending_super_notice_kb("mybot"))]
    assert any("startapp=admin" in (c or "") for c in cbs)
    assert "reimburse:enter" in cbs        # bot 内入口保留
    assert "admin:review_tasks" in cbs
    # 无参（旧调用）仍正常：保留两 callback、无小程序按钮
    cbs2 = [(b.url or b.callback_data) for b in _flat(reimburse_pending_super_notice_kb())]
    assert "reimburse:enter" in cbs2 and "admin:review_tasks" in cbs2
    assert not any("startapp=admin" in (c or "") for c in cbs2)
