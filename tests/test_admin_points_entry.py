"""「💰 积分管理」后台入口契约测试。

背景：
    本审查发现 `admin_points.py`（Phase P.3）已完整实现，且 `admin_operations_kb`
    第 171 行已含 `[💰 积分管理] → admin:points`。本批**不修改任何代码**，仅用
    集中契约测试锁定现状，防止后续误改导致入口丢失或权限漂移。

现状（已有，未触动）：
    - `bot/handlers/admin_points.py` —— 609 行；含子菜单 / 查询 / 手动加扣分
      （4 步 FSM + 二次确认 + audit log）/ 总览
    - `bot/keyboards/admin_kb.py`:
        - admin_operations_kb()  第 171 行 [💰 积分管理] → admin:points
        - admin_points_menu_kb() 三个子入口（query / grant / overview）+ 返回 admin:operations
        - admin_points_back_kb / cancel_kb / grant_value_kb / grant_minus_kb /
          grant_reason_kb / grant_confirm_kb 全部就绪
    - callback 命名空间：admin:points / admin:points:query / admin:points:grant
      / admin:points:overview / admin:points:grant_v:* / admin:points:grant_m:* /
      admin:points:grant_r:* / admin:points:grant_ok / admin:points:grant_cancel

权限边界：
    - admin:operations (admin_operations_kb 自身) → @super_admin_required（手动审查
      cb_admin_operations 装饰器）
    - admin:points  → @_super_admin_required（admin_points.py 自定义装饰器）
    - admin:points:grant 等子动作均超管专属

不连接真实 Telegram；不访问生产 DB；纯静态 / keyboard 断言。
"""

from __future__ import annotations

import inspect


# ============ helpers ============


def _cbs(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def _texts_by_cb(kb) -> dict:
    return {b.callback_data: b.text for row in kb.inline_keyboard for b in row}


# ============ 1. admin_operations_kb 含 [💰 积分管理] 入口 ============


def test_admin_operations_kb_contains_points_entry():
    """admin_operations_kb 必须含 admin:points 入口 + 「💰 积分管理」文案。"""
    from bot.keyboards.admin_kb import admin_operations_kb
    kb = admin_operations_kb()
    cbs = _cbs(kb)
    assert "admin:points" in cbs, "admin_operations_kb 缺少 admin:points 入口"
    by_cb = _texts_by_cb(kb)
    text = by_cb["admin:points"]
    assert "积分管理" in text, f"admin:points 按钮文案应含「积分管理」，实际：{text}"
    assert "💰" in text, f"admin:points 按钮文案应含 💰，实际：{text}"


def test_admin_operations_kb_lottery_and_points_coexist():
    """admin_operations_kb 同时含 抽奖管理 + 积分管理（两类活动运营入口并列）。"""
    from bot.keyboards.admin_kb import admin_operations_kb
    cbs = _cbs(admin_operations_kb())
    assert "admin:lottery" in cbs
    assert "admin:points" in cbs


# ============ 2. admin:points handler 存在且超管限制 ============


def test_cb_admin_points_handler_exists():
    """admin_points.py 必须含 admin:points handler 字面量 + cb_admin_points 函数。"""
    import bot.handlers.admin_points as ap
    src = inspect.getsource(ap)
    assert '"admin:points"' in src, "admin_points.py 缺少 admin:points callback"
    assert "cb_admin_points" in src, "admin_points.py 缺少 cb_admin_points 函数"


def test_admin_points_handler_uses_super_admin_required():
    """cb_admin_points 必须使用超管装饰器（防止普通管理员访问积分管理）。"""
    import bot.handlers.admin_points as ap
    src = inspect.getsource(ap)
    idx = src.find("async def cb_admin_points(")
    assert idx > 0, "找不到 cb_admin_points 定义"
    # 装饰器在函数定义前一段窗口内
    window = src[max(0, idx - 300):idx]
    assert "_super_admin_required" in window, (
        "cb_admin_points 应使用 _super_admin_required 装饰器"
    )


def test_admin_points_router_importable():
    """admin_points.router 仍可正常 import。"""
    from bot.handlers.admin_points import router
    assert router is not None


# ============ 3. admin_points_menu_kb 子入口完整 ============


def test_admin_points_menu_kb_contains_three_actions():
    """积分管理主面板含三个子动作 + 返回活动运营。"""
    from bot.keyboards.admin_kb import admin_points_menu_kb
    cbs = _cbs(admin_points_menu_kb())
    assert "admin:points:query" in cbs       # 查询用户积分
    assert "admin:points:grant" in cbs       # 手动加分（FSM）
    assert "admin:points:overview" in cbs    # 积分总览


def test_admin_points_menu_kb_back_button_to_operations():
    """积分管理主面板返回按钮指向 admin:operations（UX-1 第二批返回路径优化）。"""
    from bot.keyboards.admin_kb import admin_points_menu_kb
    cbs = _cbs(admin_points_menu_kb())
    assert "admin:operations" in cbs, (
        "积分管理主面板返回按钮应指向 admin:operations"
    )
    # 不应回到 menu:main（UX-1 已下沉）
    assert "menu:main" not in cbs


def test_admin_points_menu_kb_button_texts_match():
    """子动作按钮文案匹配各自含义。"""
    from bot.keyboards.admin_kb import admin_points_menu_kb
    by_cb = _texts_by_cb(admin_points_menu_kb())
    assert "查询" in by_cb["admin:points:query"]
    assert "加分" in by_cb["admin:points:grant"] or "扣分" in by_cb["admin:points:grant"]
    assert "总览" in by_cb["admin:points:overview"]
    assert "返回" in by_cb["admin:operations"]


# ============ 4. 现有手动加扣分功能完整（仅静态契约，不调用） ============


def test_admin_points_grant_handlers_exist():
    """手动加扣分功能在 admin_points.py 中完整存在（4 步 FSM + 二次确认）。

    本批不实现也不修改手动加扣分；仅锁定现状，防止后续误删。
    """
    import bot.handlers.admin_points as ap
    src = inspect.getsource(ap)
    # 4 步 FSM 关键 callback 均应在源码中
    for cb in (
        '"admin:points:grant"',           # 入口
        '"admin:points:grant_ok"',        # 确认提交
        '"admin:points:grant_cancel"',    # 取消
    ):
        assert cb in src, f"admin_points.py 缺少 {cb}"


def test_admin_points_grant_supports_audit_log():
    """手动加扣分必须写入 admin_audit_logs（spec 强制要求）。"""
    import bot.handlers.admin_points as ap
    src = inspect.getsource(ap)
    assert "log_admin_audit" in src, (
        "admin_points.py 应调用 log_admin_audit 记录加扣分动作"
    )


def test_admin_points_uses_add_point_transaction():
    """手动加扣分必须通过 add_point_transaction 写入流水（不允许跳过流水直改 total_points）。"""
    import bot.handlers.admin_points as ap
    src = inspect.getsource(ap)
    assert "add_point_transaction" in src, (
        "admin_points.py 应通过 add_point_transaction 写流水"
    )


# ============ 5. point_transactions schema 未受影响 ============


def test_schema_migrations_baseline_unchanged():
    """本批不动 schema：baseline 仍 9 条。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords"}


# ============ 6. 积分相关 helper 仍可 import ============


def test_point_helpers_still_importable():
    """积分相关核心 helper 函数仍可 import + callable。"""
    from bot.database import (
        add_point_transaction,
        count_user_point_transactions,
        count_users_with_points,
        get_top_points_users,
        get_user_points_summary,
        get_user_total_points,
        list_user_point_transactions,
        log_admin_audit,
        sum_total_points_earned,
    )
    for fn in (
        add_point_transaction,
        count_user_point_transactions,
        count_users_with_points,
        get_top_points_users,
        get_user_points_summary,
        get_user_total_points,
        list_user_point_transactions,
        log_admin_audit,
        sum_total_points_earned,
    ):
        assert callable(fn)


def test_point_grant_options_constants_present():
    """积分发放预设值常量仍可 import（手动加扣分 FSM 使用）。"""
    from bot.database import POINT_GRANT_REASON_OPTIONS, POINT_PACKAGE_OPTIONS
    assert POINT_GRANT_REASON_OPTIONS  # 非空
    assert POINT_PACKAGE_OPTIONS  # 非空


# ============ 7. 报销 / 抽奖 / 评价 handler 仍可 import ============


def test_other_admin_handlers_still_importable():
    """报销 / 抽奖 / 评价审核 handler 仍可正常 import（防止本批意外破坏）。"""
    from bot.handlers.admin_reimburse import router as r_reimburse
    from bot.handlers.admin_lottery import router as r_lottery
    from bot.handlers.admin_review import router as r_review
    from bot.handlers.rreview_admin import router as r_rreview
    for r in (r_reimburse, r_lottery, r_review, r_rreview):
        assert r is not None


def test_compute_reimbursement_amount_still_importable():
    """报销金额计算函数仍可 import + callable（积分接入工作不应触动报销）。"""
    from bot.database import compute_reimbursement_amount
    assert callable(compute_reimbursement_amount)


# ============ 8. UX-1 第二批：admin_operations 返回路径未受影响 ============


def test_admin_operations_kb_still_returns_to_menu_main():
    """admin_operations_kb 二级页自身仍回 menu:main 兜底（UX-1 第二批契约）。"""
    from bot.keyboards.admin_kb import admin_operations_kb
    cbs = _cbs(admin_operations_kb())
    assert "menu:main" in cbs, "admin_operations_kb 应保留 menu:main 兜底返回"


def test_admin_operations_handler_uses_super_admin_required():
    """admin:operations 二级页 handler 仍是超管限制（积分管理也仅超管可见）。"""
    import bot.handlers.admin_panel as ap
    src = inspect.getsource(ap)
    idx = src.find("async def cb_admin_operations(")
    assert idx > 0, "找不到 cb_admin_operations 定义"
    window = src[max(0, idx - 300):idx]
    assert "@super_admin_required" in window, (
        "cb_admin_operations 应使用 @super_admin_required 装饰器"
    )
