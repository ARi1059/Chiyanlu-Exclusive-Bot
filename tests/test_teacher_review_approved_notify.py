"""评价审核通过后将评价 + 按钮推送给老师私聊（2026-05 新增）契约测试。

测试范围：
    1. notify_teacher_review_approved 函数存在
    2. 函数源码复用 render_review_comment（保证文本 / 按钮与讨论群一致）
    3. 函数源码读 footer config（与 publish_review_comment 同口径）
    4. rreview_admin._handle_approve 中插入了调用点
    5. 失败容错（review 不存在 / teacher 不存在 / get_me 失败 / send_message
       Forbidden）→ 返回 False，不抛异常，不阻塞 caller
    6. happy path：bot.send_message 调用包含 chat_id=teacher_id +
       reply_markup + parse_mode=HTML + disable_web_page_preview=True
    7. 文本与讨论群完全一致（promo footer + 留名半匿名 + 8 项评分）
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest


def _run(coro):
    return asyncio.run(coro)


def _fake_review(**overrides):
    base = {
        "id": 42, "user_id": 12345678, "teacher_id": 99,
        "rating": "positive", "anonymous": 0,
        "score_humanphoto": 9.0, "score_appearance": 8.5,
        "score_body": 8.0, "score_service": 9.5,
        "score_attitude": 9.0, "score_environment": 8.0,
        "overall_score": 8.67, "summary": "很不错",
    }
    base.update(overrides)
    return base


def _fake_teacher(**overrides):
    base = {
        "user_id": 99, "display_name": "林老师",
        "button_url": "https://t.me/example",
    }
    base.update(overrides)
    return base


# ============================================================
# 1. 函数存在 + 源码静态契约
# ============================================================


def test_notify_teacher_review_approved_function_exists():
    from bot.utils.rreview_notify import notify_teacher_review_approved
    assert callable(notify_teacher_review_approved)


def test_function_reuses_render_review_comment():
    """复用 render_review_comment 保证与讨论群版本完全一致。"""
    import bot.utils.rreview_notify as mod
    src = inspect.getsource(mod)
    idx = src.find("async def notify_teacher_review_approved(")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "render_review_comment" in body


def test_function_reads_promo_config():
    """复用 publish_review_comment 同口径：读 footer config 后注入 render。"""
    import bot.utils.rreview_notify as mod
    src = inspect.getsource(mod)
    idx = src.find("async def notify_teacher_review_approved(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "get_reimburse_promo_text" in body
    assert "get_reimburse_promo_url" in body


def test_function_uses_html_parse_mode():
    """必须以 HTML 解析（与 render_review_comment 输出格式匹配）。"""
    import bot.utils.rreview_notify as mod
    src = inspect.getsource(mod)
    idx = src.find("async def notify_teacher_review_approved(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "HTML" in body
    assert "disable_web_page_preview=True" in body


# ============================================================
# 2. rreview_admin 调用点
# ============================================================


def test_rreview_admin_calls_notify_teacher():
    """审核通过流程中必须有 notify_teacher_review_approved 调用（在 try 块内容错）。

    审核业务核心已抽到 bot.services.review_moderation（handler 委托调用）。
    """
    import bot.services.review_moderation as mod
    src = inspect.getsource(mod)
    assert "notify_teacher_review_approved" in src
    # 在 try 块内（失败容错）
    idx = src.find("notify_teacher_review_approved")
    # 向上找最近的 try:
    try_idx = src.rfind("try:", 0, idx)
    assert try_idx > 0
    # try 与调用之间不超过 5 行（防御性，确保是包裹在 try 内）
    between = src[try_idx:idx]
    assert between.count("\n") < 8


# ============================================================
# 3. 失败容错
# ============================================================


def _patch_dependencies(monkeypatch, *,
                        review=None, teacher=None,
                        promo_text="出击报销八折",
                        promo_url="https://t.me/ChiYanDairy/553"):
    """通用 mock：review / teacher / promo config。"""
    import bot.utils.rreview_notify as mod

    async def _get_review(rid):
        return review

    async def _get_teacher(tid):
        return teacher

    monkeypatch.setattr(mod, "get_teacher_review", _get_review)
    monkeypatch.setattr(mod, "get_teacher", _get_teacher)

    # promo config 在 review_comment 模块内（被 notify_teacher_review_approved
    # 在函数体内动态 import 后调用）。同时 patch render_review_comment 用的
    # caller 路径：notify 函数体内 `from bot.database import ...`，故 patch
    # bot.database 上的 helper
    async def _get_promo_text():
        return promo_text
    async def _get_promo_url():
        return promo_url
    monkeypatch.setattr(
        "bot.database.get_reimburse_promo_text", _get_promo_text,
    )
    monkeypatch.setattr(
        "bot.database.get_reimburse_promo_url", _get_promo_url,
    )


def test_no_review_returns_false(monkeypatch):
    from bot.utils.rreview_notify import notify_teacher_review_approved
    _patch_dependencies(monkeypatch, review=None)
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="ChiYanBookBot"))
    bot.send_message = AsyncMock()

    result = _run(notify_teacher_review_approved(bot, 9999))
    assert result is False
    bot.send_message.assert_not_awaited()


def test_no_teacher_returns_false(monkeypatch):
    from bot.utils.rreview_notify import notify_teacher_review_approved
    _patch_dependencies(monkeypatch, review=_fake_review(teacher_id=99), teacher=None)
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="ChiYanBookBot"))
    bot.send_message = AsyncMock()

    result = _run(notify_teacher_review_approved(bot, 42))
    assert result is False
    bot.send_message.assert_not_awaited()


def test_send_message_forbidden_returns_false(monkeypatch):
    """老师屏蔽 bot → _safe_send_text 吞异常返回 False。"""
    from aiogram.exceptions import TelegramForbiddenError
    from bot.utils.rreview_notify import notify_teacher_review_approved
    _patch_dependencies(
        monkeypatch,
        review=_fake_review(),
        teacher=_fake_teacher(),
    )
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="ChiYanBookBot"))
    bot.send_message = AsyncMock(side_effect=TelegramForbiddenError(
        method=MagicMock(), message="bot was blocked by the user",
    ))

    result = _run(notify_teacher_review_approved(bot, 42))
    assert result is False


# ============================================================
# 4. Happy path：完整推送给老师
# ============================================================


def test_happy_path_sends_to_teacher_with_html_kb(monkeypatch):
    """成功路径：消息发到 teacher_id + 含 reply_markup + parse_mode HTML。"""
    from bot.utils.rreview_notify import notify_teacher_review_approved
    _patch_dependencies(
        monkeypatch,
        review=_fake_review(teacher_id=99),
        teacher=_fake_teacher(user_id=99),
    )
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="ChiYanBookBot"))
    bot.send_message = AsyncMock(return_value=MagicMock())

    result = _run(notify_teacher_review_approved(bot, 42))
    assert result is True
    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs

    # 发到老师 chat
    assert kwargs.get("chat_id") == 99
    # 含按钮（reply_markup 非空）
    assert kwargs.get("reply_markup") is not None
    # parse_mode HTML
    assert "HTML" in str(kwargs.get("parse_mode") or "").upper()
    # disable web preview
    assert kwargs.get("disable_web_page_preview") is True


def test_text_matches_discussion_format(monkeypatch):
    """老师收到的文本应与讨论群版本格式完全一致（关键设计点：复用 render）。"""
    from bot.utils.rreview_notify import notify_teacher_review_approved
    _patch_dependencies(
        monkeypatch,
        review=_fake_review(),
        teacher=_fake_teacher(),
    )
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="ChiYanBookBot"))
    bot.send_message = AsyncMock(return_value=MagicMock())

    _run(notify_teacher_review_approved(bot, 42))
    text = bot.send_message.await_args.kwargs["text"]

    # 8 项评分行
    assert "【老师】：林老师" in text
    assert "【留名】：" in text  # 半匿名
    assert "【人照】：9" in text
    assert "【综合】：8.67" in text
    assert "【过程】：很不错" in text
    # Powered by
    assert "Powered by @ChiYanBookBot" in text
    # footer（默认 promo 已注入）
    assert "出击报销八折" in text


def test_keyboard_has_three_rows_same_as_discussion(monkeypatch):
    """老师收到的 keyboard 与讨论群一致：3 行（联系 / 评级徽章 / 写报告 deep link）。"""
    from bot.utils.rreview_notify import notify_teacher_review_approved
    _patch_dependencies(
        monkeypatch,
        review=_fake_review(teacher_id=99),
        teacher=_fake_teacher(user_id=99),
    )
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="ChiYanBookBot"))
    bot.send_message = AsyncMock(return_value=MagicMock())

    _run(notify_teacher_review_approved(bot, 42))
    kb = bot.send_message.await_args.kwargs["reply_markup"]
    rows = kb.inline_keyboard
    assert len(rows) == 3
    # 1 联系 URL
    assert rows[0][0].url == "https://t.me/example"
    # 2 评级徽章 noop
    assert rows[1][0].callback_data == "noop:rating"
    # 3 写报告 deep link （t.me/{bot}?startapp=write_{teacher_id} 直达 MiniApp）
    assert "?startapp=write_99" in (rows[2][0].url or "")


def test_footer_skipped_when_promo_text_empty(monkeypatch):
    """promo_text 配置为空时不渲染 footer（与 publish 同语义）。"""
    from bot.utils.rreview_notify import notify_teacher_review_approved
    _patch_dependencies(
        monkeypatch,
        review=_fake_review(),
        teacher=_fake_teacher(),
        promo_text="",
        promo_url="https://t.me/test",
    )
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="ChiYanBookBot"))
    bot.send_message = AsyncMock(return_value=MagicMock())

    _run(notify_teacher_review_approved(bot, 42))
    text = bot.send_message.await_args.kwargs["text"]
    assert "<a href=" not in text
    assert "Powered by" in text  # Powered by 仍渲染
