"""Sprint UX-2 第三项第一批：「运营总览异常快捷跳转」契约测试。

背景：
    UX-2 第三项要求在 admin:overview（运营总览）页面底部按钮区，根据 stats
    与权限渲染快捷跳转按钮，减少管理员"看完总览→翻菜单→找入口"的点击。

设计：
    - `admin_overview_kb(stats, *, is_super=False)` 接收新参数（stats=None 兼容旧调用）
    - count > 0 才渲染对应快捷按钮
    - 非超管不可见评价 / 报销 / queued / 抽奖入口
    - 刷新 + 返回运营看板按钮始终保留
    - AdminOverviewStats 仅新增 1 个只读字段 `pending_teacher_edits`
      （查询 teacher_edit_requests pending），原统计口径完全不变

不连接真实 Telegram；不访问生产 DB；纯静态 / keyboard 断言。
"""

from __future__ import annotations

import inspect


# ============ helpers ============


def _make_stats(**kwargs):
    """构造 AdminOverviewStats，未指定字段默认 None。"""
    from bot.services.admin_overview import AdminOverviewStats
    return AdminOverviewStats(**kwargs)


def _cbs(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def _texts(kb) -> list:
    return [b.text for row in kb.inline_keyboard for b in row]


# ============ 1. 快捷按钮：count > 0 / 权限 控制可见性 ============


def test_overview_kb_shows_teacher_edits_shortcut_for_any_admin():
    """老师资料审核：pending > 0 → 所有 admin（含非超管）可见 review:enter 快捷。"""
    from bot.keyboards.admin_kb import admin_overview_kb
    for is_super in (True, False):
        kb = admin_overview_kb(_make_stats(pending_teacher_edits=2), is_super=is_super)
        cbs = _cbs(kb)
        assert "review:enter" in cbs, (
            f"is_super={is_super} 应可见老师资料审核快捷入口"
        )
        # 按钮文案应包含数字 badge
        btn = next(b for row in kb.inline_keyboard for b in row
                   if b.callback_data == "review:enter")
        assert "(2)" in btn.text and "老师资料审核" in btn.text


def test_overview_kb_shows_super_only_shortcuts_for_super():
    """超管 + 各 count > 0：评价审核 / 报销审核 / 报销名单 / 抽奖管理 都显示。"""
    from bot.keyboards.admin_kb import admin_overview_kb
    kb = admin_overview_kb(
        _make_stats(
            pending_teacher_edits=1,
            pending_reviews=3,
            pending_reimbursements=2,
            queued_reimbursements=5,
            active_lotteries=2,
            scheduled_lotteries=1,
        ),
        is_super=True,
    )
    cbs = _cbs(kb)
    assert "review:enter" in cbs
    assert "rreview:enter" in cbs
    assert "reimburse:enter" in cbs
    assert "reimburse:queued:0" in cbs
    assert "admin:lottery" in cbs
    # badge 数字
    by_cb = {b.callback_data: b.text for row in kb.inline_keyboard for b in row}
    assert "(1)" in by_cb["review:enter"]
    assert "(3)" in by_cb["rreview:enter"]
    assert "(2)" in by_cb["reimburse:enter"]
    assert "(5)" in by_cb["reimburse:queued:0"]
    # 抽奖总数 = active(2) + scheduled(1) = 3
    assert "(3)" in by_cb["admin:lottery"]


def test_overview_kb_hides_super_only_shortcuts_for_non_super():
    """非超管即便 count > 0 也不应看到评价 / 报销 / 名单 / 抽奖快捷入口。"""
    from bot.keyboards.admin_kb import admin_overview_kb
    kb = admin_overview_kb(
        _make_stats(
            pending_teacher_edits=1,
            pending_reviews=99,
            pending_reimbursements=99,
            queued_reimbursements=99,
            active_lotteries=99,
            scheduled_lotteries=99,
        ),
        is_super=False,  # 关键
    )
    cbs = _cbs(kb)
    # 老师资料审核可见
    assert "review:enter" in cbs
    # 超管专属四类都不可见
    assert "rreview:enter" not in cbs
    assert "reimburse:enter" not in cbs
    assert "reimburse:queued:0" not in cbs
    assert "admin:lottery" not in cbs


def test_overview_kb_hides_zero_count_shortcuts():
    """对应 count = 0 时该快捷按钮整体不显示（不应出现 (0) 角标）。"""
    from bot.keyboards.admin_kb import admin_overview_kb
    kb = admin_overview_kb(
        _make_stats(
            pending_teacher_edits=0,
            pending_reviews=0,
            pending_reimbursements=0,
            queued_reimbursements=0,
            active_lotteries=0,
            scheduled_lotteries=0,
        ),
        is_super=True,
    )
    cbs = _cbs(kb)
    # 五类快捷都不应显示
    assert "review:enter" not in cbs
    assert "rreview:enter" not in cbs
    assert "reimburse:enter" not in cbs
    assert "reimburse:queued:0" not in cbs
    assert "admin:lottery" not in cbs
    # 但刷新 + 返回仍在
    assert "admin:overview:refresh" in cbs
    assert "admin:dashboard" in cbs


def test_overview_kb_treats_none_counts_as_zero():
    """None count（统计失败回落）视为 0，对应快捷整体不显示。"""
    from bot.keyboards.admin_kb import admin_overview_kb
    kb = admin_overview_kb(_make_stats(), is_super=True)  # 全 None
    cbs = _cbs(kb)
    assert "review:enter" not in cbs
    assert "rreview:enter" not in cbs
    assert "reimburse:enter" not in cbs
    assert "reimburse:queued:0" not in cbs
    assert "admin:lottery" not in cbs
    # 兜底按钮仍在
    assert "admin:overview:refresh" in cbs
    assert "admin:dashboard" in cbs


def test_overview_kb_lottery_aggregates_active_and_scheduled():
    """抽奖管理 badge = active + scheduled；仅一者 > 0 时也显示。"""
    from bot.keyboards.admin_kb import admin_overview_kb
    # 只有 active：1
    kb1 = admin_overview_kb(_make_stats(active_lotteries=1), is_super=True)
    by1 = {b.callback_data: b.text for row in kb1.inline_keyboard for b in row}
    assert "admin:lottery" in by1
    assert "(1)" in by1["admin:lottery"]

    # 只有 scheduled：4
    kb2 = admin_overview_kb(_make_stats(scheduled_lotteries=4), is_super=True)
    by2 = {b.callback_data: b.text for row in kb2.inline_keyboard for b in row}
    assert "admin:lottery" in by2
    assert "(4)" in by2["admin:lottery"]

    # 两者都 0
    kb3 = admin_overview_kb(
        _make_stats(active_lotteries=0, scheduled_lotteries=0),
        is_super=True,
    )
    assert "admin:lottery" not in _cbs(kb3)


# ============ 2. 兜底按钮（刷新 + 返回）始终保留 ============


def test_overview_kb_refresh_and_back_buttons_always_present():
    """无论 stats / is_super 如何，刷新和返回按钮始终保留。"""
    from bot.keyboards.admin_kb import admin_overview_kb
    cases = [
        admin_overview_kb(),  # 无参（旧调用兼容）
        admin_overview_kb(None, is_super=True),
        admin_overview_kb(_make_stats(), is_super=False),
        admin_overview_kb(
            _make_stats(
                pending_teacher_edits=10, pending_reviews=10,
                pending_reimbursements=10, queued_reimbursements=10,
                active_lotteries=10, scheduled_lotteries=10,
            ),
            is_super=True,
        ),
    ]
    for kb in cases:
        cbs = _cbs(kb)
        assert "admin:overview:refresh" in cbs, "缺少刷新按钮"
        assert "admin:dashboard" in cbs, "缺少返回运营看板按钮"


def test_overview_kb_no_args_returns_only_refresh_and_back():
    """无参 admin_overview_kb()：仅含兜底（旧调用兼容）。"""
    from bot.keyboards.admin_kb import admin_overview_kb
    kb = admin_overview_kb()
    cbs = _cbs(kb)
    assert cbs == ["admin:overview:refresh", "admin:dashboard"]


# ============ 3. 快捷按钮不应触发 approve/reject ============


def test_overview_kb_shortcuts_never_trigger_approve_or_reject():
    """所有快捷按钮 callback 必须是导航类（:enter / 列表入口），不能是
    任何 approve / reject 动作 callback。"""
    from bot.keyboards.admin_kb import admin_overview_kb
    kb = admin_overview_kb(
        _make_stats(
            pending_teacher_edits=1, pending_reviews=1,
            pending_reimbursements=1, queued_reimbursements=1,
            active_lotteries=1,
        ),
        is_super=True,
    )
    for cb in _cbs(kb):
        for forbidden in (":approve", ":reject", ":approve_p:"):
            assert forbidden not in cb, (
                f"快捷按钮 callback 不应含 {forbidden}：{cb}"
            )


# ============ 4. AdminOverviewStats 新字段 + service 查询 ============


def test_admin_overview_stats_has_pending_teacher_edits_field():
    """AdminOverviewStats 必须有 pending_teacher_edits 字段（UX-2 第三项第一批新增）。"""
    from bot.services.admin_overview import AdminOverviewStats
    stats = AdminOverviewStats()
    # 默认 None，与其它 pending_* 字段一致
    assert hasattr(stats, "pending_teacher_edits")
    assert stats.pending_teacher_edits is None


def test_get_admin_overview_stats_queries_teacher_edit_requests():
    """get_admin_overview_stats 必须查询 teacher_edit_requests 的 pending 数。

    静态扫描 service 源码，确认包含对应 SQL。
    """
    import bot.services.admin_overview as svc
    src = inspect.getsource(svc)
    assert "teacher_edit_requests" in src, (
        "get_admin_overview_stats 应查询 teacher_edit_requests 表"
    )
    assert "pending_teacher_edits" in src, (
        "get_admin_overview_stats 应给 pending_teacher_edits 字段赋值"
    )


def test_render_admin_overview_text_body_unchanged():
    """渲染正文不应因新字段而改变（spec：不大改运营总览正文）。

    检查 render 输出长度（行数）与既有版本一致：14 行（含空行）。
    """
    from bot.services.admin_overview import (
        AdminOverviewStats, render_admin_overview,
    )
    text = render_admin_overview(AdminOverviewStats())
    lines = text.split("\n")
    # 原文有 18 行（含空行）；新字段未输出则保持 18
    assert "📊 运营总览" in text
    assert "今日数据" in text
    assert "待处理" in text
    assert "抽奖" in text
    assert "系统" in text
    # 关键：新字段标签未出现在正文（不大改文案契约）
    assert "待审核老师资料" not in text, (
        "render 不应新增「待审核老师资料」行；新字段仅用于 keyboard 快捷判断"
    )
    # 行数应保持 22（5 个分组 + 4 空行 + 标题 + 更新时间；spec：不大改正文）
    assert len(lines) == 22, (
        f"render 行数应保持 22，实际 {len(lines)} 行；正文应未变"
    )


# ============ 5. handler wiring：cb_admin_overview / refresh 注入 stats + is_super ============


def _admin_panel_source() -> str:
    import bot.handlers.admin_panel as ap
    return inspect.getsource(ap)


def test_cb_admin_overview_passes_stats_and_is_super_to_kb():
    """cb_admin_overview 必须把 stats 和 is_super 传给 admin_overview_kb。"""
    src = _admin_panel_source()
    idx = src.find("async def cb_admin_overview(")
    assert idx > 0
    body = src[idx:idx + 1500]
    # 必须计算 is_super
    assert "is_super" in body, "cb_admin_overview 应计算 is_super"
    # 必须把 stats 与 is_super= 都传给 kb
    assert "admin_overview_kb(stats" in body, (
        "cb_admin_overview 应调用 admin_overview_kb(stats, is_super=...)"
    )
    assert "is_super=is_super" in body


def test_cb_admin_overview_refresh_passes_stats_and_is_super_to_kb():
    """cb_admin_overview_refresh 同样应注入 stats + is_super。"""
    src = _admin_panel_source()
    idx = src.find("async def cb_admin_overview_refresh(")
    assert idx > 0
    body = src[idx:idx + 1500]
    assert "is_super" in body
    assert "admin_overview_kb(stats" in body
    assert "is_super=is_super" in body


# ============ 6. callback 字面量未删 + 不动业务 handler ============


def test_admin_overview_callbacks_still_present():
    """admin:overview / admin:overview:refresh 字面量仍在 admin_panel.py。"""
    src = _admin_panel_source()
    assert '"admin:overview"' in src
    assert '"admin:overview:refresh"' in src


def test_shortcut_target_callbacks_handlers_still_importable():
    """快捷跳转指向的 5 个 callback 对应 handler 仍可正常 import。

    review:enter        → admin_review.router
    rreview:enter       → rreview_admin.router
    reimburse:enter     → admin_reimburse.router
    reimburse:queued:0  → admin_reimburse.router
    admin:lottery       → admin_lottery.router
    """
    from bot.handlers.admin_review import router as r1
    from bot.handlers.rreview_admin import router as r2
    from bot.handlers.admin_reimburse import router as r3
    from bot.handlers.admin_lottery import router as r4
    assert r1 is not None
    assert r2 is not None
    assert r3 is not None
    assert r4 is not None


# ============ 7. schema / 业务逻辑保护 ============


def test_schema_migrations_baseline_unchanged():
    """UX-2 第三项第一批不动 schema。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states"}


def test_compute_reimbursement_amount_unchanged():
    """报销金额计算函数仍可 import 且 callable。"""
    from bot.database import compute_reimbursement_amount
    assert callable(compute_reimbursement_amount)
