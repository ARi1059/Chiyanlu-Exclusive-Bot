"""讨论群评价文案的「报销八折」超链接 footer 契约测试（2026-05-20）。

范围：
    - bot.utils.review_comment.render_review_comment：
      - footer 含既有 "✳ Powered by @{bot_username}" 行
      - footer 末尾追加 <a href="https://t.me/ChiYanDairy/553">出击报销八折</a>
      - display_name / summary 经 html.escape 防注入
    - bot.utils.review_comment.publish_review_comment：
      - 两条 send_message 路径（reply 成功 / 锚丢失 fallback）
        均传 parse_mode=ParseMode.HTML + disable_web_page_preview=True

约束：
    - 不改 callback_data；不改按钮结构
    - 不引入 schema 迁移
"""
from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock

import pytest


def _run(coro):
    return asyncio.run(coro)


def _fake_review(**overrides):
    base = {
        "id": 42,
        "user_id": 12345678,
        "teacher_id": 99,
        "rating": "positive",
        "anonymous": 0,
        "score_humanphoto": 9.0,
        "score_appearance": 8.5,
        "score_body": 8.0,
        "score_service": 9.5,
        "score_attitude": 9.0,
        "score_environment": 8.0,
        "overall_score": 8.67,
        "summary": "很不错",
    }
    base.update(overrides)
    return base


def _fake_teacher(**overrides):
    base = {
        "user_id": 99,
        "display_name": "林老师",
        "button_url": "https://t.me/example",
    }
    base.update(overrides)
    return base


# ============================================================
# 1. footer 内容
# ============================================================


def test_footer_keeps_powered_by_line():
    from bot.utils.review_comment import render_review_comment
    text, _ = render_review_comment(
        _fake_review(), _fake_teacher(), bot_username="ChiYanBookBot",
    )
    assert "✳ Powered by @ChiYanBookBot" in text


def test_footer_appends_promo_hyperlink():
    """footer 末尾应有 HTML <a> 形式的"出击报销八折"超链接。"""
    from bot.utils.review_comment import (
        render_review_comment,
        REIMBURSE_PROMO_TEXT,
        REIMBURSE_PROMO_URL,
    )
    text, _ = render_review_comment(
        _fake_review(), _fake_teacher(), bot_username="ChiYanBookBot",
    )
    assert REIMBURSE_PROMO_TEXT == "出击报销八折"
    assert REIMBURSE_PROMO_URL == "https://t.me/ChiYanDairy/553"
    assert (
        f'<a href="{REIMBURSE_PROMO_URL}">{REIMBURSE_PROMO_TEXT}</a>' in text
    )


def test_promo_line_appears_after_powered_by():
    """渲染顺序：评价主体 → "Powered by" → "出击报销八折" 超链接。"""
    from bot.utils.review_comment import render_review_comment
    text, _ = render_review_comment(
        _fake_review(), _fake_teacher(), bot_username="ChiYanBookBot",
    )
    pos_powered = text.find("Powered by")
    pos_promo = text.find("出击报销八折")
    assert pos_powered > 0
    assert pos_promo > pos_powered


def test_blank_line_separates_powered_by_from_promo():
    """符合视觉规范：Powered by 与 promo 之间留 1 空行。"""
    from bot.utils.review_comment import render_review_comment
    text, _ = render_review_comment(
        _fake_review(), _fake_teacher(), bot_username="ChiYanBookBot",
    )
    # 找到 "Powered by" 行，下一行应为空，再下一行才是 promo
    lines = text.split("\n")
    idx_powered = next(
        i for i, line in enumerate(lines) if "Powered by" in line
    )
    assert lines[idx_powered + 1] == ""
    assert "出击报销八折" in lines[idx_powered + 2]


# ============================================================
# 2. HTML 注入防护
# ============================================================


def test_display_name_is_html_escaped():
    """display_name 含 < / > / & 时必须被 escape，否则 parse_mode=HTML 会破坏渲染。"""
    from bot.utils.review_comment import render_review_comment
    text, _ = render_review_comment(
        _fake_review(),
        _fake_teacher(display_name="<script>恶意</script> & 林老师"),
        bot_username="ChiYanBookBot",
    )
    # 原始 < > & 应被 escape；不会留在 text 里以原貌出现
    assert "<script>" not in text
    assert "&lt;script&gt;" in text or "&lt;script" in text
    assert "&amp;" in text


def test_summary_is_html_escaped():
    """summary 同样为用户输入，必须 escape。"""
    from bot.utils.review_comment import render_review_comment
    text, _ = render_review_comment(
        _fake_review(summary="<b>诱导</b>评分 & 跳转"),
        _fake_teacher(),
        bot_username="ChiYanBookBot",
    )
    assert "<b>诱导</b>" not in text
    assert "&lt;b&gt;" in text


def test_promo_anchor_not_escaped_in_text():
    """promo 行本身是合法 HTML <a>，不应被错误地 escape。"""
    from bot.utils.review_comment import render_review_comment
    text, _ = render_review_comment(
        _fake_review(), _fake_teacher(), bot_username="ChiYanBookBot",
    )
    # 我们生成的 <a href="..."> 应原样出现，不是 &lt;a&gt;
    assert '<a href="https://t.me/ChiYanDairy/553">' in text
    assert "&lt;a href" not in text


# ============================================================
# 3. 按钮结构未变
# ============================================================


def test_keyboard_buttons_unchanged():
    """按钮 3 行结构：联系 / 评级 / 写报告；2026-05 footer 改动不影响。"""
    from bot.utils.review_comment import render_review_comment
    _, kb = render_review_comment(
        _fake_review(), _fake_teacher(), bot_username="ChiYanBookBot",
    )
    rows = kb.inline_keyboard
    assert len(rows) == 3
    # 第一行：URL 按钮（联系）
    assert rows[0][0].url == "https://t.me/example"
    # 第二行：noop:rating
    assert rows[1][0].callback_data == "noop:rating"
    # 第三行：写报告 deep link
    assert "?start=write_99" in (rows[2][0].url or "")


# ============================================================
# 4. publish_review_comment 端到端：parse_mode HTML 传递
# ============================================================


def _patch_publish_dependencies(monkeypatch, *, anchor_present=True):
    """让 publish_review_comment 走 happy path：DB 查询 + bot.get_me 都 mock 掉。"""
    from bot.utils import review_comment as mod

    async def _get_review(rid):
        return _fake_review(id=rid)

    async def _get_teacher(tid):
        return _fake_teacher(user_id=tid)

    async def _get_post(tid):
        if not anchor_present:
            return None
        return {
            "discussion_chat_id": -1001234567890,
            "discussion_anchor_id": 555,
        }

    async def _noop_update(*args, **kwargs):
        return None

    monkeypatch.setattr(mod, "get_teacher_review", _get_review)
    monkeypatch.setattr(mod, "get_teacher", _get_teacher)
    monkeypatch.setattr(mod, "get_teacher_channel_post", _get_post)
    monkeypatch.setattr(mod, "update_review_discussion_msg", _noop_update)


def test_publish_sends_with_html_parse_mode(monkeypatch):
    from bot.utils.review_comment import publish_review_comment
    _patch_publish_dependencies(monkeypatch)
    bot = MagicMock()
    me = MagicMock()
    me.username = "ChiYanBookBot"
    bot.get_me = AsyncMock(return_value=me)
    sent = MagicMock()
    sent.chat = MagicMock(); sent.chat.id = -1001234567890
    sent.message_id = 888
    bot.send_message = AsyncMock(return_value=sent)

    res = _run(publish_review_comment(bot, 42))
    bot.send_message.assert_awaited()
    call_kwargs = bot.send_message.await_args.kwargs
    # parse_mode 必须显式传 HTML（不能依赖 bot 默认）
    assert call_kwargs.get("parse_mode") is not None
    # 字符串或枚举都可
    assert "HTML" in str(call_kwargs["parse_mode"]).upper()
    # 防止预览图盖掉文案
    assert call_kwargs.get("disable_web_page_preview") is True
    # 文本含 promo 超链接
    assert "出击报销八折" in call_kwargs["text"]
    assert '<a href="https://t.me/ChiYanDairy/553">' in call_kwargs["text"]


def test_publish_anchor_lost_fallback_also_uses_html(monkeypatch):
    """锚丢失 fallback 路径同样要带 parse_mode=HTML。"""
    from aiogram.exceptions import TelegramBadRequest
    from bot.utils.review_comment import publish_review_comment
    _patch_publish_dependencies(monkeypatch)
    bot = MagicMock()
    me = MagicMock()
    me.username = "ChiYanBookBot"
    bot.get_me = AsyncMock(return_value=me)
    sent_ok = MagicMock()
    sent_ok.chat = MagicMock(); sent_ok.chat.id = -1001234567890
    sent_ok.message_id = 999

    # 第一次 raise reply not found；第二次成功
    call_log: list[dict] = []

    async def _send_message(**kwargs):
        call_log.append(kwargs)
        if len(call_log) == 1:
            raise TelegramBadRequest(
                method=MagicMock(),
                message="Bad Request: reply message not found",
            )
        return sent_ok
    bot.send_message = AsyncMock(side_effect=_send_message)

    # 关掉 anchor_lost notify 防止真请求
    from bot.utils import review_comment as mod
    async def _fake_notify(*a, **kw): return None
    monkeypatch.setattr(
        "bot.utils.rreview_notify.notify_super_admins_anchor_lost",
        _fake_notify, raising=False,
    )

    res = _run(publish_review_comment(bot, 42))
    assert res["fallback"] is True
    assert len(call_log) == 2
    # 两次调用都应带 parse_mode HTML
    for kw in call_log:
        assert "HTML" in str(kw.get("parse_mode")).upper()
        assert kw.get("disable_web_page_preview") is True
