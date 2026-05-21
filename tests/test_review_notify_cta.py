"""Sprint UX-4 第三项（UX-4.3）：评价审核通过 / 驳回通知 + CTA 按钮契约测试。

范围：bot/utils/rreview_notify.py 新增的两个 keyboard 函数 + 两个 notify 接入。

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §1 C1 + §11.3）：
    评价者收到审核通知（通过 / 驳回）当前是纯文本死胡同，本批附 CTA keyboard。

    通过 → [📝 个人评价主页] [🔥 找下一个老师] [🏠 返回主菜单]
    驳回 → [📝 个人评价主页] [📩 联系超管 (URL, 仅当 config 配置)] [🏠 返回主菜单]

    "联系超管" URL 读取优先级：review_contact_url → lottery_contact_url；
    双空时不显示该按钮（不引入死链）。

决策记录（与 §11.3 范围里"用 deep link"差异）：
    本批采用 callback 风格（与 UX-4.1 / UX-4.2 一致）。私聊里 bot → user 的
    inline button callback 完全能工作；deep link 需要新增 start_router parser，
    超出本批范围。如未来 callback 失败率上升，再补 deep link 兜底。

约束：
    - 不改 callback_data；user:write_review / user:find / user:main 早已存在
    - 不引入 schema 迁移
    - 不改 _safe_send_text 失败容错行为
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
        prefix=f"test_rrcta_{uuid.uuid4().hex}_", suffix=".db",
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


def _src(module) -> str:
    return inspect.getsource(module)


def _flat_buttons(kb) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            out.append(btn)
    return out


def _patch_review_lookup(monkeypatch, *, user_id=1001, teacher_name="林老师"):
    """让 notify_review_approved / rejected 内部的 get_teacher_review 与
    get_teacher 返回 fixture 数据，避免依赖真实 DB 插入。"""
    fake_review = {
        "id": 42,
        "user_id": user_id,
        "teacher_id": 99,
        "rating": "positive",
        "overall_score": 9,
        "summary": "very good",
        "anonymous": 0,
        "booking_screenshot_file_id": "boo",
        "gesture_photo_file_id": "ges",
    }
    fake_teacher = {"display_name": teacher_name, "id": 99}

    async def _fake_get_review(rid):
        return fake_review if rid == 42 else None

    async def _fake_get_teacher(tid):
        return fake_teacher if tid == 99 else None

    monkeypatch.setattr(
        "bot.utils.rreview_notify.get_teacher_review", _fake_get_review,
    )
    monkeypatch.setattr(
        "bot.utils.rreview_notify.get_teacher", _fake_get_teacher,
    )


# ============================================================
# 1. approved keyboard（同步，无 config）
# ============================================================


def test_approved_kb_has_three_buttons():
    from bot.utils.rreview_notify import build_user_review_approved_kb
    kb = build_user_review_approved_kb()
    assert len(_flat_buttons(kb)) == 3


def test_approved_kb_contains_required_callbacks():
    from bot.utils.rreview_notify import build_user_review_approved_kb
    kb = build_user_review_approved_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "user:write_review" in cbs
    assert "user:find" in cbs
    assert "user:main" in cbs


def test_approved_kb_no_url_buttons():
    from bot.utils.rreview_notify import build_user_review_approved_kb
    kb = build_user_review_approved_kb()
    for b in _flat_buttons(kb):
        assert b.url is None


def test_approved_kb_order_main_last():
    """user:main 兜底应在最后；高频项在前。"""
    from bot.utils.rreview_notify import build_user_review_approved_kb
    kb = build_user_review_approved_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert cbs.index("user:main") == len(cbs) - 1


# ============================================================
# 2. rejected keyboard（异步，依赖 config）
# ============================================================


def test_rejected_kb_when_no_contact_has_two_callbacks(temp_db):
    """config 双空时：keyboard 只含 [📝 个人评价主页] + [🏠 返回主菜单] 两个 callback。"""
    from bot.utils.rreview_notify import build_user_review_rejected_kb
    kb = _run(build_user_review_rejected_kb())
    btns = _flat_buttons(kb)
    assert len(btns) == 2
    cbs = [b.callback_data for b in btns]
    assert "user:write_review" in cbs
    assert "user:main" in cbs
    for b in btns:
        assert b.url is None


def test_rejected_kb_falls_back_to_lottery_contact_url(temp_db):
    from bot.database import set_config
    from bot.utils.rreview_notify import build_user_review_rejected_kb
    _run(set_config("lottery_contact_url", "https://t.me/L"))
    kb = _run(build_user_review_rejected_kb())
    btns = _flat_buttons(kb)
    assert len(btns) == 3
    # 应有一个按钮 url 指向 lottery_contact_url
    url_btns = [b for b in btns if b.url]
    assert len(url_btns) == 1
    assert url_btns[0].url == "https://t.me/L"
    assert "超管" in url_btns[0].text or "联系" in url_btns[0].text


def test_rejected_kb_prefers_review_contact_url_over_lottery(temp_db):
    from bot.database import set_config
    from bot.utils.rreview_notify import build_user_review_rejected_kb
    _run(set_config("lottery_contact_url", "https://t.me/L"))
    _run(set_config("review_contact_url", "https://t.me/R"))
    kb = _run(build_user_review_rejected_kb())
    url_btns = [b for b in _flat_buttons(kb) if b.url]
    assert len(url_btns) == 1
    assert url_btns[0].url == "https://t.me/R"


def test_rejected_kb_blank_contact_url_falls_back(temp_db):
    from bot.database import set_config
    from bot.utils.rreview_notify import build_user_review_rejected_kb
    _run(set_config("review_contact_url", "   "))
    _run(set_config("lottery_contact_url", "https://t.me/L"))
    kb = _run(build_user_review_rejected_kb())
    url_btns = [b for b in _flat_buttons(kb) if b.url]
    assert len(url_btns) == 1
    assert url_btns[0].url == "https://t.me/L"


# ============================================================
# 3. notify_review_approved 行为
# ============================================================


def test_notify_approved_attaches_keyboard(temp_db, monkeypatch):
    """通过通知发送时应附 reply_markup（user:write_review + user:find + user:main）。"""
    _patch_review_lookup(monkeypatch)
    from bot.utils.rreview_notify import notify_review_approved
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(notify_review_approved(bot, review_id=42))
    bot.send_message.assert_awaited_once()
    kb = bot.send_message.await_args.kwargs.get("reply_markup")
    assert kb is not None
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "user:write_review" in cbs
    assert "user:find" in cbs
    assert "user:main" in cbs


def test_notify_approved_text_still_contains_required_lines(temp_db, monkeypatch):
    """UX-4.3 不应破坏原通过文案契约（含老师名、评级、感谢）。"""
    _patch_review_lookup(monkeypatch, teacher_name="林老师")
    from bot.utils.rreview_notify import notify_review_approved
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(notify_review_approved(bot, review_id=42))
    text = bot.send_message.await_args.kwargs.get("text", "")
    assert "通过审核" in text
    assert "林老师" in text
    assert "感谢" in text


# ============================================================
# 4. notify_review_rejected 行为
# ============================================================


def test_notify_rejected_attaches_keyboard(temp_db, monkeypatch):
    _patch_review_lookup(monkeypatch)
    from bot.utils.rreview_notify import notify_review_rejected
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(notify_review_rejected(bot, review_id=42, reason="证据不充分"))
    bot.send_message.assert_awaited_once()
    kb = bot.send_message.await_args.kwargs.get("reply_markup")
    assert kb is not None
    btns = _flat_buttons(kb)
    cbs = [b.callback_data for b in btns]
    assert "user:write_review" in cbs
    assert "user:main" in cbs


def test_notify_rejected_text_contains_reason(temp_db, monkeypatch):
    _patch_review_lookup(monkeypatch)
    from bot.utils.rreview_notify import notify_review_rejected
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(notify_review_rejected(bot, review_id=42, reason="重复提交"))
    text = bot.send_message.await_args.kwargs.get("text", "")
    assert "未通过审核" in text
    assert "重复提交" in text


def test_notify_rejected_text_handles_none_reason(temp_db, monkeypatch):
    """reason=None 时显示"未填写"（保留既有契约）。"""
    _patch_review_lookup(monkeypatch)
    from bot.utils.rreview_notify import notify_review_rejected
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(notify_review_rejected(bot, review_id=42, reason=None))
    text = bot.send_message.await_args.kwargs.get("text", "")
    assert "未填写" in text


def test_notify_rejected_keyboard_contains_url_when_configured(temp_db, monkeypatch):
    """config 配 contact_url 时驳回通知 keyboard 含 [📩 联系超管] URL 按钮。"""
    from bot.database import set_config
    _patch_review_lookup(monkeypatch)
    _run(set_config("lottery_contact_url", "https://t.me/super"))
    from bot.utils.rreview_notify import notify_review_rejected
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(notify_review_rejected(bot, review_id=42, reason="x"))
    kb = bot.send_message.await_args.kwargs.get("reply_markup")
    url_btns = [b for b in _flat_buttons(kb) if b.url]
    assert len(url_btns) == 1
    assert url_btns[0].url == "https://t.me/super"


# ============================================================
# 5. callback handler 存在性
# ============================================================


def test_user_write_review_callback_registered():
    import bot.handlers.review_submit as mod
    src = _src(mod)
    assert 'F.data == "user:write_review"' in src


def test_user_find_callback_registered():
    import bot.handlers.user_panel as mod
    src = _src(mod)
    assert 'F.data == "user:find"' in src


def test_user_main_callback_registered():
    import bot.handlers.user_panel as mod
    src = _src(mod)
    assert 'F.data == "user:main"' in src


# ============================================================
# 6. 容错保留 + 无 schema 迁移
# ============================================================


def test_safe_send_text_failure_does_not_raise(temp_db, monkeypatch):
    """bot.send_message 抛异常时 notify 不应向上抛（保留 _safe_send_text 容错）。"""
    from aiogram.exceptions import TelegramForbiddenError
    _patch_review_lookup(monkeypatch)
    from bot.utils.rreview_notify import notify_review_rejected
    bot = MagicMock()
    bot.send_message = AsyncMock(
        side_effect=TelegramForbiddenError(method="send_message", message="blocked"),
    )
    # 不抛
    _run(notify_review_rejected(bot, review_id=42, reason="x"))


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable"}
