"""scripts/sync_review_promo_footer.py 契约测试（2026-05-20）。

覆盖：
    - list_published_review_ids：只取 discussion_msg_id NOT NULL 的行
    - _build_new_text_and_kb：缺评价 / 缺老师 / 缺消息引用 → 返回 skip 原因
    - edit_one_review：dry-run / 成功 / message not modified / not found /
      forbidden / RetryAfter 的处理
    - 参数解析：--execute / --limit / --throttle-ms 默认值

约束：
    - 不真发 Telegram 请求；bot 全部 mock
    - temp_db fixture 与其它测试同构
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# 把项目根加入 sys.path（与脚本本身相同的策略）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 显式 import 脚本模块（不在 bot/ 包里，直接 file 路径）
import importlib.util as _util


def _import_script_module():
    """每次测试拿到全新模块；避免跨用例污染。"""
    path = _ROOT / "scripts" / "sync_review_promo_footer.py"
    spec = _util.spec_from_file_location("sync_review_promo_footer", path)
    mod = _util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


@pytest.fixture(scope="module")
def script_mod():
    return _import_script_module()


# ============ temp_db ============


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_syncfooter_{uuid.uuid4().hex}_", suffix=".db",
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


async def _make_teacher(user_id: int = 99, display_name: str = "林老师"):
    from bot.database import get_db
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO teachers
               (user_id, username, display_name, region, price, tags, button_url)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, f"u{user_id}", display_name, "成都", "500", "[]",
             "https://t.me/example"),
        )
        await db.commit()
        return user_id
    finally:
        await db.close()


async def _make_review(
    *,
    teacher_id: int,
    user_id: int = 1001,
    discussion_chat_id: int | None = -1001234567890,
    discussion_msg_id: int | None = 555,
    status: str = "approved",
    summary: str = "体验不错",
) -> int:
    from bot.database import get_db
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO teacher_reviews
               (user_id, teacher_id, booking_screenshot_file_id,
                gesture_photo_file_id, rating,
                score_humanphoto, score_appearance, score_body,
                score_service, score_attitude, score_environment,
                overall_score, summary, status,
                discussion_chat_id, discussion_msg_id, published_at)
               VALUES (?, ?, 'boo', 'ges', 'positive',
                       9, 8.5, 8, 9.5, 9, 8, 8.67, ?, ?, ?, ?, '2026-05-19 10:00:00')""",
            (user_id, teacher_id, summary, status,
             discussion_chat_id, discussion_msg_id),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


# ============================================================
# 1. list_published_review_ids
# ============================================================


def test_list_published_only_includes_msg_id_not_null(temp_db, script_mod):
    tid = _run(_make_teacher())
    rid_ok = _run(_make_review(teacher_id=tid, discussion_msg_id=111))
    _run(_make_review(teacher_id=tid, discussion_msg_id=None, user_id=1002))
    _run(_make_review(teacher_id=tid, discussion_chat_id=None, user_id=1003))
    ids = _run(script_mod.list_published_review_ids())
    assert rid_ok in ids
    assert len(ids) == 1


def test_list_published_returns_empty_when_none(temp_db, script_mod):
    ids = _run(script_mod.list_published_review_ids())
    assert ids == []


def test_list_published_orders_by_published_at(temp_db, script_mod):
    """按 published_at 升序：早的在前。"""
    tid = _run(_make_teacher())
    # 通过 raw SQL 控制 published_at
    from bot.database import get_db

    async def _set_published(rid: int, ts: str):
        db = await get_db()
        try:
            await db.execute(
                "UPDATE teacher_reviews SET published_at = ? WHERE id = ?",
                (ts, rid),
            )
            await db.commit()
        finally:
            await db.close()

    rid_a = _run(_make_review(teacher_id=tid, discussion_msg_id=111, user_id=1001))
    rid_b = _run(_make_review(teacher_id=tid, discussion_msg_id=222, user_id=1002))
    _run(_set_published(rid_a, "2026-04-01 10:00:00"))
    _run(_set_published(rid_b, "2026-05-15 10:00:00"))
    ids = _run(script_mod.list_published_review_ids())
    assert ids == [rid_a, rid_b]


# ============================================================
# 2. _build_new_text_and_kb 边界
# ============================================================


def test_build_returns_skip_no_review(temp_db, script_mod):
    built, reason = _run(script_mod._build_new_text_and_kb("Bot", 9999))
    assert built is None
    assert reason == "no_review"


def test_build_success_returns_text_with_promo_link(temp_db, script_mod):
    tid = _run(_make_teacher())
    rid = _run(_make_review(teacher_id=tid))
    built, reason = _run(script_mod._build_new_text_and_kb("ChiYanBookBot", rid))
    assert reason is None
    assert built is not None
    chat_id, msg_id, text, kb = built
    assert chat_id == -1001234567890
    assert msg_id == 555
    assert "出击报销八折" in text
    assert '<a href="https://t.me/ChiYanDairy/553">' in text
    assert kb.inline_keyboard  # 有按钮


# ============================================================
# 3. edit_one_review 各分支
# ============================================================


def _mk_bot(*, side_effect=None, return_value=True):
    bot = MagicMock()
    bot.edit_message_text = AsyncMock(
        side_effect=side_effect, return_value=return_value,
    )
    return bot


def test_edit_dry_run_does_not_call_telegram(temp_db, script_mod):
    import logging
    tid = _run(_make_teacher())
    rid = _run(_make_review(teacher_id=tid))
    bot = _mk_bot()
    res = _run(script_mod.edit_one_review(
        bot, rid, "Bot",
        dry_run=True, logger=logging.getLogger("test"),
    ))
    assert res == "ok"
    bot.edit_message_text.assert_not_awaited()


def test_edit_execute_calls_edit_with_html(temp_db, script_mod):
    import logging
    tid = _run(_make_teacher())
    rid = _run(_make_review(teacher_id=tid))
    bot = _mk_bot()
    res = _run(script_mod.edit_one_review(
        bot, rid, "ChiYanBookBot",
        dry_run=False, logger=logging.getLogger("test"),
    ))
    assert res == "ok"
    bot.edit_message_text.assert_awaited_once()
    kw = bot.edit_message_text.await_args.kwargs
    assert kw["chat_id"] == -1001234567890
    assert kw["message_id"] == 555
    assert "HTML" in str(kw["parse_mode"]).upper()
    assert kw["disable_web_page_preview"] is True
    assert "出击报销八折" in kw["text"]


def test_edit_returns_noop_when_message_not_modified(temp_db, script_mod):
    import logging
    from aiogram.exceptions import TelegramBadRequest
    tid = _run(_make_teacher())
    rid = _run(_make_review(teacher_id=tid))
    err = TelegramBadRequest(
        method=MagicMock(),
        message="Bad Request: message is not modified: ...",
    )
    bot = _mk_bot(side_effect=err)
    res = _run(script_mod.edit_one_review(
        bot, rid, "Bot",
        dry_run=False, logger=logging.getLogger("test"),
    ))
    assert res == "noop"


def test_edit_returns_fail_msg_not_found(temp_db, script_mod):
    import logging
    from aiogram.exceptions import TelegramBadRequest
    tid = _run(_make_teacher())
    rid = _run(_make_review(teacher_id=tid))
    err = TelegramBadRequest(
        method=MagicMock(),
        message="Bad Request: message to edit not found",
    )
    bot = _mk_bot(side_effect=err)
    res = _run(script_mod.edit_one_review(
        bot, rid, "Bot",
        dry_run=False, logger=logging.getLogger("test"),
    ))
    assert res == "fail:msg_not_found"


def test_edit_returns_fail_forbidden(temp_db, script_mod):
    import logging
    from aiogram.exceptions import TelegramForbiddenError
    tid = _run(_make_teacher())
    rid = _run(_make_review(teacher_id=tid))
    err = TelegramForbiddenError(
        method=MagicMock(), message="Forbidden: bot was kicked",
    )
    bot = _mk_bot(side_effect=err)
    res = _run(script_mod.edit_one_review(
        bot, rid, "Bot",
        dry_run=False, logger=logging.getLogger("test"),
    ))
    assert res == "fail:forbidden"


def test_edit_retry_after_raises_up(temp_db, script_mod):
    """RetryAfter 应被抛回主循环处理（不在 edit_one_review 里默默吞）。"""
    import logging
    from aiogram.exceptions import TelegramRetryAfter
    tid = _run(_make_teacher())
    rid = _run(_make_review(teacher_id=tid))
    err = TelegramRetryAfter(
        method=MagicMock(), message="Too Many Requests: retry after 5", retry_after=5,
    )
    bot = _mk_bot(side_effect=err)
    with pytest.raises(TelegramRetryAfter):
        _run(script_mod.edit_one_review(
            bot, rid, "Bot",
            dry_run=False, logger=logging.getLogger("test"),
        ))


def test_edit_skip_when_no_msg_ref(temp_db, script_mod):
    """评价行的 discussion_msg_id 为空 → skip:no_msg_ref。"""
    import logging
    tid = _run(_make_teacher())
    rid = _run(_make_review(teacher_id=tid, discussion_msg_id=None))
    bot = _mk_bot()
    res = _run(script_mod.edit_one_review(
        bot, rid, "Bot",
        dry_run=False, logger=logging.getLogger("test"),
    ))
    assert res == "skip:no_msg_ref"
    bot.edit_message_text.assert_not_awaited()


# ============================================================
# 4. CLI 参数解析
# ============================================================


def test_args_default_is_dry_run(script_mod, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["sync"])
    args = script_mod._parse_args()
    assert args.execute is False
    assert args.limit == 0
    assert args.throttle_ms == 1500


def test_args_execute_flag(script_mod, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["sync", "--execute"])
    args = script_mod._parse_args()
    assert args.execute is True


def test_args_limit_and_throttle(script_mod, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["sync", "--execute", "--limit", "50", "--throttle-ms", "2000"],
    )
    args = script_mod._parse_args()
    assert args.execute is True
    assert args.limit == 50
    assert args.throttle_ms == 2000
