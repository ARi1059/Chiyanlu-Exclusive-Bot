"""报销资格 hint 文案 + 2026-05-21 评价前置改造后的契约测试。

2026-05-21 改动：报销资格判定提到选老师之后立即做（intent 前置）；
原 review_card._enter_reimburse_or_submit 在 submit 时刻 gate 的逻辑被
拆分到：
    - bot.utils.reimburse_eligibility.is_user_reimburse_eligible_for_review
      （前置预判，5 个 reason 分支）
    - bot.handlers.review_card.start_card_review
      （把预判结果存进 state.data["_reimburse_eligibility_info"]）
    - bot.handlers.review_card._finalize_submit
      （req=0 + reason 非 None 时把 hint 拼到提交成功页尾）

UX 目标：
    - eligible → 用户在 intent 屏看到「是否参与报销」选择
    - ineligible → 跳过 intent，进卡片；提交成功后附 hint 告知原因
    - 用户主动选「否」 reason=None，不附 hint（避免劝退式打扰）

hint 文案分支（按优先级）：
    - reason="feature_off"      → "💡 报销功能当前暂关闭..."
    - reason="amount_zero" / amount<=0
                               → "💡 老师价位档不在报销范围（仅 ≦800 / 900 / ≧1000 元）"
    - reason="pool_exhausted"  → "💡 本月报销池已用完（剩 X 元）..."
    - reason="below_threshold" / points<min_pts
                               → "💡 当前积分 X（门槛 Y），距离还差 Z 分..."
"""
from __future__ import annotations

import inspect

import pytest  # noqa: F401


def _src(module) -> str:
    return inspect.getsource(module)


# ============================================================
# 1. 文案 helper 旧分支（无 reason 参数，按 amount / points 反推）
# ============================================================


def test_hint_for_amount_zero():
    """amount <= 0 → 老师价位档不在范围的提示。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(amount=0, points=100, min_pts=5)
    assert "价位" in hint or "范围" in hint
    assert "积分" not in hint or "不在" in hint


def test_hint_for_amount_negative():
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(amount=-1, points=100, min_pts=5)
    assert "价位" in hint or "范围" in hint


def test_hint_for_points_below_threshold():
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(amount=50, points=3, min_pts=5)
    assert "3" in hint
    assert "5" in hint
    assert "2" in hint
    assert "评价" in hint or "积分" in hint


def test_hint_diff_floor_zero_when_already_meeting():
    """防御性：points >= min_pts 时返回 diff=0 而非负数。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(amount=50, points=10, min_pts=5)
    assert "-5" not in hint


def test_hint_amount_zero_takes_priority_over_points():
    """同时 amount<=0 + points<min_pts → amount 提示优先。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(amount=0, points=1, min_pts=5)
    assert "价位" in hint or "范围" in hint
    assert "门槛" not in hint


# ============================================================
# 2. 文案 helper 新分支（reason 参数，2026-05-21）
# ============================================================


def test_hint_reason_feature_off():
    """reason='feature_off' → 报销功能当前关闭。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(
        amount=100, points=10, min_pts=5, reason="feature_off",
    )
    assert "关闭" in hint or "暂" in hint
    # 不应让用户误以为"还差几分"
    assert "差" not in hint or "暂" in hint


def test_hint_reason_pool_exhausted():
    """reason='pool_exhausted' → 本月池子已用完，含剩余数。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(
        amount=100, points=10, min_pts=5,
        reason="pool_exhausted", pool_remaining=0,
    )
    assert "池" in hint
    assert "0" in hint  # 剩余金额渲染


def test_hint_reason_pool_exhausted_negative_remaining_floor_zero():
    """剩余金额负数（边缘情况）应渲染为 0，不暴露负数。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(
        amount=100, points=10, min_pts=5,
        reason="pool_exhausted", pool_remaining=-50,
    )
    assert "-50" not in hint
    assert "0" in hint


def test_hint_reason_amount_zero_explicit():
    """显式 reason='amount_zero' 走价位档分支，不依赖 amount 入参反推。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(
        amount=100, points=10, min_pts=5, reason="amount_zero",
    )
    assert "价位" in hint or "范围" in hint


def test_hint_reason_below_threshold_explicit():
    """显式 reason='below_threshold' 走积分差额分支。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(
        amount=100, points=3, min_pts=5, reason="below_threshold",
    )
    assert "3" in hint
    assert "5" in hint
    assert "2" in hint


def test_hint_amount_zero_label_updated_to_800_900_1000():
    """2026-05-21：amount_zero 文案对齐用户描述「≦800 / 900 / ≧1000」。"""
    from bot.utils.reimburse_notify import format_reimburse_ineligibility_hint
    hint = format_reimburse_ineligibility_hint(amount=0, points=10, min_pts=5)
    assert "800" in hint and "900" in hint and "1000" in hint


# ============================================================
# 3. review_card._finalize_submit 静态契约（新位置）
# ============================================================


def test_finalize_submit_imports_hint_formatter():
    """_finalize_submit 应能调 format_reimburse_ineligibility_hint
    （顶层 import 即可，不要求在函数体内显式 import）。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    assert "format_reimburse_ineligibility_hint" in src


def test_finalize_submit_reads_eligibility_info_from_state():
    """_finalize_submit 应从 state.data 读 _reimburse_eligibility_info 决定是否拼 hint。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def _finalize_submit(")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "_reimburse_eligibility_info" in body
    assert "reason" in body
    assert "format_reimburse_ineligibility_hint" in body


def test_finalize_submit_only_appends_hint_when_req_zero():
    """_finalize_submit hint 拼接应 gate 在 req == 0：req=1 时已是报销路径，
    不需要 ineligibility hint。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def _finalize_submit(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    req_pos = body.find("req == 0")
    hint_pos = body.find("format_reimburse_ineligibility_hint")
    assert 0 < req_pos < hint_pos


def test_finalize_submit_hint_wrapped_in_try():
    """hint 格式化失败仅 logger.warning，不阻塞落库 + 通知。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def _finalize_submit(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    hint_pos = body.find("format_reimburse_ineligibility_hint")
    try_pos = body.rfind("try:", 0, hint_pos)
    # try 块必须包围 hint 调用
    assert 0 < try_pos < hint_pos


# ============================================================
# 4. start_card_review 调资格预判 helper
# ============================================================


def test_start_card_review_calls_eligibility_helper():
    """start_card_review 在校验通过后必须调 is_user_reimburse_eligible_for_review。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def start_card_review(")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "is_user_reimburse_eligible_for_review" in body
    # 调用必须在 subreq 校验通过后
    subreq_pos = body.find("check_user_subscribed(")
    eligible_pos = body.find("is_user_reimburse_eligible_for_review(")
    assert 0 < subreq_pos < eligible_pos


def test_start_card_review_routes_eligible_to_intent_state():
    """eligible 用户应进 choosing_reimburse_intent；ineligible 进 card。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def start_card_review(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "choosing_reimburse_intent" in body
    # 同时也要有 card 分支（ineligible 路径）
    assert "CardReviewStates.card" in body


# ============================================================
# 5. schema 迁移注册（2026-05-21 新增一条）
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {
        "20260520_001_teacher_draft_states",
        "20260520_002_quick_entry_keywords",
        "20260521_001_teacher_reviews_gesture_nullable",
    }
