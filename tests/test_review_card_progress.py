"""Sprint UX-8 第一项（UX-8.1）：评价卡片进度计数 + 提交按钮动态文案契约测试。

范围：
    - bot.handlers.review_card._build_card_text 顶部进度行
    - bot.keyboards.user_kb.review_card_kb missing_count 参数 + 动态提交按钮
    - bot.handlers.review_card.cb_card_submit alert 聚焦"第一个未填项"

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §2.2 痛点 3 + §11.3）：
    用户看不到"我离能提交还差几步"；提交按钮文案静态"😟匿名提交 / 😎默认提交"，
    点击后才弹 alert 列全部未填项。本批：
      - 卡片顶部加进度行 "📊 进度：已完成 N/9 · ✅ 可提交 / 还差 N 项"
      - 提交按钮文案动态切换：未完成 → "还差 N 项（匿名/默认）"；完成 → "✅ 提交（匿名/默认）"
      - alert 改为只提示**第一个**未填项，减少认知负担（其余项数量在卡片顶部已可见）

约束：
    - 纯文案 / keyboard 渲染层；不动 FSM / 提交业务逻辑
    - 不改任何 callback_data（card:submit:anon / card:submit:default 不变）
    - review_card_kb missing_count 默认 None 向后兼容旧 caller
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest  # noqa: F401


# ============ helpers ============


def _run(coro):
    return asyncio.run(coro)


def _src(module) -> str:
    return inspect.getsource(module)


def _flat_buttons(kb) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            out.append(btn)
    return out


def _submit_button_texts(kb) -> tuple[str, str]:
    """提取"匿名提交 / 默认提交"按钮文案。"""
    btns = _flat_buttons(kb)
    anon = next((b.text for b in btns if b.callback_data == "card:submit:anon"), "")
    default = next((b.text for b in btns if b.callback_data == "card:submit:default"), "")
    return anon, default


# ============================================================
# 1. review_card_kb missing_count 行为
# ============================================================


def test_kb_default_keeps_legacy_labels():
    """missing_count=None（默认）→ 旧文案"😟匿名提交 / 😎默认提交"，向后兼容。"""
    from bot.keyboards.user_kb import review_card_kb
    kb = review_card_kb(state_data={})
    anon, default = _submit_button_texts(kb)
    assert anon == "😟 匿名提交"
    assert default == "😎 默认提交"


def test_kb_complete_shows_success_label():
    """missing_count=0 → "✅ 提交（匿名/默认）" 明确"已可提交"。"""
    from bot.keyboards.user_kb import review_card_kb
    kb = review_card_kb(state_data={}, missing_count=0)
    anon, default = _submit_button_texts(kb)
    assert anon == "✅ 提交（匿名）"
    assert default == "✅ 提交（默认）"


def test_kb_incomplete_shows_remaining_count():
    """missing_count>0 → "还差 N 项（匿名/默认）"。"""
    from bot.keyboards.user_kb import review_card_kb
    kb = review_card_kb(state_data={}, missing_count=3)
    anon, default = _submit_button_texts(kb)
    assert "还差 3 项" in anon
    assert "还差 3 项" in default


def test_kb_missing_one_field():
    """边界：missing_count=1 仍正确渲染单数文案。"""
    from bot.keyboards.user_kb import review_card_kb
    kb = review_card_kb(state_data={}, missing_count=1)
    anon, _ = _submit_button_texts(kb)
    assert "还差 1 项" in anon


def test_kb_submit_callbacks_unchanged():
    """callback_data 完全保留（旧 inline button 仍可用）。"""
    from bot.keyboards.user_kb import review_card_kb
    for mc in (None, 0, 5):
        kb = review_card_kb(state_data={}, missing_count=mc)
        cbs = [b.callback_data for b in _flat_buttons(kb)]
        assert "card:submit:anon" in cbs
        assert "card:submit:default" in cbs


def test_kb_other_buttons_preserved():
    """业务保护：edit / cancel 等按钮 callback 仍存在。"""
    from bot.keyboards.user_kb import review_card_kb
    kb = review_card_kb(state_data={}, missing_count=0)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    # 9 个字段编辑入口 + 取消
    assert "card:edit:evidence" in cbs
    assert "card:edit:rating" in cbs
    assert "card:edit:summary" in cbs
    assert "card:cancel" in cbs


# ============================================================
# 2. _build_card_text 顶部进度行
# ============================================================


def test_build_card_text_shows_progress_when_incomplete(monkeypatch):
    """缺项时显示"已完成 N/9 · 还差 M 项"。"""
    from bot.handlers import review_card
    # 模拟 _build_card_text 内部访问 state.get_data()
    fake_state = MagicMock()
    fake_state.get_data = AsyncMock(return_value={
        "teacher_id": 1,
        # 全部字段空 → 9 项缺
    })

    # 模拟 get_teacher 返回（避免真实 DB）
    async def _fake_get_teacher(tid):
        return {"display_name": "T", "is_active": True}
    monkeypatch.setattr(review_card, "get_teacher", _fake_get_teacher)

    text = _run(review_card._build_card_text(fake_state))
    assert "已完成 0/9" in text
    assert "还差 9 项" in text


def test_build_card_text_shows_ready_when_complete(monkeypatch):
    """全部填齐 → "已完成 9/9 · ✅ 可提交"。"""
    from bot.handlers import review_card
    fake_state = MagicMock()
    fake_state.get_data = AsyncMock(return_value={
        "teacher_id": 1,
        "booking_screenshot_file_id": "a",
        "gesture_photo_file_id": "b",
        "rating": "positive",
        "score_humanphoto": 9,
        "score_appearance": 9,
        "score_body": 9,
        "score_service": 9,
        "score_attitude": 9,
        "score_environment": 9,
        "summary": "good service",
    })

    async def _fake_get_teacher(tid):
        return {"display_name": "T", "is_active": True}
    monkeypatch.setattr(review_card, "get_teacher", _fake_get_teacher)

    text = _run(review_card._build_card_text(fake_state))
    assert "已完成 9/9" in text
    assert "✅ 可提交" in text


def test_build_card_text_progress_at_top_above_separator(monkeypatch):
    """进度行应在分隔线（━）之前，第一眼能看到。

    2026-05-21：在进度行和分隔线之间新增了 reimburse_banner
    （💰/📝 标记本条评价是否参与报销路径）；契约调整为
    「进度行 < banner < 分隔线」，进度仍在第一眼能看到的位置。
    """
    from bot.handlers import review_card
    fake_state = MagicMock()
    fake_state.get_data = AsyncMock(return_value={"teacher_id": 1})

    async def _fake_get_teacher(tid):
        return {"display_name": "T", "is_active": True}
    monkeypatch.setattr(review_card, "get_teacher", _fake_get_teacher)

    text = _run(review_card._build_card_text(fake_state))
    lines = text.split("\n")
    assert "评价卡片" in lines[0]
    assert "进度" in lines[1]
    # 分隔线在 banner 之后；进度仍位于分隔线之前
    progress_idx = next(i for i, ln in enumerate(lines) if "进度" in ln)
    sep_idx = next(i for i, ln in enumerate(lines) if "━" in ln)
    assert progress_idx < sep_idx


# ============================================================
# 3. render_card 传 missing_count 到 keyboard
# ============================================================


def test_render_card_passes_missing_count_to_kb():
    """静态契约：render_card 调用 review_card_kb 时应传 missing_count。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def render_card(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "missing_count" in body
    assert "_missing_fields(data)" in body


# ============================================================
# 4. cb_card_submit alert 聚焦第一个未填项
# ============================================================


def test_cb_submit_alert_shows_first_missing_only():
    """alert 文案应只提"先填第一个未填项 + 还差 N 项"，不再列全部项。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def cb_card_submit(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    # 应有 "先填「" + "{miss[0]}" 模式
    assert 'f"⚠️ 先填' in body or "先填「" in body
    # 不应再用旧"还有未填项：\n" + "、".join(miss) 的旧风格
    assert '"、".join(miss)' not in body


def test_cb_submit_keeps_block_logic():
    """业务保护：有未填项时仍 callback.answer + show_alert=True + return（不进入提交流）。"""
    import bot.handlers.review_card as mod
    src = _src(mod)
    idx = src.find("async def cb_card_submit(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "show_alert=True" in body
    # _missing_fields 调用仍在
    assert "_missing_fields(data)" in body
    # 走到提交主流程的入口仍在
    assert "_enter_reimburse_or_submit" in body


# ============================================================
# 5. _missing_fields 行为保护
# ============================================================


def test_missing_fields_all_empty():
    from bot.handlers.review_card import _missing_fields
    miss = _missing_fields({})
    # 9 项全缺
    assert len(miss) == 9


def test_missing_fields_complete():
    from bot.handlers.review_card import _missing_fields
    miss = _missing_fields({
        "booking_screenshot_file_id": "a",
        "gesture_photo_file_id": "b",
        "rating": "positive",
        "score_humanphoto": 9,
        "score_appearance": 9,
        "score_body": 9,
        "score_service": 9,
        "score_attitude": 9,
        "score_environment": 9,
        "summary": "ok",
    })
    assert miss == []


def test_missing_fields_partial():
    """部分填齐：仅看具体未填字段。"""
    from bot.handlers.review_card import _missing_fields
    miss = _missing_fields({
        "booking_screenshot_file_id": "a",
        "gesture_photo_file_id": "b",
        "rating": "positive",
        # 6 维全空 + summary 空 → 7 项缺
    })
    assert len(miss) == 7


# ============================================================
# 6. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable", "20260613_001_teacher_is_deleted", "20260613_002_remove_quick_entry_keywords"}
