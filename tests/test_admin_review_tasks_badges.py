"""Sprint UX-2 第一项：审核处理 badge 优化契约测试。

背景：
    UX-2 第一项要求主菜单「✅ 审核处理」按钮与二级页 admin_review_tasks_kb
    内每个入口都显示 pending 数量 badge；0 不显示括号；非超管不可见超管入口；
    queued 不计入主菜单总数。

现状：
    keyboard 层（main_menu_kb / admin_review_tasks_kb）的 badge 渲染逻辑已经
    实现到位，由 tests/test_admin_review_tasks_menu.py 完整覆盖。

本文件的作用：
    1. 锁定 **caller wiring**：admin_panel.py 中
       - `_build_main_menu_kb` 必须把 4 个 pending count 全部传给 main_menu_kb
       - `cb_admin_review_tasks` 必须把 4 个 pending count + is_super 传给
         admin_review_tasks_kb
       这是 test_admin_review_tasks_menu 没覆盖的部分；如果未来某个 caller
       漏传一个参数，相关 badge 会静默归零，单测得不报错——本文件用静态源码
       断言锁住。
    2. 锁定 UX-2 第一项的标志性场景（端到端样例）：把"目标展示示例"作为
       可执行规约，避免被无意改动破坏。
    3. 锁定 queued 不计入主菜单总数 / 非超管不查超管专属 count 的契约。

不连接真实 Telegram；不访问生产 DB；纯静态 / keyboard 断言。
"""

from __future__ import annotations

import inspect


# ============ 1. caller wiring：_build_main_menu_kb 静态契约 ============


def _admin_panel_source() -> str:
    import bot.handlers.admin_panel as ap
    return inspect.getsource(ap)


def _build_main_menu_kb_source() -> str:
    """提取 _build_main_menu_kb 函数体源码（含上下文）。"""
    src = _admin_panel_source()
    idx = src.find("async def _build_main_menu_kb(")
    assert idx > 0, "找不到 _build_main_menu_kb 定义"
    # 取 2000 字符窗口；足够覆盖整个函数体（含 main_menu_kb 调用 + 5 个 kwargs）
    return src[idx:idx + 2000]


def test_build_main_menu_kb_passes_all_four_pending_counts():
    """_build_main_menu_kb 必须把 4 个 pending count + is_super 全部传给 main_menu_kb。

    任何一个参数被漏传，对应 badge 会归零（UX-2 第一项的可见 bug）。
    """
    body = _build_main_menu_kb_source()
    assert "pending_count=" in body, "_build_main_menu_kb 缺 pending_count="
    assert "pending_review_count=" in body, "_build_main_menu_kb 缺 pending_review_count="
    assert "pending_reimburse_count=" in body, (
        "_build_main_menu_kb 缺 pending_reimburse_count="
    )
    assert "queued_reimburse_count=" in body, (
        "_build_main_menu_kb 缺 queued_reimburse_count="
    )
    assert "is_super=" in body, "_build_main_menu_kb 缺 is_super="


def test_build_main_menu_kb_uses_count_helpers_from_database():
    """_build_main_menu_kb 必须调用 4 个 count_* helper 读取真实 pending 数。"""
    body = _build_main_menu_kb_source()
    assert "count_pending_edits" in body, "缺 count_pending_edits 调用"
    assert "count_pending_reviews" in body, "缺 count_pending_reviews 调用"
    assert "count_pending_reimbursements" in body, (
        "缺 count_pending_reimbursements 调用"
    )
    assert "count_queued_reimbursements" in body, (
        "缺 count_queued_reimbursements 调用"
    )


def test_build_main_menu_kb_gates_super_only_counts_behind_is_super():
    """普通管理员不应调用超管专属 count；rcount / reimb / queued 三个查询
    必须在 is_super 分支内。"""
    body = _build_main_menu_kb_source()
    # 找 if user_id... 分支内的位置（is_super=True 之后）
    is_super_idx = body.find("is_super = True")
    assert is_super_idx > 0, "找不到 is_super=True 分支"
    super_block = body[is_super_idx:]
    # 三个超管 count 必须在 super 分支之后出现
    assert "count_pending_reviews" in super_block
    assert "count_pending_reimbursements" in super_block
    assert "count_queued_reimbursements" in super_block


# ============ 2. caller wiring：cb_admin_review_tasks 静态契约 ============


def _cb_admin_review_tasks_source() -> str:
    """提取 cb_admin_review_tasks 函数体源码（含上下文）。"""
    src = _admin_panel_source()
    idx = src.find("async def cb_admin_review_tasks(")
    assert idx > 0, "找不到 cb_admin_review_tasks 定义"
    # 取 3000 字符窗口；足够覆盖整个函数体（含 admin_review_tasks_kb 调用 + 5 个 kwargs）
    return src[idx:idx + 3000]


def test_cb_admin_review_tasks_passes_all_four_counts_plus_is_super():
    """cb_admin_review_tasks 必须把 4 个 pending count + is_super 全部传给
    admin_review_tasks_kb。任何一个漏传都会让对应 badge 静默归零。"""
    body = _cb_admin_review_tasks_source()
    assert "pending_edit_count=" in body, "cb_admin_review_tasks 缺 pending_edit_count="
    assert "pending_review_count=" in body, (
        "cb_admin_review_tasks 缺 pending_review_count="
    )
    assert "pending_reimburse_count=" in body, (
        "cb_admin_review_tasks 缺 pending_reimburse_count="
    )
    assert "queued_reimburse_count=" in body, (
        "cb_admin_review_tasks 缺 queued_reimburse_count="
    )
    assert "is_super=" in body, "cb_admin_review_tasks 缺 is_super="


def test_cb_admin_review_tasks_gates_super_only_counts():
    """普通管理员走 cb_admin_review_tasks 时不应触发超管专属 count 查询。"""
    body = _cb_admin_review_tasks_source()
    # 三个超管 count 必须在 is_super 分支内
    is_super_idx = body.find("if is_super:")
    assert is_super_idx > 0, "找不到 if is_super 分支"
    super_block = body[is_super_idx:]
    assert "count_pending_reviews" in super_block
    assert "count_pending_reimbursements" in super_block
    assert "count_queued_reimbursements" in super_block


# ============ 3. UX-2 第一项 端到端标志性样例 ============


def test_main_menu_super_full_badge_scenario():
    """UX-2 第一项标志样例：超管，老师=2/评价=3/报销=3/queued=5，
    主菜单显示 (8) = 2 + 3 + 3，queued 5 不计入。
    """
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(
        pending_count=2,
        pending_review_count=3,
        pending_reimburse_count=3,
        queued_reimburse_count=5,
        is_super=True,
    )
    btn = next(
        b for row in kb.inline_keyboard for b in row
        if b.callback_data == "admin:review_tasks"
    )
    assert "✅ 审核处理" in btn.text
    assert "(8)" in btn.text, (
        f"超管 2+3+3 应显示 (8)，queued=5 不应进入主菜单总数；实际：{btn.text}"
    )
    # 防御：不应误把 queued 加进总数变 13
    assert "(13)" not in btn.text


def test_review_tasks_kb_super_full_badge_scenario():
    """UX-2 第一项标志样例：超管二级页四类 badge 全显示。

    目标:
        👩‍🏫 老师资料审核 (2)
        📝 评价审核 (3)
        💰 报销审核 (3)
        📋 报销名单 (5)
        ⬅️ 返回后台
    """
    from bot.keyboards.admin_kb import admin_review_tasks_kb
    kb = admin_review_tasks_kb(
        pending_edit_count=2,
        pending_review_count=3,
        pending_reimburse_count=3,
        queued_reimburse_count=5,
        is_super=True,
    )
    by_cb = {b.callback_data: b.text for row in kb.inline_keyboard for b in row}
    assert by_cb["review:enter"].endswith("(2)")
    assert "老师资料审核" in by_cb["review:enter"]
    assert by_cb["rreview:enter"].endswith("(3)")
    assert "评价审核" in by_cb["rreview:enter"]
    assert by_cb["reimburse:enter"].endswith("(3)")
    assert "报销审核" in by_cb["reimburse:enter"]
    assert by_cb["reimburse:queued:0"].endswith("(5)")
    assert "报销名单" in by_cb["reimburse:queued:0"]
    # 返回按钮仍是 menu:main（admin:review_tasks 二级页本身回主菜单）
    assert by_cb.get("menu:main") is not None


def test_review_tasks_kb_non_super_does_not_show_super_only_entries():
    """UX-2 第一项约束：普通管理员二级页只看老师资料审核 + 返回，
    即便传入超管参数也不应显示评价 / 报销 / 名单入口。
    """
    from bot.keyboards.admin_kb import admin_review_tasks_kb
    kb = admin_review_tasks_kb(
        pending_edit_count=2,
        pending_review_count=99,
        pending_reimburse_count=99,
        queued_reimburse_count=99,
        is_super=False,  # 关键
    )
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    # 仅含老师资料审核 + 返回
    assert callbacks == ["review:enter", "menu:main"]


def test_review_tasks_kb_super_no_queued_no_badge_for_queued():
    """queued=0 时报销名单按钮整体不显示（不应出现 0 badge 也不应出现按钮）。"""
    from bot.keyboards.admin_kb import admin_review_tasks_kb
    kb = admin_review_tasks_kb(
        pending_edit_count=0,
        pending_review_count=0,
        pending_reimburse_count=0,
        queued_reimburse_count=0,
        is_super=True,
    )
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "reimburse:queued:0" not in callbacks, (
        "queued=0 时报销名单按钮整体不应显示"
    )


def test_main_menu_zero_badge_no_parens_super_or_not():
    """主菜单 0 badge 时不显示括号——super 和非 super 都遵守。"""
    from bot.keyboards.admin_kb import main_menu_kb
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        btn = next(
            b for row in kb.inline_keyboard for b in row
            if b.callback_data == "admin:review_tasks"
        )
        assert "(" not in btn.text and ")" not in btn.text, (
            f"is_super={is_super} 全 0 时不应含括号；实际：{btn.text}"
        )


# ============ 4. handler 文案随 queued 动态显示 ============


def test_cb_admin_review_tasks_renders_queued_line_only_when_present():
    """cb_admin_review_tasks 的正文中『📋 报销名单』一行应受 queued>0 条件控制。"""
    body = _cb_admin_review_tasks_source()
    # 必须有针对 queued_reimburse_count > 0 的判断包裹 报销名单 行
    assert "queued_reimburse_count > 0" in body, (
        "cb_admin_review_tasks 应只在 queued>0 时追加 报销名单 行"
    )
    assert "报销名单" in body
    assert "评价审核" in body
    assert "报销审核" in body


# ============ 5. 不影响 schema / 审核业务 handler ============


def test_schema_migrations_baseline_unchanged():
    """UX-2 第一项只动只读统计渲染，不动 schema。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords"}


def test_review_handlers_unchanged_still_importable():
    """三个审核业务 handler 仍可正常 import + 含原 callback 字面量。"""
    import bot.handlers.admin_review as ar
    import bot.handlers.rreview_admin as rra
    import bot.handlers.admin_reimburse as ari
    assert ar.router is not None
    assert rra.router is not None
    assert ari.router is not None
    assert '"review:enter"' in inspect.getsource(ar)
    assert '"rreview:enter"' in inspect.getsource(rra)
    assert '"reimburse:enter"' in inspect.getsource(ari)
    assert "reimburse:queued" in inspect.getsource(ari)
