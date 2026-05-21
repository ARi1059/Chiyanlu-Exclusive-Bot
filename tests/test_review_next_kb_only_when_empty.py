"""Sprint UX-5 第三项（UX-5.3）：审核完成 next kb 仅在队列空时显示契约测试。

范围：
    - bot.handlers.admin_review.cb_review_approve          老师资料审核
    - bot.handlers.rreview_admin._do_approve_inner         评价通过
    - bot.handlers.rreview_admin._do_reject                评价驳回
    - bot.handlers.admin_reimburse.on_reimburse_reject_reason  报销驳回

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §11.1 决策 1）：
    审核完成后 admin_review_done_next_kb 的显示策略：
        - 非空队列 → 只自动推下一条，**不**附 done_next_kb（避免与自动推送视觉重复）
        - 空队列   → 显示 done_next_kb 给明确出口（处理下一条 / 返回审核处理）

约束：
    - 不改 callback_data；admin_review_done_next_kb 仍按原签名调用
    - 不改 callback.answer 简短 ack 行为
    - cb_reimburse_payout_confirm 不在范围（特殊完成页 reimburse_payout_done_kb，
      跟"自动推下一条"语义不同）
    - 旧的 review_empty_kb / rreview_empty_kb / reimburse_empty_kb 仍存在
      （cb_*_enter 等非"刚审完"路径仍用 empty_kb）
"""
from __future__ import annotations

import inspect

import pytest  # noqa: F401


# ============ helpers ============


def _src(module) -> str:
    return inspect.getsource(module)


def _slice_function(src: str, fn_decl: str, max_size: int = 6000) -> str:
    """从 src 中切出 fn_decl 开头函数的 body（不跨 router decorator / 不跨 async def）。"""
    idx = src.find(fn_decl)
    assert idx > 0, f"找不到 {fn_decl}"
    # 找到下一个 @router 或下一个 async def，取较小的作为函数结束
    end_a = src.find("\n@router", idx + 1)
    end_b = src.find("\nasync def ", idx + 1)
    candidates = [e for e in (end_a, end_b) if e > 0]
    end = min(candidates) if candidates else (idx + max_size)
    return src[idx:end]


# ============================================================
# 1. admin_review.py cb_review_approve
# ============================================================


def test_cb_review_approve_empty_uses_done_next_kb():
    """空队列分支用 admin_review_done_next_kb('edit')，不再用 review_empty_kb。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    body = _slice_function(src, "async def cb_review_approve(")
    # 找到 "if not pending:" 分支
    empty_pos = body.find("if not pending:")
    assert empty_pos > 0
    empty_block = body[empty_pos:empty_pos + 800]
    assert 'admin_review_done_next_kb("edit")' in empty_block
    # 旧 review_empty_kb 不应再被本分支调用
    assert "review_empty_kb()" not in empty_block


def test_cb_review_approve_non_empty_no_done_next_kb():
    """非空队列分支不应附加 done_next_kb（仅自动推下一条）。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    body = _slice_function(src, "async def cb_review_approve(")
    # 整个函数体内 done_next_kb 应只出现在 "if not pending:" 分支
    # 即出现次数应 == 1（在 empty 分支）
    assert body.count("admin_review_done_next_kb") == 1


def test_cb_review_approve_still_calls_show_request_at_index_on_non_empty():
    """非空路径仍调 _show_request_at_index 自动推下一条（业务保护）。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    body = _slice_function(src, "async def cb_review_approve(")
    assert "_show_request_at_index" in body


# ============================================================
# 2. rreview_admin.py _do_approve_inner
# ============================================================


def test_rreview_approve_inner_empty_uses_done_next_kb():
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    body = _slice_function(src, "async def _do_approve_inner(")
    empty_pos = body.find("if not pending:")
    assert empty_pos > 0
    empty_block = body[empty_pos:empty_pos + 1500]
    assert 'admin_review_done_next_kb("review")' in empty_block
    # 不再用 main_menu_kb 切回主面板
    assert "main_menu_kb(" not in empty_block


def test_rreview_approve_inner_non_empty_no_done_next_kb():
    """非空队列分支（含 message 路径）不再附 done_next_kb。"""
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    body = _slice_function(src, "async def _do_approve_inner(")
    # done_next_kb 应只在 empty 分支出现一次
    assert body.count("admin_review_done_next_kb") == 1
    # 找到 empty 分支后的代码（即非空路径）
    empty_pos = body.find("if not pending:")
    after_empty_return = body.find("return", empty_pos)
    non_empty_block = body[after_empty_return:after_empty_return + 1500]
    assert "admin_review_done_next_kb" not in non_empty_block


def test_rreview_approve_inner_non_empty_message_path_still_sends_ack():
    """非空 message 路径仍发简短 ack 文字（行为保护）。"""
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    body = _slice_function(src, "async def _do_approve_inner(")
    # "✅ 已通过评价 #" 应在 message 路径出现
    assert body.count("已通过评价 #") >= 2  # 一次空分支 + 一次非空 message 路径


def test_rreview_approve_inner_still_calls_send_review_at_index():
    """非空路径仍调 _send_review_at_index 自动推下一条。"""
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    body = _slice_function(src, "async def _do_approve_inner(")
    assert "_send_review_at_index" in body


# ============================================================
# 3. rreview_admin.py _do_reject
# ============================================================


def test_rreview_reject_empty_uses_done_next_kb():
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    body = _slice_function(src, "async def _do_reject(")
    empty_pos = body.find("if not pending:")
    assert empty_pos > 0
    empty_block = body[empty_pos:empty_pos + 1500]
    assert 'admin_review_done_next_kb("review")' in empty_block
    assert "main_menu_kb(" not in empty_block


def test_rreview_reject_non_empty_no_done_next_kb():
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    body = _slice_function(src, "async def _do_reject(")
    assert body.count("admin_review_done_next_kb") == 1


def test_rreview_reject_still_calls_send_review_at_index():
    """非空仍走自动推下一条。"""
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    body = _slice_function(src, "async def _do_reject(")
    assert "_send_review_at_index" in body


# ============================================================
# 4. admin_reimburse.py on_reimburse_reject_reason
# ============================================================


def test_reimburse_reject_empty_uses_done_next_kb():
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    body = _slice_function(src, "async def on_reimburse_reject_reason(")
    # empty 分支应有 done_next_kb("reimburse")
    assert 'admin_review_done_next_kb("reimburse")' in body
    # empty 分支位置：在 if pending 的 else
    else_pos = body.rfind("else:")
    assert else_pos > 0
    else_block = body[else_pos:else_pos + 1500]
    assert 'admin_review_done_next_kb("reimburse")' in else_block


def test_reimburse_reject_non_empty_no_done_next_kb():
    """非空 (if pending:) 分支不应附 done_next_kb（仅简短 ack）。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    body = _slice_function(src, "async def on_reimburse_reject_reason(")
    # done_next_kb 应只出现一次（在 else 分支）
    assert body.count("admin_review_done_next_kb") == 1


def test_reimburse_reject_still_shows_next_pending_detail():
    """非空仍渲染下一条详情页（业务保护）。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    body = _slice_function(src, "async def on_reimburse_reject_reason(")
    assert "_render_reimbursement_detail" in body
    assert "reimburse_action_kb" in body


def test_reimburse_reject_no_empty_kb_in_else_branch():
    """空队列分支应改为 done_next_kb，旧 reimburse_empty_kb 不再出现在 else 分支。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    body = _slice_function(src, "async def on_reimburse_reject_reason(")
    else_pos = body.rfind("else:")
    else_block = body[else_pos:else_pos + 800]
    assert "reimburse_empty_kb" not in else_block


# ============================================================
# 5. 其它 handler 不应被误改（保护契约）
# ============================================================


def test_cb_review_enter_still_uses_empty_kb():
    """cb_review_enter（从二级页直接进，发现空队列）仍用 review_empty_kb 兜底，
    与 "刚审完一条 → 空" 语义不同。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    body = _slice_function(src, "async def cb_review_enter(")
    assert "review_empty_kb()" in body


def test_payout_confirm_unchanged_uses_payout_done_kb():
    """cb_reimburse_payout_confirm 是特殊完成页（已用 reimburse_payout_done_kb，
    等价 done_next_kb），UX-5.3 不动该路径。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    body = _slice_function(src, "async def cb_reimburse_payout_confirm(")
    assert "reimburse_payout_done_kb" in body


def test_admin_review_done_next_kb_signature_unchanged():
    """函数签名保持不变（"edit" / "review" / "reimburse" 三个 kind）。"""
    from bot.keyboards.admin_kb import admin_review_done_next_kb
    # 三个 kind 全部能正确构造
    for kind in ("edit", "review", "reimburse"):
        kb = admin_review_done_next_kb(kind)
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "admin:review_tasks" in cbs


# ============================================================
# 6. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable"}
