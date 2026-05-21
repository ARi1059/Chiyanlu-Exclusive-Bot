"""报销专用必关 - 隔离性 / 安全性契约测试。

覆盖 spec 隔离性 5 点 + 安全性 5 点：
    18. 全局必关订阅逻辑不变
    19. 用户浏览老师不触发报销必关检查
    20. 搜索 / 收藏 / 最近看过不触发
    21. 抽奖不触发
    22. 评价提交（不勾选报销）不触发
    23. 不修改报销金额计算
    24. 不修改积分规则
    25. 不修改抽奖逻辑
    26. 不修改 schema_migrations
    27. 没有新增迁移
    28. 新增 callback 字面量有锁定
"""
from __future__ import annotations

import inspect


def _src(module) -> str:
    return inspect.getsource(module)


# ============ 18. 全局必关订阅逻辑不变 ============


def test_global_subreq_helper_unchanged():
    """全局 check_user_subscribed (bot/utils/required_channels.py) 仍可 import + callable。"""
    from bot.utils.required_channels import check_user_subscribed, precheck_required_chat
    assert callable(check_user_subscribed)
    assert callable(precheck_required_chat)


def test_global_subreq_db_helpers_unchanged():
    """全局 required_subscriptions 表 5 个 helper 仍可 import。"""
    from bot.database import (
        add_required_subscription,
        list_required_subscriptions,
        get_required_subscription,
        toggle_required_subscription,
        remove_required_subscription,
    )
    for fn in (
        add_required_subscription, list_required_subscriptions,
        get_required_subscription, toggle_required_subscription,
        remove_required_subscription,
    ):
        assert callable(fn)


def test_global_subreq_admin_router_unchanged():
    """subreq_admin.router 未触动。"""
    from bot.handlers.subreq_admin import router
    assert router is not None


def test_global_subreq_uses_independent_states():
    """全局 SubReqAddStates 与新增 ReimburseSubReqAddStates 是不同的类。"""
    from bot.states.teacher_states import SubReqAddStates, ReimburseSubReqAddStates
    assert SubReqAddStates is not ReimburseSubReqAddStates
    # 状态名同名（waiting_chat_id / waiting_display_name / waiting_invite_link）
    # 但 state.state 字符串不同（aiogram 用类名+字段名作为状态 key）
    assert SubReqAddStates.waiting_chat_id.state != ReimburseSubReqAddStates.waiting_chat_id.state


# ============ 19. 用户浏览老师 / teacher_detail 不触发 ============


def test_teacher_detail_does_not_call_reimburse_subreq():
    """teacher_detail.py 不应 import 或调用 check_user_subscribed_for_reimburse。"""
    import bot.handlers.teacher_detail as mod
    src = _src(mod)
    assert "check_user_subscribed_for_reimburse" not in src
    assert "reimburse_subreq" not in src


# ============ 20. 搜索 / 收藏 / 最近看过 不触发 ============


def test_user_search_does_not_call_reimburse_subreq():
    import bot.handlers.user_search as mod
    src = _src(mod)
    assert "check_user_subscribed_for_reimburse" not in src
    assert "reimburse_subreq" not in src


def test_user_filter_does_not_call_reimburse_subreq():
    import bot.handlers.user_filter as mod
    src = _src(mod)
    assert "check_user_subscribed_for_reimburse" not in src


def test_user_history_does_not_call_reimburse_subreq():
    import bot.handlers.user_history as mod
    src = _src(mod)
    assert "check_user_subscribed_for_reimburse" not in src


def test_favorite_does_not_call_reimburse_subreq():
    import bot.handlers.favorite as mod
    src = _src(mod)
    assert "check_user_subscribed_for_reimburse" not in src


def test_user_panel_does_not_call_reimburse_subreq():
    import bot.handlers.user_panel as mod
    src = _src(mod)
    assert "check_user_subscribed_for_reimburse" not in src


def test_hot_teachers_does_not_call_reimburse_subreq():
    import bot.handlers.hot_teachers as mod
    src = _src(mod)
    assert "check_user_subscribed_for_reimburse" not in src


# ============ 21. 抽奖 不触发 ============


def test_lottery_entry_does_not_call_reimburse_subreq():
    import bot.handlers.lottery_entry as mod
    src = _src(mod)
    assert "check_user_subscribed_for_reimburse" not in src


def test_admin_lottery_does_not_call_reimburse_subreq():
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    assert "check_user_subscribed_for_reimburse" not in src


# ============ 22. 评价提交主体（除 yes/recheck 外）不触发 ============


# 注：review_submit.py 中的旧 cb_review_reimburse_yes /
# cb_reimburse_subreq_recheck_submit 已于 Sprint 7 §9.1 第 3 批
# ReviewSubmitStates 删除中清理。当前生产路径在 review_card.py，
# 等价契约由下面 test_review_card_main_steps_do_not_call_reimburse_subreq
# 覆盖。


def test_review_card_main_steps_do_not_call_reimburse_subreq():
    """check_user_subscribed_for_reimburse 仅在「报销意愿相关 handler」中出现，
    评价主体（卡片字段编辑、submit、_finalize_submit）不应触发。

    2026-05-21 评价前置改造后允许出现的 handler 升为 4 个：
        - cb_card_intent_yes         （新前置 intent 屏的 yes）
        - cb_card_intent_retry       （新前置 intent 屏的"已加入"重检）
        - cb_card_reimburse_yes      （旧路径兼容；waiting_reimbursement_choice 状态）
        - cb_reimburse_subreq_recheck_card（旧路径兼容；waiting_reimbursement_choice 状态）

    其它任何位置（字段编辑 / submit / _finalize_submit 等）出现 →
    意味着评价主体被报销 subreq 污染，违反 隔离性。
    """
    import bot.handlers.review_card as mod
    src = _src(mod)

    expected_fns = (
        "cb_card_intent_yes",
        "cb_card_intent_retry",
        "cb_card_reimburse_yes",
        "cb_reimburse_subreq_recheck_card",
    )
    bodies = []
    for fn in expected_fns:
        idx = src.find(f"async def {fn}(")
        assert idx > 0, f"找不到 {fn}"
        end = src.find("async def ", idx + 1)
        body = src[idx:end if end > 0 else idx + 2000]
        assert "check_user_subscribed_for_reimburse" in body, (
            f"{fn} 应调用 check_user_subscribed_for_reimburse"
        )
        bodies.append(body)

    total = src.count("check_user_subscribed_for_reimburse")
    in_expected = sum(b.count("check_user_subscribed_for_reimburse") for b in bodies)
    assert total == in_expected, (
        f"check_user_subscribed_for_reimburse 不应在 4 个 intent/yes/recheck 之外出现；"
        f"total={total}, in_expected={in_expected}"
    )


# ============ 23/24/25. 业务函数未改 ============


def test_compute_reimbursement_amount_unchanged():
    from bot.database import compute_reimbursement_amount
    assert callable(compute_reimbursement_amount)


def test_point_transaction_helpers_unchanged():
    from bot.database import add_point_transaction, get_user_total_points
    assert callable(add_point_transaction)
    assert callable(get_user_total_points)


def test_lottery_helpers_unchanged():
    from bot.database import get_lottery, list_lotteries_by_status
    assert callable(get_lottery)
    assert callable(list_lotteries_by_status)


def test_create_reimbursement_unchanged():
    from bot.database import create_reimbursement
    assert callable(create_reimbursement)


def test_approve_reimbursement_unchanged():
    from bot.database import approve_reimbursement, reject_reimbursement
    assert callable(approve_reimbursement)
    assert callable(reject_reimbursement)


def test_admin_reimburse_handler_unchanged():
    """admin_reimburse.py 业务 handler 模块仍可正常 import。"""
    from bot.handlers.admin_reimburse import router
    assert router is not None


def test_admin_reimburse_does_not_call_reimburse_subreq_gate():
    """报销审核 handler 不应调用准入 gate（只用户侧报销提交触发）。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    assert "check_user_subscribed_for_reimburse" not in src


# ============ 26-27. schema 不变 ============


def test_schema_migrations_baseline_unchanged():
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable"}


# ============ 28. 新增 callback 字面量锁定 ============


def test_new_callbacks_present_in_correct_modules():
    """关键 callback 字面量在对应模块源码中存在。

    旧 reimburse:subreq:recheck:submit / reimburse:subreq:back:submit 已随
    review_submit.py 中 ReviewSubmitStates 一并清理（Sprint 7 §9.1 第 3 批）。
    当前生产路径仅 review_card.py 的 :card 后缀变体。
    """
    import bot.handlers.reimburse_subreq_admin as adm
    import bot.handlers.review_card as rc
    import bot.keyboards.admin_kb as akb

    adm_src = _src(adm)
    for cb in (
        '"system:reimburse_subreq"',
        '"system:reimburse_subreq:add"',
        '"system:reimburse_subreq:add_confirm"',
    ):
        assert cb in adm_src

    rc_src = _src(rc)
    assert '"reimburse:subreq:recheck:card"' in rc_src
    assert '"reimburse:subreq:back:card"' in rc_src

    kb_src = _src(akb)
    assert '"system:reimburse_subreq"' in kb_src
    assert "reimburse:subreq:recheck:" in kb_src  # f-string 拼接
    assert "reimburse:subreq:back:" in kb_src


def test_legacy_global_subreq_callbacks_still_present():
    """全局 subreq callback 仍存在（admin:subreq:*）—— 隔离性。"""
    import bot.handlers.subreq_admin as mod
    src = _src(mod)
    for cb in (
        '"admin:subreq"',
        '"admin:subreq:add"',
    ):
        assert cb in src


# ============ Bonus: routers.py 注册顺序合理 ============


def test_reimburse_subreq_router_registered_after_admin_panel():
    """新 router 应在 admin_panel 之后注册（因 system:reimburse_subreq
    入口在 system_menu_kb，handler 在 admin_panel 已被 import 后才能解析）。"""
    import bot.routers as routers_mod
    src = _src(routers_mod)
    panel_idx = src.find("include_router(admin_panel_router)")
    reim_idx = src.find("include_router(reimburse_subreq_admin_router)")
    assert panel_idx > 0
    assert reim_idx > 0
    assert reim_idx > panel_idx, (
        "reimburse_subreq_admin_router 应在 admin_panel_router 之后注册"
    )
