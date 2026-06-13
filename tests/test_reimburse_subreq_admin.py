"""报销专用必关 - 管理员后台契约测试（静态契约 + keyboard）。

覆盖 spec 后台菜单 4 个点 + 安全 1 个：
    8. system_menu_kb 含 system:reimburse_subreq 入口
    9-10. 入口仅超管可见 / 普通管理员不可见
    11. 返回按钮指向 menu:system
    审计：添加 / 删除必须调 log_admin_audit
"""
from __future__ import annotations

import inspect


# ============ helpers ============


def _cbs(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def _texts_by_cb(kb) -> dict:
    return {b.callback_data: b.text for row in kb.inline_keyboard for b in row}


# ============ 1. admin_reimburse_config_kb 含入口（2026-05-20 修订） ============
# 原入口在 system_menu_kb；2026-05-20 起 menu:system 不再含报销类直入口，
# 唯一入口源是聚合页 admin:reimburse_config。


def test_admin_reimburse_config_kb_contains_reimburse_subreq_entry():
    """💰 报销配置聚合页必须含 system:reimburse_subreq 入口。"""
    from bot.keyboards.admin_kb import admin_reimburse_config_kb
    cbs = _cbs(admin_reimburse_config_kb())
    assert "system:reimburse_subreq" in cbs


def test_admin_reimburse_config_kb_reimburse_subreq_label_includes_keyword():
    """入口文案应含「报销」「必关」字样。"""
    from bot.keyboards.admin_kb import admin_reimburse_config_kb
    by_cb = _texts_by_cb(admin_reimburse_config_kb())
    text = by_cb["system:reimburse_subreq"]
    assert "报销" in text
    assert "必关" in text


def test_system_menu_kb_no_longer_has_reimburse_subreq_entry():
    """2026-05-20：menu:system 不再含 system:reimburse_subreq 直入口，
    避免与 admin:reimburse_config 聚合页重复（用户痛点：按钮重复）。"""
    from bot.keyboards.admin_kb import system_menu_kb
    cbs = _cbs(system_menu_kb())
    assert "system:reimburse_subreq" not in cbs


# ============ 2. 权限：仅超管 ============


def test_cb_reimburse_subreq_menu_uses_super_admin_required():
    """cb_reimburse_subreq_menu 必须用 @super_admin_required 装饰。"""
    import bot.handlers.reimburse_subreq_admin as mod
    src = inspect.getsource(mod)
    idx = src.find("async def cb_reimburse_subreq_menu(")
    assert idx > 0, "找不到 cb_reimburse_subreq_menu"
    window = src[max(0, idx - 300):idx]
    assert "@super_admin_required" in window


def test_all_admin_handlers_use_super_admin_required():
    """所有 system:reimburse_subreq:* handler 都必须超管限制。"""
    import bot.handlers.reimburse_subreq_admin as mod
    src = inspect.getsource(mod)
    for fn_name in (
        "cb_reimburse_subreq_menu",
        "cb_reimburse_subreq_delete_ask",
        "cb_reimburse_subreq_delete_confirm",
        "cb_reimburse_subreq_add_start",
        "step_reimburse_subreq_chat_id",
        "step_reimburse_subreq_display_name",
        "step_reimburse_subreq_invite_link",
        "cb_reimburse_subreq_add_confirm",
    ):
        idx = src.find(f"async def {fn_name}(")
        assert idx > 0, f"找不到 {fn_name}"
        window = src[max(0, idx - 300):idx]
        assert "@super_admin_required" in window, (
            f"{fn_name} 应使用 @super_admin_required 装饰"
        )


def test_admin_required_decorator_not_used():
    """报销 subreq 不能用 @admin_required（普通管理员）—— 必须 super_admin_required。"""
    import bot.handlers.reimburse_subreq_admin as mod
    src = inspect.getsource(mod)
    assert "@admin_required" not in src, (
        "报销 subreq handler 不应使用 @admin_required（普通管理员可见即漏权）"
    )


# ============ 3. Keyboard：返回路径正确 ============


def test_reimburse_subreq_menu_kb_back_button_to_menu_system():
    """主面板「⬅️ 返回」应指向 menu:system。"""
    from bot.keyboards.admin_kb import reimburse_subreq_menu_kb
    cbs = _cbs(reimburse_subreq_menu_kb([]))
    assert "menu:system" in cbs


def test_reimburse_subreq_menu_kb_empty_state():
    """空配置时主面板含 add / 刷新 / 返回 三个按钮。"""
    from bot.keyboards.admin_kb import reimburse_subreq_menu_kb
    kb = reimburse_subreq_menu_kb([])
    cbs = _cbs(kb)
    assert "system:reimburse_subreq:add" in cbs
    assert "system:reimburse_subreq" in cbs       # 刷新
    assert "menu:system" in cbs                    # 返回
    # 不应有 delete 按钮
    assert not any(c.startswith("system:reimburse_subreq:delete:") for c in cbs)


def test_reimburse_subreq_menu_kb_with_chats_shows_delete_per_item():
    """非空配置时每条显示一个 delete 按钮（带 idx）。"""
    from bot.keyboards.admin_kb import reimburse_subreq_menu_kb
    chats = [
        {"chat_id": -1001, "display_name": "A", "chat_type": "channel", "invite_link": "x", "enabled": True},
        {"chat_id": -1002, "display_name": "B", "chat_type": "group",   "invite_link": "x", "enabled": True},
    ]
    cbs = _cbs(reimburse_subreq_menu_kb(chats))
    assert "system:reimburse_subreq:delete:0" in cbs
    assert "system:reimburse_subreq:delete:1" in cbs


def test_reimburse_subreq_remove_confirm_kb_includes_idx():
    """删除二次确认 callback 含正确 idx。"""
    from bot.keyboards.admin_kb import reimburse_subreq_remove_confirm_kb
    cbs = _cbs(reimburse_subreq_remove_confirm_kb(idx=5))
    assert "system:reimburse_subreq:confirm_delete:5" in cbs
    assert "system:reimburse_subreq" in cbs  # 取消按钮回主菜单


def test_reimburse_subreq_add_confirm_kb_contains_confirm_and_cancel():
    """添加确认页含 add_confirm + 取消（回主菜单）。"""
    from bot.keyboards.admin_kb import reimburse_subreq_add_confirm_kb
    cbs = _cbs(reimburse_subreq_add_confirm_kb())
    assert "system:reimburse_subreq:add_confirm" in cbs
    assert "system:reimburse_subreq" in cbs


# ============ 4. Audit log 必写入 ============


def test_admin_handler_writes_audit_log_on_add():
    """添加确认后必须调 log_admin_audit。"""
    import bot.handlers.reimburse_subreq_admin as mod
    src = inspect.getsource(mod)
    idx = src.find("async def cb_reimburse_subreq_add_confirm(")
    assert idx > 0
    body = src[idx:idx + 3000]
    assert "log_admin_audit" in body
    assert "reimburse_subreq_add" in body


def test_admin_handler_writes_audit_log_on_remove():
    """删除确认后必须调 log_admin_audit。"""
    import bot.handlers.reimburse_subreq_admin as mod
    src = inspect.getsource(mod)
    idx = src.find("async def cb_reimburse_subreq_delete_confirm(")
    assert idx > 0
    body = src[idx:idx + 2500]
    assert "log_admin_audit" in body
    assert "reimburse_subreq_remove" in body


def test_admin_handler_uses_independent_fsm_states():
    """添加 FSM 使用独立 ReimburseSubReqAddStates，不复用全局 SubReqAddStates。"""
    import bot.handlers.reimburse_subreq_admin as mod
    src = inspect.getsource(mod)
    assert "ReimburseSubReqAddStates" in src
    # 不应 import / 使用全局 SubReqAddStates
    assert "SubReqAddStates" in src  # 由 import 的形式包含
    # 但实际 import 行应只 import 报销 FSM
    assert "from bot.states.teacher_states import ReimburseSubReqAddStates" in src
    assert "from bot.states.teacher_states import SubReqAddStates" not in src


# ============ 5. Router 已注册 ============


def test_reimburse_subreq_admin_router_importable():
    """router 仍可正常 import。"""
    from bot.handlers.reimburse_subreq_admin import router
    assert router is not None


def test_router_registered_in_routers_py():
    """routers.py 已注册 reimburse_subreq_admin_router。"""
    import bot.routers as routers_mod
    src = inspect.getsource(routers_mod)
    assert "reimburse_subreq_admin_router" in src
    assert "include_router(reimburse_subreq_admin_router)" in src


# ============ 6. Schema 与积分 / 抽奖 / 报销金额 不变 ============


def test_schema_migrations_baseline_unchanged():
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    from _migration_baseline import EXPECTED_MIGRATION_VERSIONS
    assert {m.version for m in MIGRATIONS} == EXPECTED_MIGRATION_VERSIONS


def test_compute_reimbursement_amount_callable():
    from bot.database import compute_reimbursement_amount
    assert callable(compute_reimbursement_amount)
