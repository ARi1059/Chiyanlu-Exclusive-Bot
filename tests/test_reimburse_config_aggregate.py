"""Sprint UX-6 第二项（UX-6.2）：报销配置二级菜单聚合契约测试。

范围：
    - bot.keyboards.admin_kb.admin_reimburse_config_kb 新增聚合 keyboard
    - bot.keyboards.admin_kb.admin_settings_kb 在 is_super 区域新增聚合入口
    - bot.handlers.admin_panel.cb_admin_reimburse_config 新增 handler

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §4.2 痛点 11 + §7.2 痛点 8 + §11.3）：
    把原来散在 admin:settings 主面板（2 项）+ menu:system 子面板（5 项中其余 3 项）
    的 5 个报销配置入口收纳到一个聚合页：
        - 🔛 报销功能开关       system:reimburse_toggle
        - 💰 报销池设置         system:reimburse_pool
        - 🔄 重置本月报销池     system:reimburse_pool_reset
        - 🎚 报销门槛设置       system:reimburse_min_points
        - 📋 报销必关设置       system:reimburse_subreq

约束（与 PLAN §1.2 一致）：
    - **不删除任何旧入口**：admin:settings 主面板的两个 super-only 按钮 +
      menu:system 内的 5 项报销入口全部保留至少一个 Sprint 双跑期
    - 不改任何 callback_data（聚合页 5 个按钮全部复用既有 system:reimburse_* 命名空间）
    - 不引入 schema 迁移
    - 仅超管可访问（callback handler 在 admin_required 之上多 1 层 is_super 守卫）
"""
from __future__ import annotations

import inspect

import pytest  # noqa: F401


# ============ helpers ============


def _src(module) -> str:
    return inspect.getsource(module)


def _flat_buttons(kb) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            out.append(btn)
    return out


# ============================================================
# 1. admin_reimburse_config_kb keyboard 契约
# ============================================================


def test_kb_contains_all_5_reimburse_callbacks():
    """聚合页应含 5 个报销配置 callback 入口（顺序 + 字面量）。"""
    from bot.keyboards.admin_kb import admin_reimburse_config_kb
    kb = admin_reimburse_config_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    for expected in (
        "system:reimburse_toggle",
        "system:reimburse_pool",
        "system:reimburse_pool_reset",
        "system:reimburse_min_points",
        "system:reimburse_subreq",
    ):
        assert expected in cbs, f"missing callback: {expected}"


def test_kb_has_return_to_settings():
    """末行返回按钮指向 admin:settings（二级父页），不是 menu:main。"""
    from bot.keyboards.admin_kb import admin_reimburse_config_kb
    kb = admin_reimburse_config_kb()
    last_row_cbs = [b.callback_data for b in kb.inline_keyboard[-1]]
    assert "admin:settings" in last_row_cbs
    assert "menu:main" not in last_row_cbs


def test_kb_reuses_existing_callbacks_only():
    """所有 callback 全部复用既有 system:reimburse_* / admin:settings；
    Sprint 3 §5.2.1 新增 admin:reimburse_rules（只读规则页）也属于报销命名空间。

    防御性：不允许出现其它命名空间的新 callback。"""
    from bot.keyboards.admin_kb import admin_reimburse_config_kb
    kb = admin_reimburse_config_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    allowed_prefixes = ("system:reimburse_", "admin:reimburse_rules")
    for cb in cbs:
        assert (
            cb == "admin:settings"
            or any(cb.startswith(p) for p in allowed_prefixes)
        ), f"unexpected callback {cb}"


def test_kb_button_count():
    """聚合页共 8 个按钮（1 只读规则 + 6 项编辑配置 + 1 返回）。

    2026-05-20 修订：评价 footer 文本 / 链接（system:reimburse_promo_text /
    _url）已迁回 menu:system「系统设置」面板（属评价文案全局配置，与报销
    功能本身解耦），本聚合页不再包含。

    现有 6 项编辑配置 =
      旧 5 项（toggle / pool / pool_reset / min_points / subreq）
      + 2026-05 新增 1 项（weekly_limit）。"""
    from bot.keyboards.admin_kb import admin_reimburse_config_kb
    kb = admin_reimburse_config_kb()
    assert len(_flat_buttons(kb)) == 8


def test_kb_first_button_is_readonly_rules_view():
    """Sprint 3 §5.2.1：只读规则一览作为第一按钮，引导用户先看现状再决定编辑。"""
    from bot.keyboards.admin_kb import admin_reimburse_config_kb
    kb = admin_reimburse_config_kb()
    first_row = kb.inline_keyboard[0]
    assert first_row[0].callback_data == "admin:reimburse_rules"
    assert "完整规则" in first_row[0].text or "规则一览" in first_row[0].text


# ============================================================
# 2. admin_settings_kb 增加聚合入口（仅 super）
# ============================================================


def test_admin_settings_kb_super_has_aggregate_entry():
    """super 视角下 admin_settings_kb 含 [admin:reimburse_config] 入口。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    kb = admin_settings_kb(is_super=True)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "admin:reimburse_config" in cbs


def test_admin_settings_kb_non_super_no_aggregate_entry():
    """普通管理员视角下 admin_settings_kb 不应含报销聚合入口（与原 super-only 一致）。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    kb = admin_settings_kb(is_super=False)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "admin:reimburse_config" not in cbs
    # 旧 super-only 报销按钮也不应出现
    assert "system:reimburse_pool" not in cbs
    assert "system:reimburse_toggle" not in cbs


def test_admin_settings_kb_super_no_longer_has_overlapping_reimburse_entries():
    """2026-05 修订：admin_settings_kb 顶部原本含 system:reimburse_pool /
    system:reimburse_toggle 两并列入口，与 admin:reimburse_config 聚合页
    入口重叠。本批已删除两个直入口；callback handler 仍保留兼容旧
    inline button（在历史会话中点旧按钮仍可工作）。

    历史 PLAN §1.2「不破坏旧入口」+ §11.3「旧入口保留双跑期」契约由
    callback handler 自身的存在性满足，UI 入口的去重并不违反这一契约。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    kb = admin_settings_kb(is_super=True)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    # 聚合入口必在
    assert "admin:reimburse_config" in cbs
    # 两个直入口应已被撤除
    assert "system:reimburse_pool" not in cbs
    assert "system:reimburse_toggle" not in cbs


# ============================================================
# 3. menu:system 子面板里的 5 项报销入口已下线（2026-05-20 修订）
# ============================================================


def test_system_menu_kb_no_longer_has_reimburse_entries():
    """2026-05-20 修订：menu:system 内的 5 项报销 callback 已被移除，
    聚合页 admin:reimburse_config 是唯一入口源；callback handler 本身
    保留兼容，旧 inline button 仍可工作。"""
    from bot.keyboards.admin_kb import system_menu_kb
    cbs = [b.callback_data for b in _flat_buttons(system_menu_kb())]
    for removed in (
        "system:reimburse_pool",
        "system:reimburse_toggle",
        "system:reimburse_min_points",
        "system:reimburse_pool_reset",
        "system:reimburse_subreq",
    ):
        assert removed not in cbs, (
            f"{removed} 应已从 system_menu_kb 移除，避免与 admin:reimburse_config 聚合页重复"
        )


# ============================================================
# 4. cb_admin_reimburse_config handler 静态契约
# ============================================================


def test_handler_registered():
    """admin:reimburse_config callback handler 应在 admin_panel.py 注册。"""
    import bot.handlers.admin_panel as mod
    src = _src(mod)
    assert 'F.data == "admin:reimburse_config"' in src


def test_handler_uses_aggregate_kb():
    """handler 应渲染 admin_reimburse_config_kb 聚合页。"""
    import bot.handlers.admin_panel as mod
    src = _src(mod)
    idx = src.find("async def cb_admin_reimburse_config(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "admin_reimburse_config_kb" in body


def test_handler_has_super_admin_guard():
    """handler 必须做 is_super 守卫（非超管访问应被拒）。"""
    import bot.handlers.admin_panel as mod
    src = _src(mod)
    idx = src.find("async def cb_admin_reimburse_config(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    # 应含 is_super 判断
    assert "is_super" in body
    # 非超管应 callback.answer 提示
    assert "仅超管" in body or "show_alert=True" in body


def test_handler_shows_4_status_lines():
    """聚合页应显示 4 个关键状态总览（功能开关 / 门槛 / 池 / queued）。"""
    import bot.handlers.admin_panel as mod
    src = _src(mod)
    idx = src.find("async def cb_admin_reimburse_config(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "reimbursement_feature_enabled" in body
    assert "get_reimbursement_min_points" in body
    assert "reimbursement_monthly_pool" in body
    assert "count_queued_reimbursements" in body


def test_handler_status_queries_swallow_exceptions():
    """关键状态查询应有容错（try/except），单项查询失败不应阻塞聚合页渲染。"""
    import bot.handlers.admin_panel as mod
    src = _src(mod)
    idx = src.find("async def cb_admin_reimburse_config(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    # 至少出现 2 个 try/except 块（min_points + queued_count 都易失败）
    assert body.count("try:") >= 2
    assert body.count("except") >= 2


# ============================================================
# 5. 既有 5 个 callback handler 未被本批改动（行为保护）
# ============================================================


def test_existing_reimburse_handlers_still_registered():
    """既有 5 个 system:reimburse_* callback handler 在各自原文件中仍注册。"""
    import bot.handlers.admin_panel as ap
    import bot.handlers.reimburse_settings_admin as rsa
    import bot.handlers.reimburse_subreq_admin as rsa2
    ap_src = _src(ap)
    rsa_src = _src(rsa)
    rsa2_src = _src(rsa2)
    # admin_panel.py 处理 reimburse_pool / reimburse_toggle
    assert 'F.data == "system:reimburse_pool"' in ap_src
    assert 'F.data == "system:reimburse_toggle"' in ap_src
    # reimburse_settings_admin.py 处理 min_points / pool_reset
    assert 'F.data == "system:reimburse_min_points"' in rsa_src
    assert 'F.data == "system:reimburse_pool_reset"' in rsa_src
    # reimburse_subreq_admin.py 处理 subreq
    assert 'F.data == "system:reimburse_subreq"' in rsa2_src


# ============================================================
# 6. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable", "20260613_001_teacher_is_deleted", "20260613_002_remove_quick_entry_keywords"}
