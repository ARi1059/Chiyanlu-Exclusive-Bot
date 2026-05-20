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
    # 2026-05-20：tuple 形状改为 (teacher_id, chat_id, msg_id, text, kb)，
    # 多带出 teacher_id 供后续按老师聚合通知（DM 老师 footer 已批量更新）
    teacher_id, chat_id, msg_id, text, kb = built
    assert teacher_id == tid
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
    # 2026-05-20：默认开启老师 DM 通知（仅 --execute 下生效）
    assert args.notify is True
    assert args.notify_throttle_ms == 1500


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


def test_args_no_notify_flag(script_mod, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["sync", "--execute", "--no-notify"])
    args = script_mod._parse_args()
    assert args.execute is True
    assert args.notify is False


def test_args_notify_throttle_custom(script_mod, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["sync", "--execute", "--notify-throttle-ms", "3000"],
    )
    args = script_mod._parse_args()
    assert args.notify_throttle_ms == 3000


# ============================================================
# 5. 老师 DM 通知（2026-05-20 新增功能）
# ============================================================


def test_build_review_link_private_supergroup(script_mod):
    """-100 开头 chat_id → 构造 t.me/c/<rest>/<msg> 形式直链。"""
    link = script_mod._build_review_link(-1001234567890, 555)
    assert link == "https://t.me/c/1234567890/555"


def test_build_review_link_invalid_chat_id_returns_none(script_mod):
    """非 -100 开头 → 返回 None（讨论群理论上必带）。"""
    assert script_mod._build_review_link(123456, 555) is None
    assert script_mod._build_review_link(0, 555) is None


def test_build_teacher_notify_text_contains_count_and_links(script_mod):
    """聚合 DM 应含老师名 / 总数 / 评价直链 / footer 说明。"""
    items = [
        (101, -1001234567890, 111),
        (102, -1001234567890, 222),
    ]
    text = script_mod._build_teacher_notify_text("林老师", items)
    assert "林老师" in text
    assert "<b>2</b>" in text
    assert "https://t.me/c/1234567890/111" in text
    assert "https://t.me/c/1234567890/222" in text
    assert "评价 #101" in text
    assert "评价 #102" in text
    assert "出击报销八折" in text


def test_build_teacher_notify_text_collapses_when_over_20(script_mod):
    """>20 条评价 → 列前 20 + 「还有 N 条」折叠，避免单条 DM 超长。"""
    items = [(i, -1001234567890, i * 10) for i in range(1, 26)]  # 25 条
    text = script_mod._build_teacher_notify_text("林老师", items)
    assert "<b>25</b>" in text
    assert "评价 #20" in text  # 第 20 条还在
    assert "评价 #21" not in text  # 第 21 条已折叠
    assert "还有 5 条" in text


def test_build_teacher_notify_text_escapes_html_in_name(script_mod):
    """老师名含 HTML 关键字符 → 应被 escape，避免破坏外层 <b> 标签。"""
    text = script_mod._build_teacher_notify_text(
        "<script>x</script>", [(1, -1001234567890, 1)],
    )
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_send_teacher_notification_dry_run_skips(script_mod):
    """dry-run 仅校验长度，不调 bot.send_message。"""
    import logging
    bot = MagicMock()
    bot.send_message = AsyncMock()
    res = _run(script_mod._send_teacher_notification(
        bot, teacher_id=99, text="hello",
        dry_run=True, logger=logging.getLogger("test"),
    ))
    assert res == "ok"
    bot.send_message.assert_not_awaited()


def test_send_teacher_notification_execute_calls_send_message(script_mod):
    """execute 模式 → bot.send_message 被调，参数含 chat_id / parse_mode HTML。"""
    import logging
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=True)
    res = _run(script_mod._send_teacher_notification(
        bot, teacher_id=99, text="hi <b>name</b>",
        dry_run=False, logger=logging.getLogger("test"),
    ))
    assert res == "ok"
    bot.send_message.assert_awaited_once()
    kw = bot.send_message.await_args.kwargs
    assert kw["chat_id"] == 99
    assert "HTML" in str(kw["parse_mode"]).upper()
    assert kw["disable_web_page_preview"] is True


def test_send_teacher_notification_forbidden_returns_fail(script_mod):
    """老师未启动过 bot → ForbiddenError 仅记录 warning，返回 fail:forbidden。"""
    import logging
    from aiogram.exceptions import TelegramForbiddenError
    bot = MagicMock()
    bot.send_message = AsyncMock(
        side_effect=TelegramForbiddenError(
            method=MagicMock(), message="Forbidden: bot can't initiate conversation",
        ),
    )
    res = _run(script_mod._send_teacher_notification(
        bot, teacher_id=99, text="hi",
        dry_run=False, logger=logging.getLogger("test"),
    ))
    assert res == "fail:forbidden"


def test_notify_teachers_aggregated_groups_by_teacher(temp_db, script_mod):
    """两位老师 + 三条评价 → 调 bot.send_message 两次，每次一位老师。"""
    import logging
    t1 = _run(_make_teacher(user_id=101, display_name="张老师"))
    t2 = _run(_make_teacher(user_id=102, display_name="李老师"))
    edits = {
        t1: [(1, -1001234567890, 11), (2, -1001234567890, 22)],
        t2: [(3, -1001234567890, 33)],
    }
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=True)
    counts = _run(script_mod.notify_teachers_aggregated(
        bot, edits, dry_run=False, throttle_ms=0,
        logger=logging.getLogger("test"),
    ))
    assert counts == {"ok": 2}
    assert bot.send_message.await_count == 2
    chat_ids = [c.kwargs["chat_id"] for c in bot.send_message.await_args_list]
    assert sorted(chat_ids) == sorted([t1, t2])


def test_notify_teachers_aggregated_empty_returns_empty(script_mod):
    """无任何 edit → 跳过通知阶段，不调 bot。"""
    import logging
    bot = MagicMock()
    bot.send_message = AsyncMock()
    counts = _run(script_mod.notify_teachers_aggregated(
        bot, {}, dry_run=False, throttle_ms=0,
        logger=logging.getLogger("test"),
    ))
    assert counts == {}
    bot.send_message.assert_not_awaited()


def test_notify_teachers_aggregated_missing_teacher_skips(temp_db, script_mod):
    """teacher_id 对应记录已删 → skip:no_teacher 记数；不阻塞其他老师。"""
    import logging
    t1 = _run(_make_teacher(user_id=101, display_name="张老师"))
    edits = {
        t1: [(1, -1001234567890, 11)],
        9999: [(2, -1001234567890, 22)],  # 不存在的老师
    }
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=True)
    counts = _run(script_mod.notify_teachers_aggregated(
        bot, edits, dry_run=False, throttle_ms=0,
        logger=logging.getLogger("test"),
    ))
    assert counts.get("ok") == 1
    assert counts.get("skip:no_teacher") == 1
    # 仅给存在的老师发了 1 条
    assert bot.send_message.await_count == 1


def test_edit_one_review_calls_on_edited_on_success(temp_db, script_mod):
    """成功 edit → 触发 on_edited 回调，传递 (review_id, teacher_id, chat_id, msg_id)。"""
    import logging
    tid = _run(_make_teacher())
    rid = _run(_make_review(teacher_id=tid))
    bot = _mk_bot()
    captured = []
    res = _run(script_mod.edit_one_review(
        bot, rid, "Bot",
        dry_run=False, logger=logging.getLogger("test"),
        on_edited=lambda rev_id, t_id, c_id, m_id: captured.append((rev_id, t_id, c_id, m_id)),
    ))
    assert res == "ok"
    assert len(captured) == 1
    assert captured[0] == (rid, tid, -1001234567890, 555)


def test_edit_one_review_no_on_edited_on_noop(temp_db, script_mod):
    """noop（message is not modified）→ 不触发 on_edited，避免误推已是最新格式的评价。"""
    import logging
    from aiogram.exceptions import TelegramBadRequest
    tid = _run(_make_teacher())
    rid = _run(_make_review(teacher_id=tid))
    err = TelegramBadRequest(
        method=MagicMock(),
        message="Bad Request: message is not modified: ...",
    )
    bot = _mk_bot(side_effect=err)
    captured = []
    res = _run(script_mod.edit_one_review(
        bot, rid, "Bot",
        dry_run=False, logger=logging.getLogger("test"),
        on_edited=lambda *a: captured.append(a),
    ))
    assert res == "noop"
    assert captured == []


def test_edit_one_review_no_on_edited_on_dry_run(temp_db, script_mod):
    """dry-run → 即便结果是 ok 也不触发 on_edited（dry-run 不真改）。"""
    import logging
    tid = _run(_make_teacher())
    rid = _run(_make_review(teacher_id=tid))
    bot = _mk_bot()
    captured = []
    res = _run(script_mod.edit_one_review(
        bot, rid, "Bot",
        dry_run=True, logger=logging.getLogger("test"),
        on_edited=lambda *a: captured.append(a),
    ))
    assert res == "ok"
    assert captured == []
