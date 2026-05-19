"""Sprint UX-5 第四项（UX-5.4）：报销资格不足时给用户显式提示契约测试。

范围：
    - bot.utils.reimburse_notify.format_reimburse_ineligibility_hint 文案 helper
    - bot.handlers.review_submit._enter_reimbursement_step gate 分支
    - bot.handlers.review_card._enter_reimburse_or_submit gate 分支

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §1 C6 + §4.2 痛点 1 + §11.3）：
    当前 amount<=0 / points<min_pts 时静默跳过，用户无法自查；本批改为
    feature_enabled=True 时显式提示：

        - amount<=0：「💡 老师价位档不在报销范围（仅 8P/9P/10P 可申请）」
        - points<min_pts：「💡 当前积分 X（报销门槛 Y），距离还差 Z 分」+ 引导

约束（与 §11 决策对齐）：
    - feature OFF 时**仍保持静默**——避免暗示用户可申请
    - hint 发送失败仅 logger.warning，不阻塞 _enter_confirm / _finalize_submit
    - 不改 request_reimbursement / _reimburse_amount 状态写入
    - 不改 feature OFF + 资格满足时的 queued 路径
"""
from __future__ import annotations

import inspect

import pytest  # noqa: F401


# ============ helpers ============


def _src(module) -> str:
    return inspect.getsource(module)


# ============================================================
# 1. 文案 helper
# ============================================================


def test_hint_for_amount_zero():
    """amount <= 0 → 老师价位档不在范围的提示。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(amount=0, points=100, min_pts=5)
    assert "价位" in hint or "范围" in hint
    # 不应误报"积分不足"
    assert "积分" not in hint or "不在" in hint


def test_hint_for_amount_negative():
    """compute_reimbursement_amount 可能返回 0 或负——同样的提示。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(amount=-1, points=100, min_pts=5)
    assert "价位" in hint or "范围" in hint


def test_hint_for_points_below_threshold():
    """points < min_pts → 积分差额提示。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(amount=50, points=3, min_pts=5)
    assert "3" in hint  # 当前积分
    assert "5" in hint  # 门槛
    assert "2" in hint  # 差额
    # 应有获取积分的引导
    assert "评价" in hint or "积分" in hint


def test_hint_diff_floor_zero_when_already_meeting():
    """边界：points >= min_pts 时本不该调本函数；防御性返回 diff=0 而不是负数。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(amount=50, points=10, min_pts=5)
    # diff = max(0, 5-10) = 0，不应出现负数
    assert "-5" not in hint
    assert "差 0" in hint or "积分门槛" in hint


def test_hint_amount_zero_takes_priority_over_points():
    """同时 amount<=0 且 points<min_pts → amount 提示优先（更明确）。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(amount=0, points=1, min_pts=5)
    assert "价位" in hint or "范围" in hint
    # 不应同时提两个原因
    assert "门槛" not in hint


# ============================================================
# 2. review_submit.py gate 分支静态契约
# ============================================================


def test_review_submit_gate_calls_hint_when_feature_enabled():
    """_enter_reimbursement_step 资格不满足分支内必须出现 hint 发送代码。"""
    import bot.handlers.review_submit as mod
    src = _src(mod)
    idx = src.find("async def _enter_reimbursement_step(")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    # 必须 import / 调用 helper
    assert "format_reimburse_ineligibility_hint" in body
    # 必须在 feature_enabled 守卫之内（OFF 时静默）
    feature_pos = body.find("if feature_enabled:")
    hint_pos = body.find("format_reimburse_ineligibility_hint")
    assert 0 < feature_pos < hint_pos, (
        "hint 调用必须放在 if feature_enabled: 块内，避免功能 OFF 时仍提示"
    )


def test_review_submit_gate_off_feature_stays_silent():
    """feature OFF 路径不应包含任何 hint 文字（保持静默约束）。"""
    import bot.handlers.review_submit as mod
    src = _src(mod)
    idx = src.find("async def _enter_reimbursement_step(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    # "if not feature_enabled:" 分支内不应有 hint 调用
    off_idx = body.find("if not feature_enabled:")
    if off_idx > 0:
        next_block = body[off_idx:off_idx + 800]
        assert "format_reimburse_ineligibility_hint" not in next_block


def test_review_submit_gate_failure_state_writes_unchanged():
    """资格不满足分支仍写 request_reimbursement=0 / _reimburse_amount=0（业务保护）。"""
    import bot.handlers.review_submit as mod
    src = _src(mod)
    idx = src.find("async def _enter_reimbursement_step(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "request_reimbursement=0" in body
    assert "_reimburse_amount=0" in body
    assert "_enter_confirm" in body


# ============================================================
# 3. review_card.py gate 分支静态契约
# ============================================================


def test_review_card_gate_calls_hint_when_feature_enabled():
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def _enter_reimburse_or_submit(")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "format_reimburse_ineligibility_hint" in body
    feature_pos = body.find("if feature_enabled:")
    hint_pos = body.find("format_reimburse_ineligibility_hint")
    assert 0 < feature_pos < hint_pos


def test_review_card_gate_off_feature_stays_silent():
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def _enter_reimburse_or_submit(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    off_idx = body.find("if not feature_enabled:")
    if off_idx > 0:
        next_block = body[off_idx:off_idx + 800]
        assert "format_reimburse_ineligibility_hint" not in next_block


def test_review_card_gate_failure_state_writes_unchanged():
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def _enter_reimburse_or_submit(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "request_reimbursement=0" in body
    assert "_reimburse_amount=0" in body
    assert "_finalize_submit" in body


# ============================================================
# 4. hint 发送失败容错
# ============================================================


def test_review_submit_gate_hint_wrapped_in_try():
    """hint 发送应在 try/except 内，避免 send_message 失败阻塞 _enter_confirm。"""
    import bot.handlers.review_submit as mod
    src = _src(mod)
    idx = src.find("async def _enter_reimbursement_step(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    hint_pos = body.find("format_reimburse_ineligibility_hint")
    # 向上找最近的 try:
    try_pos = body.rfind("try:", 0, hint_pos)
    feature_pos = body.find("if feature_enabled:")
    # try 应在 hint 之前 且 在 feature 守卫之内
    assert feature_pos < try_pos < hint_pos


def test_review_card_gate_hint_wrapped_in_try():
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def _enter_reimburse_or_submit(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    hint_pos = body.find("format_reimburse_ineligibility_hint")
    try_pos = body.rfind("try:", 0, hint_pos)
    feature_pos = body.find("if feature_enabled:")
    assert feature_pos < try_pos < hint_pos


# ============================================================
# 5. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert MIGRATIONS == []
