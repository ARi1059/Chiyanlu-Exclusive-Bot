"""Sprint UX-8 第三项第一批（UX-8.3-A）：评价侧空状态加 CTA 引导契约测试。

范围：
    - bot.keyboards.user_kb.review_list_empty_kb 新增 keyboard
    - bot.handlers.review_list.cb_teacher_reviews 0 评价分支改为 edit_text + 完整页面
    - bot.utils.review_detail_render.format_review_stats_block rc=0 时
      改为返回"📊 0 条车评，欢迎首评"（既有空字符串契约修订）

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §2.2 痛点 12 + §11.3）：
    用户从详情页点 [📖 查看全部评价] 进入空列表 → 当前只弹 alert 一闪而过，
    转化为引导首评的机会被浪费。本批：
      - 列表页 edit_text 渲染完整空状态页面 + [📝 写第一条评价] CTA + 返回详情
      - 详情页统计块 0 评价时显示"📊 0 条车评，欢迎首评 🎉"（详情页 keyboard
        已有 [📝 写评价] 按钮，本块仅文字提示）

约束：
    - 复用既有 callback：review:start:<teacher_id> 是 review_submit.py 既有入口
    - 不引入 schema 迁移
    - 详情页统计块从空字符串改为非空——会影响详情页渲染（多一行），是有意为之
"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


# ============ helpers ============


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_empty_cta_{uuid.uuid4().hex}_", suffix=".db",
    )
    os.close(fd)
    from bot.config import config as _config
    original_path = _config.database_path
    _config.database_path = path
    try:
        from bot.database import init_db
        asyncio.run(init_db())
        yield path
    finally:
        _config.database_path = original_path
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass


def _run(coro):
    return asyncio.run(coro)


def _flat_buttons(kb) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            out.append(btn)
    return out


def _src(module) -> str:
    return inspect.getsource(module)


async def _make_teacher(teacher_id: int = 99, name: str = "测试老师") -> None:
    from bot.database import get_db
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO teachers
               (user_id, username, display_name, region, price, tags, button_url)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (teacher_id, f"t{teacher_id}", name, "北京", "300", "[]", "https://t.me/x"),
        )
        await db.commit()
    finally:
        await db.close()


# ============================================================
# 1. review_list_empty_kb keyboard 契约
# ============================================================


def test_empty_kb_has_write_first_button():
    """空 keyboard 第一个按钮应是 [📝 写第一条评价] → review:start:<id>。"""
    from bot.keyboards.user_kb import review_list_empty_kb
    kb = review_list_empty_kb(teacher_id=42)
    btns = _flat_buttons(kb)
    first = btns[0]
    assert "写第一条" in first.text or "评价" in first.text
    assert first.callback_data == "review:start:42"


def test_empty_kb_has_back_to_detail():
    from bot.keyboards.user_kb import review_list_empty_kb
    kb = review_list_empty_kb(teacher_id=42)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "teacher:view:42" in cbs


def test_empty_kb_callbacks_reuse_existing_namespaces():
    """所有 callback 都应复用既有命名空间：review:start:* / teacher:view:*。"""
    from bot.keyboards.user_kb import review_list_empty_kb
    kb = review_list_empty_kb(teacher_id=42)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    for cb in cbs:
        assert cb.startswith("review:start:") or cb.startswith("teacher:view:")


def test_empty_kb_has_only_two_buttons():
    """空 keyboard 仅含 [写第一条] + [返回详情] 两个按钮。"""
    from bot.keyboards.user_kb import review_list_empty_kb
    kb = review_list_empty_kb(teacher_id=42)
    assert len(_flat_buttons(kb)) == 2


# ============================================================
# 2. cb_teacher_reviews 0 评价分支端到端
# ============================================================


def test_cb_teacher_reviews_empty_uses_edit_text_not_alert(temp_db):
    """0 评价时应 edit_text（渲染完整页面），不再只 callback.answer alert。"""
    _run(_make_teacher(teacher_id=42, name="林老师"))
    from bot.handlers.review_list import cb_teacher_reviews

    cb = MagicMock()
    cb.data = "teacher:reviews:42"
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    _run(cb_teacher_reviews(cb))
    # edit_text 应被调用一次
    cb.message.edit_text.assert_awaited_once()
    call = cb.message.edit_text.await_args
    text = call.args[0] if call.args else call.kwargs.get("text", "")
    assert "暂无评价" in text
    assert "林老师" in text


def test_cb_teacher_reviews_empty_attaches_empty_kb(temp_db):
    """0 评价页应附带 review_list_empty_kb（含 [📝 写第一条] CTA）。"""
    _run(_make_teacher(teacher_id=42))
    from bot.handlers.review_list import cb_teacher_reviews

    cb = MagicMock()
    cb.data = "teacher:reviews:42"
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    _run(cb_teacher_reviews(cb))
    call = cb.message.edit_text.await_args
    kb = call.kwargs.get("reply_markup")
    assert kb is not None
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "review:start:42" in cbs
    assert "teacher:view:42" in cbs


def test_cb_teacher_reviews_empty_falls_back_when_edit_fails(temp_db):
    """edit_text 抛异常时仍 ack callback（避免按钮显示 loading）。"""
    _run(_make_teacher(teacher_id=42))
    from bot.handlers.review_list import cb_teacher_reviews

    cb = MagicMock()
    cb.data = "teacher:reviews:42"
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(side_effect=RuntimeError("edit fail"))
    cb.answer = AsyncMock(return_value=None)
    _run(cb_teacher_reviews(cb))
    # 仍调 answer
    cb.answer.assert_awaited()


# ============================================================
# 3. format_review_stats_block rc=0 行为
# ============================================================


def test_stats_block_returns_empty_when_stats_none():
    """stats=None 仍返回空字符串（详情页省略整段）。"""
    from bot.utils.review_detail_render import format_review_stats_block
    assert format_review_stats_block(None) == ""


def test_stats_block_returns_invite_line_when_zero_reviews():
    """rc=0 时应返回"📊 0 条车评，欢迎首评"提示行，而非空字符串。"""
    from bot.utils.review_detail_render import format_review_stats_block
    result = format_review_stats_block({"review_count": 0})
    assert result != ""
    assert "0 条" in result
    assert "首评" in result


def test_stats_block_returns_full_stats_when_has_reviews():
    """review_count > 0 时仍返回 4 行完整统计（既有契约）。"""
    from bot.utils.review_detail_render import format_review_stats_block
    result = format_review_stats_block({
        "review_count": 10,
        "positive_count": 8,
        "neutral_count": 1,
        "negative_count": 1,
        "avg_overall": 8.5,
        "avg_humanphoto": 9.0,
        "avg_service": 8.0,
        "avg_appearance": 8.5,
        "avg_attitude": 8.5,
        "avg_body": 8.0,
        "avg_environment": 8.5,
    })
    assert "10 条车评" in result
    # 至少 3 行（spec §5 是 4 行）
    assert result.count("\n") >= 2


# ============================================================
# 4. 非空列表分支保护（业务保护）
# ============================================================


async def _make_review(teacher_id: int, user_id: int, *, status="approved"):
    """便利：插入一条 teacher_review。"""
    from bot.database import get_db
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO teacher_reviews
               (teacher_id, user_id,
                booking_screenshot_file_id, gesture_photo_file_id,
                rating,
                score_humanphoto, score_appearance, score_body,
                score_service, score_attitude, score_environment,
                overall_score, summary, status)
               VALUES (?, ?, 'a', 'b', 'positive',
                       9, 9, 9, 9, 9, 9, 9, 'ok', ?)""",
            (teacher_id, user_id, status),
        )
        await db.commit()
    finally:
        await db.close()


def test_cb_teacher_reviews_with_reviews_still_uses_pagination_kb(temp_db):
    """非空列表仍走旧的分页渲染 + review_list_pagination_kb（业务保护）。"""
    _run(_make_teacher(teacher_id=42))
    _run(_make_review(42, 1001))
    from bot.handlers.review_list import cb_teacher_reviews

    cb = MagicMock()
    cb.data = "teacher:reviews:42"
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    _run(cb_teacher_reviews(cb))
    call = cb.message.edit_text.await_args
    text = call.args[0] if call.args else call.kwargs.get("text", "")
    # 非空：应有标题 + 评价列表，不应有"暂无评价"
    assert "暂无评价" not in text
    kb = call.kwargs.get("reply_markup")
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    # 分页 kb 含返回老师详情按钮
    assert "teacher:view:42" in cbs
    # 没有 [📝 写第一条] 按钮（那是空状态专用）
    assert "review:start:42" not in cbs


# ============================================================
# 5. 不引入 schema 迁移 / 不改 callback_data
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states"}


def test_no_new_callback_data_introduced():
    """空 keyboard 全部复用既有 callback；不应有 review:write_first 等新 callback。"""
    from bot.keyboards.user_kb import review_list_empty_kb
    kb = review_list_empty_kb(teacher_id=42)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    # 仅 review:start:* + teacher:view:* 既有命名空间
    new_cb = [c for c in cbs if not (
        c.startswith("review:start:") or c.startswith("teacher:view:")
    )]
    assert new_cb == [], f"新引入了 callback: {new_cb}"
