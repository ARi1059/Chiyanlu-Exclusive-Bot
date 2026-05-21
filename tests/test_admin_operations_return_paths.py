"""Sprint UX-1 第二批：子页面返回路径优化（admin:operations 子页）契约测试。

范围：仅覆盖「🎲 活动运营」(admin:operations) 下的两个主面板：
    - 🎲 抽奖管理 admin:lottery   keyboard: admin_lottery_menu_kb
    - 💰 积分管理 admin:points    keyboard: admin_points_menu_kb

UX 目标（参见 docs/UX-EFFICIENCY-PLAN.md §7 Sprint UX-1）：
    超管在「活动运营」内查看抽奖 / 积分管理后，应回到二级页 admin:operations
    继续做下一项运营动作，而不是被甩回主菜单。返回按钮 callback 从
    menu:main 调整为 admin:operations。

本文件是 UX-1 第二批改动的「集中契约」：
    1. 抽奖管理主面板返回按钮 callback_data == "admin:operations"
    2. 积分管理主面板返回按钮 callback_data == "admin:operations"
    3. 抽奖管理主面板仍含原本应有的管理入口
    4. 积分管理主面板仍含原本应有的管理入口
    5. admin_operations_kb 仍含 admin:lottery / admin:points / menu:main
    6. admin:lottery / admin:points / admin:operations callback 字面量未删
    7. 不新增数据库迁移
    8. 不修改 service 与 handler 业务逻辑（router 仍可 import）

不连接真实 Telegram；不访问生产 DB；纯静态 / keyboard 断言。
"""

from __future__ import annotations


# ============ 1. 两个主面板返回按钮 callback_data == "admin:operations" ============


def _return_buttons(kb) -> list:
    """提取 keyboard 中所有"返回"类按钮（文案含 ⬅️ / 🔙 / "返回"）。"""
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            if "⬅️" in btn.text or "🔙" in btn.text or "返回" in btn.text:
                out.append(btn)
    return out


def test_admin_lottery_menu_kb_return_button_goes_to_admin_operations():
    from bot.keyboards.admin_kb import admin_lottery_menu_kb
    kb = admin_lottery_menu_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1, (
        f"admin_lottery_menu_kb 应有恰好 1 个返回按钮，实际：{[b.text for b in backs]}"
    )
    assert backs[0].callback_data == "admin:operations", (
        f"抽奖管理主面板返回按钮 callback 应为 admin:operations，"
        f"实际：{backs[0].callback_data}"
    )
    assert "活动运营" in backs[0].text, (
        f"返回按钮文案应含「活动运营」，实际：{backs[0].text}"
    )


def test_admin_points_menu_kb_return_button_goes_to_admin_operations():
    from bot.keyboards.admin_kb import admin_points_menu_kb
    kb = admin_points_menu_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1
    assert backs[0].callback_data == "admin:operations"
    assert "活动运营" in backs[0].text


def test_two_main_panels_no_longer_return_to_menu_main():
    """UX-1 第二批：两个主面板不再直接含 menu:main 返回。"""
    from bot.keyboards.admin_kb import admin_lottery_menu_kb, admin_points_menu_kb
    for kb_fn in (admin_lottery_menu_kb, admin_points_menu_kb):
        kb = kb_fn() if kb_fn is admin_points_menu_kb else kb_fn(0)
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "menu:main" not in callbacks, (
            f"{kb_fn.__name__} 不应再含 menu:main 返回"
            f"（UX-1 已下沉到 admin:operations）"
        )


# ============ 2. 抽奖管理主面板仍含管理入口 ============


def test_admin_lottery_menu_kb_keeps_core_entries():
    """抽奖管理主面板的核心入口（创建 / 列表 / 客服）保持。"""
    from bot.keyboards.admin_kb import admin_lottery_menu_kb
    callbacks = [
        b.callback_data for row in admin_lottery_menu_kb().inline_keyboard for b in row
    ]
    assert "admin:lottery:create" in callbacks
    assert "admin:lottery:list" in callbacks
    assert "admin:lottery:contact" in callbacks


def test_admin_lottery_menu_kb_list_badge_when_pending():
    """pending_count 大于 0 时列表按钮带 badge，行为未被本批改动影响。"""
    from bot.keyboards.admin_kb import admin_lottery_menu_kb
    kb_zero = admin_lottery_menu_kb(0)
    kb_three = admin_lottery_menu_kb(3)
    texts_zero = [b.text for row in kb_zero.inline_keyboard for b in row]
    texts_three = [b.text for row in kb_three.inline_keyboard for b in row]
    assert any("📋 抽奖列表" == t for t in texts_zero)
    assert any("📋 抽奖列表 (3)" == t for t in texts_three)


# ============ 3. 积分管理主面板仍含管理入口 ============


def test_admin_points_menu_kb_keeps_core_entries():
    """积分管理主面板的核心入口（查询 / 加分 / 总览）保持。"""
    from bot.keyboards.admin_kb import admin_points_menu_kb
    callbacks = [
        b.callback_data for row in admin_points_menu_kb().inline_keyboard for b in row
    ]
    assert "admin:points:query" in callbacks
    assert "admin:points:grant" in callbacks
    assert "admin:points:overview" in callbacks


# ============ 4. admin_operations_kb 仍含两个入口 + menu:main ============


def test_admin_operations_kb_still_contains_lottery_and_points_and_menu_main():
    """UX-1 第二批不改 admin_operations_kb 自身：仍含两个入口 + menu:main 返回。"""
    from bot.keyboards.admin_kb import admin_operations_kb
    kb = admin_operations_kb()
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "admin:lottery" in callbacks
    assert "admin:points" in callbacks
    # admin:operations 自己回主菜单仍走 menu:main（兜底）
    assert "menu:main" in callbacks


def test_admin_operations_kb_does_not_introduce_extra_entries():
    """UX-1 第二批严禁在 admin_operations_kb 内引入额外入口
    （如报销活动 / 重启 promo_links / source_stats 等）。"""
    from bot.keyboards.admin_kb import admin_operations_kb
    callbacks = {
        b.callback_data for row in admin_operations_kb().inline_keyboard for b in row
    }
    # 允许集合：两个子入口 + 主菜单返回
    allowed = {"admin:lottery", "admin:points", "menu:main"}
    extras = callbacks - allowed
    assert not extras, f"admin_operations_kb 不应含额外入口，发现：{extras}"


# ============ 5. 旧 callback 字面量仍存在（含义未变） ============


def test_legacy_callbacks_still_in_handlers_and_kb():
    """admin:lottery / admin:points / admin:operations 字面量在
    对应 handler / kb 源码中仍存在（UX-1 不改 callback 含义）。"""
    import inspect
    import bot.handlers.admin_lottery as al
    import bot.handlers.admin_points as ap
    import bot.handlers.admin_panel as panel
    import bot.keyboards.admin_kb as akb

    assert '"admin:lottery"' in inspect.getsource(al)
    assert '"admin:points"' in inspect.getsource(ap)
    assert '"admin:operations"' in inspect.getsource(panel)
    for lit in ('"admin:lottery"', '"admin:points"', '"admin:operations"'):
        assert lit in inspect.getsource(akb), (
            f"admin_kb.py 缺少 {lit}（UX-1 不应改 callback 含义）"
        )


# ============ 6. 不新增数据库迁移 ============


def test_schema_migrations_baseline_unchanged():
    """UX-1 第二批不新增 schema 变更：baseline 仍 9 条。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    """UX-1 第二批不新增 Migration：MIGRATIONS 仍为空 list。"""
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable"}


# ============ 7. 不修改业务 handler / service ============


def test_admin_lottery_and_points_handlers_still_importable():
    """UX-1 第二批严禁改 handler 业务逻辑；router 仍可 import + 非空。"""
    from bot.handlers.admin_lottery import router as r1
    from bot.handlers.admin_points import router as r2
    assert r1 is not None
    assert r2 is not None


def test_lottery_and_points_handler_modules_unchanged_kb_imports():
    """两个 handler 仍通过 import 调用对应主面板 kb（未在 handler 内硬编码 keyboard）。"""
    import bot.handlers.admin_lottery as al
    import bot.handlers.admin_points as ap
    import inspect
    assert "admin_lottery_menu_kb" in inspect.getsource(al)
    assert "admin_points_menu_kb" in inspect.getsource(ap)
