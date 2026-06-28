"""「今日开课」关键词专属渲染测试（实时老师超链接列表 + 打开小程序按钮）。

覆盖：
  - _is_today_entry：按 deep-link target=="today" 判定（不依赖 trigger 文本）
  - _send_today_open_teachers：有老师→超链接列表(含 <a href)+末页带 startapp=today 按钮；
    空→「暂无老师开课」+按钮；多页→按钮仅末页
  - render_group_search_result_pages(header=...) 自定义页头 / 默认页头

DB 叶子函数 monkeypatch（get_checked_in_teachers / _enrich_with_today_status）。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import bot.handlers.keyword as kw
from bot.utils.group_search import render_group_search_result_pages


def _run(coro):
    return asyncio.run(coro)


def _fake_teacher(uid: int, name: str) -> dict:
    return {
        "user_id": uid,
        "display_name": name,
        "region": "心岛",
        "price": "1000P",
        "button_url": f"https://example.com/{uid}",
    }


def _patch_today(monkeypatch, teachers):
    async def fake_checked(today):
        return list(teachers)

    async def fake_enrich(ts, today):
        for t in ts:
            t["signed_in_today"] = 1
            t["daily_status"] = None
            t["fav_count"] = 0
        return ts

    monkeypatch.setattr(kw, "get_checked_in_teachers", fake_checked)
    monkeypatch.setattr(kw, "_enrich_with_today_status", fake_enrich)


def _reply_text(call) -> str:
    return call.args[0] if call.args else call.kwargs.get("text", "")


# ============ _is_today_entry ============

def test_is_today_entry_by_target():
    assert kw._is_today_entry({"buttons": [["打开今日开课", "today"]]}) is True
    assert kw._is_today_entry({"buttons": [["x", "filter"], ["y", "today"]]}) is True
    assert kw._is_today_entry({"buttons": [["按条件筛选", "filter"]]}) is False
    assert kw._is_today_entry({"buttons": []}) is False
    assert kw._is_today_entry(None) is False


# ============ _send_today_open_teachers ============

def test_today_renders_hyperlink_list_with_miniapp_button(monkeypatch):
    _patch_today(monkeypatch, [_fake_teacher(1, "甲"), _fake_teacher(2, "乙")])
    msg = MagicMock()
    msg.reply = AsyncMock()

    ok = _run(kw._send_today_open_teachers(msg, "fakebot"))
    assert ok is True
    assert msg.reply.call_count == 1  # 2 位 → 单页

    call = msg.reply.call_args
    text = _reply_text(call)
    assert "今日开课" in text
    assert "<a href=" in text          # 超链接规则
    assert "甲" in text and "乙" in text
    # 末页（=唯一页）带打开小程序按钮，深链 startapp=today
    kb = call.kwargs["reply_markup"]
    assert "startapp=today" in kb.inline_keyboard[0][0].url
    # HTML 发送 + 禁预览
    assert call.kwargs.get("disable_web_page_preview") is True


def test_today_empty_state(monkeypatch):
    _patch_today(monkeypatch, [])
    msg = MagicMock()
    msg.reply = AsyncMock()

    ok = _run(kw._send_today_open_teachers(msg, "fakebot"))
    assert ok is True
    assert msg.reply.call_count == 1
    text = _reply_text(msg.reply.call_args)
    assert "暂无老师开课" in text
    kb = msg.reply.call_args.kwargs["reply_markup"]
    assert "startapp=today" in kb.inline_keyboard[0][0].url


def test_today_paginated_button_only_on_last_page(monkeypatch):
    _patch_today(monkeypatch, [_fake_teacher(i, f"老师{i}") for i in range(30)])
    msg = MagicMock()
    msg.reply = AsyncMock()

    ok = _run(kw._send_today_open_teachers(msg, "fakebot"))
    assert ok is True
    assert msg.reply.call_count == 2  # 30 → 25 + 5 → 2 页

    first_kb = msg.reply.call_args_list[0].kwargs["reply_markup"]
    last_kb = msg.reply.call_args_list[1].kwargs["reply_markup"]
    assert first_kb is None            # 第一页不附按钮
    assert last_kb is not None and "startapp=today" in last_kb.inline_keyboard[0][0].url


# ============ render_group_search_result_pages header ============

def test_custom_header_used():
    teachers = [_fake_teacher(1, "甲")]
    pages = render_group_search_result_pages(
        teachers, total_count=1, header="📚 今日开课（1 位老师）",
    )
    assert pages[0].splitlines()[0] == "📚 今日开课（1 位老师）"


def test_default_header_preserved():
    teachers = [_fake_teacher(1, "甲")]
    pages = render_group_search_result_pages(teachers, total_count=1)
    assert "找到 1 位相关老师" in pages[0].splitlines()[0]


def test_custom_header_paginated_appends_page_no():
    teachers = [_fake_teacher(i, f"T{i}") for i in range(30)]
    pages = render_group_search_result_pages(
        teachers, total_count=30, per_page=25, header="📚 今日开课（30 位老师）",
    )
    assert len(pages) == 2
    assert "📚 今日开课（30 位老师）（第 1/2 页）" == pages[0].splitlines()[0]
    assert "📚 今日开课（30 位老师）（第 2/2 页）" == pages[1].splitlines()[0]
