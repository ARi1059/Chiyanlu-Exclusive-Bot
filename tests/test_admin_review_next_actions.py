"""Sprint UX-2 第二项：「审核完成后处理下一条」契约测试。

背景：
    UX-2 第二项要求在三类审核（老师资料 / 评价 / 报销）approve / reject 成功
    的 ack 消息上增加快捷按钮，给"想换审核类型 / 错过自动推下一条 / 想停下"
    的管理员一个明确出口。

设计：
    新增 `admin_review_done_next_kb(kind)` helper：
        kind="edit"      → [➡️ 处理下一条 → review:enter]      [⬅️ 返回审核处理]
        kind="review"    → [➡️ 处理下一条 → rreview:enter]     [⬅️ 返回审核处理]
        kind="reimburse" → [➡️ 处理下一条 → reimburse:enter]   [⬅️ 返回审核处理]

接入点（仅 4 处 ack 消息加 reply_markup，业务逻辑零改动）：
    1. admin_review.py _perform_reject_from_message  ：老师资料 FSM 驳回 ack
    2. rreview_admin.py _do_approve   自定义 FSM 路径：评价通过 ack
    3. rreview_admin.py _do_reject    驳回 ack 文字（非空队列分支）
    4. admin_reimburse.py on_reimburse_reject_reason ：报销驳回 ack

不连接真实 Telegram；不访问生产 DB；纯静态 / keyboard 断言。
"""

from __future__ import annotations

import inspect


# ============ helpers ============


def _all_callbacks(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def _texts(kb) -> list:
    return [b.text for row in kb.inline_keyboard for b in row]


# ============ 1. admin_review_done_next_kb 三种 kind ============


def test_done_kb_edit_points_to_review_enter():
    """kind='edit' → 处理下一条指向 review:enter（老师资料审核入口）。"""
    from bot.keyboards.admin_kb import admin_review_done_next_kb
    kb = admin_review_done_next_kb("edit")
    cbs = _all_callbacks(kb)
    assert cbs == ["review:enter", "admin:review_tasks"], (
        f"kind=edit 应只含两个按钮 [review:enter, admin:review_tasks]，"
        f"实际：{cbs}"
    )
    texts = _texts(kb)
    assert "处理下一条" in texts[0]
    assert "返回审核处理" in texts[1]


def test_done_kb_review_points_to_rreview_enter():
    """kind='review' → 处理下一条指向 rreview:enter（评价审核入口）。"""
    from bot.keyboards.admin_kb import admin_review_done_next_kb
    kb = admin_review_done_next_kb("review")
    cbs = _all_callbacks(kb)
    assert cbs == ["rreview:enter", "admin:review_tasks"]
    texts = _texts(kb)
    assert "处理下一条" in texts[0]
    assert "返回审核处理" in texts[1]


def test_done_kb_reimburse_points_to_reimburse_enter():
    """kind='reimburse' → 处理下一条指向 reimburse:enter（报销审核入口）。"""
    from bot.keyboards.admin_kb import admin_review_done_next_kb
    kb = admin_review_done_next_kb("reimburse")
    cbs = _all_callbacks(kb)
    assert cbs == ["reimburse:enter", "admin:review_tasks"]
    texts = _texts(kb)
    assert "处理下一条" in texts[0]
    assert "返回审核处理" in texts[1]


def test_done_kb_unknown_kind_raises_value_error():
    """非预期 kind 必须显式抛 ValueError，不允许静默回落到错误 entry。"""
    import pytest
    from bot.keyboards.admin_kb import admin_review_done_next_kb
    with pytest.raises(ValueError):
        admin_review_done_next_kb("teacher")
    with pytest.raises(ValueError):
        admin_review_done_next_kb("")


def test_done_kb_all_kinds_share_same_back_button():
    """三类审核的「返回审核处理」按钮统一指向 admin:review_tasks。"""
    from bot.keyboards.admin_kb import admin_review_done_next_kb
    for kind in ("edit", "review", "reimburse"):
        kb = admin_review_done_next_kb(kind)
        # 第 2 行是返回按钮
        back_btn = kb.inline_keyboard[1][0]
        assert back_btn.callback_data == "admin:review_tasks", (
            f"kind={kind} 返回按钮应指向 admin:review_tasks，"
            f"实际：{back_btn.callback_data}"
        )


# ============ 2. 三个 handler ack 消息已加 reply_markup ============


def _src(module) -> str:
    return inspect.getsource(module)


def test_admin_review_handler_imports_done_kb():
    import bot.handlers.admin_review as ar
    src = _src(ar)
    assert "admin_review_done_next_kb" in src, (
        "admin_review.py 应 import admin_review_done_next_kb"
    )


def test_admin_review_reject_ack_uses_done_kb_edit():
    """admin_review.py FSM 驳回 ack 消息应带 admin_review_done_next_kb('edit')。"""
    import bot.handlers.admin_review as ar
    src = _src(ar)
    # 锁定函数定义而非调用点；定义关键字：async def _perform_reject_from_message
    idx = src.find("async def _perform_reject_from_message")
    assert idx > 0, "找不到 _perform_reject_from_message 函数定义"
    body = src[idx:idx + 3500]
    assert 'admin_review_done_next_kb("edit")' in body, (
        "_perform_reject_from_message ack 消息应携带 admin_review_done_next_kb('edit')"
    )


def test_rreview_admin_handler_imports_done_kb():
    import bot.handlers.rreview_admin as rra
    src = _src(rra)
    assert "admin_review_done_next_kb" in src


def test_rreview_admin_approve_ack_uses_done_kb_review():
    """rreview_admin.py 评价审核通过 ack 应带 done_kb('review')。

    真正的实现在 `_do_approve_inner`（`_do_approve` / `_do_approve_from_message`
    都是薄包装）。
    """
    import bot.handlers.rreview_admin as rra
    src = _src(rra)
    idx = src.find("async def _do_approve_inner(")
    assert idx > 0, "找不到 _do_approve_inner 函数定义"
    # _do_approve_inner 函数体较长（含 6 步骤 + 报销联动 + 通知超管 + 队列分支等），
    # 用 12000 字符窗口
    body = src[idx:idx + 12000]
    assert 'admin_review_done_next_kb("review")' in body


def test_rreview_admin_reject_ack_uses_done_kb_review():
    """rreview_admin.py _do_reject ack 文字（非空队列分支）应带 done_kb('review')。"""
    import bot.handlers.rreview_admin as rra
    src = _src(rra)
    idx = src.find("async def _do_reject(")
    assert idx > 0
    body = src[idx:idx + 5000]
    # 该函数体内必须出现 done_kb('review') 调用（接到非空队列下的 ack send_message）
    assert 'admin_review_done_next_kb("review")' in body


def test_admin_reimburse_handler_imports_done_kb():
    import bot.handlers.admin_reimburse as ari
    src = _src(ari)
    assert "admin_review_done_next_kb" in src


def test_admin_reimburse_reject_ack_uses_done_kb_reimburse():
    """admin_reimburse.py FSM 驳回 ack 消息应带 admin_review_done_next_kb('reimburse')。"""
    import bot.handlers.admin_reimburse as ari
    src = _src(ari)
    idx = src.find("async def on_reimburse_reject_reason(")
    assert idx > 0
    body = src[idx:idx + 4000]
    assert 'admin_review_done_next_kb("reimburse")' in body


# ============ 3. 审核业务 callback 与 handler 字面量未删 ============


def test_legacy_approve_reject_callbacks_still_in_handlers():
    """审核 approve / reject 的 callback 字面量在各自 handler 中仍存在。

    UX-2 第二项不改 callback 含义，只在 ack 消息上增加 reply_markup。
    """
    import bot.handlers.admin_review as ar
    import bot.handlers.rreview_admin as rra
    import bot.handlers.admin_reimburse as ari

    ar_src = _src(ar)
    rra_src = _src(rra)
    ari_src = _src(ari)

    # 老师资料审核
    assert '"review:approve:' in ar_src or "review:approve:" in ar_src
    assert '"review:reject:' in ar_src or "review:reject:" in ar_src
    # 评价审核（rreview）
    assert 'rreview:approve' in rra_src
    assert 'rreview:reject' in rra_src
    # 报销审核
    assert 'reimburse:approve' in ari_src
    assert 'reimburse:reject' in ari_src


def test_admin_review_tasks_callback_still_present():
    """admin:review_tasks 字面量未删（done_kb 内部及 admin_panel handler 都依赖）。"""
    import bot.keyboards.admin_kb as akb
    import bot.handlers.admin_panel as panel
    kb_src = _src(akb)
    panel_src = _src(panel)
    assert '"admin:review_tasks"' in kb_src
    assert '"admin:review_tasks"' in panel_src


# ============ 4. 不存在自动 approve 下一条逻辑 ============


def test_no_auto_approve_next_in_review_handlers():
    """spec：审核完成后不允许自动批准下一条；只能给按钮让管理员主动点。

    用静态扫描：三个 handler 中『处理下一条』按钮的回调指向各自 entry callback，
    而 entry handler 仅渲染下一条详情，不执行任何 approve / reject 副作用。
    """
    from bot.keyboards.admin_kb import admin_review_done_next_kb
    for kind in ("edit", "review", "reimburse"):
        kb = admin_review_done_next_kb(kind)
        next_btn = kb.inline_keyboard[0][0]
        # 防御：next 按钮 callback 不应触发 approve / reject 动作
        for forbidden in (":approve", ":reject", ":approve_p:", ":reject_preset:"):
            assert forbidden not in next_btn.callback_data, (
                f"kind={kind} 的「处理下一条」按钮 callback 不应触发 approve/reject："
                f"{next_btn.callback_data}"
            )
        # 反向校验：必须以 ":enter" 结尾（各自审核入口）
        assert next_btn.callback_data.endswith(":enter"), (
            f"kind={kind} 的「处理下一条」按钮应指向 *:enter 入口，"
            f"实际：{next_btn.callback_data}"
        )


# ============ 5. 不修改 schema / 审核业务逻辑 ============


def test_schema_migrations_baseline_unchanged():
    """UX-2 第二项不动 schema。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states"}


def test_review_handlers_still_importable():
    """三个审核 handler 仍可正常 import；router 非空。"""
    from bot.handlers.admin_review import router as r1
    from bot.handlers.rreview_admin import router as r2
    from bot.handlers.admin_reimburse import router as r3
    assert r1 is not None
    assert r2 is not None
    assert r3 is not None


def test_reimbursement_amount_function_still_importable():
    """报销金额计算函数仍可 import 且 callable（业务逻辑保护契约）。"""
    from bot.database import compute_reimbursement_amount
    assert callable(compute_reimbursement_amount)


def test_existing_review_action_keyboards_unchanged():
    """既有 review_action_kb / rreview_action_kb / reimburse_action_kb 仍可用且含
    各自 approve / reject 入口（本批不动这些 keyboard）。"""
    from bot.keyboards.admin_kb import (
        review_action_kb, rreview_action_kb, reimburse_action_kb,
    )
    # 老师资料审核操作面板（pseudo args 仅满足签名）
    kb1 = review_action_kb(request_id=1, has_prev=False, has_next=False)
    cbs1 = _all_callbacks(kb1)
    assert any("review:approve:" in c for c in cbs1)
    assert any("review:reject:" in c for c in cbs1)

    kb2 = rreview_action_kb(review_id=1, has_prev=False, has_next=False)
    cbs2 = _all_callbacks(kb2)
    assert any("rreview:approve:" in c for c in cbs2)
    assert any("rreview:reject:" in c for c in cbs2)

    kb3 = reimburse_action_kb(reimb_id=1, user_id=100)
    cbs3 = _all_callbacks(kb3)
    assert any("reimburse:approve:" in c for c in cbs3)
    assert any("reimburse:reject:" in c for c in cbs3)
