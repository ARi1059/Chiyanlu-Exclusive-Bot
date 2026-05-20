"""Sprint UX-4 第五项（UX-4.5）：抽奖参与成功通知 + CTA 按钮契约测试。

范围：
    - bot.utils.lottery_publish.build_lottery_channel_url 频道帖 URL 构造
    - bot.handlers.lottery_entry._build_lottery_entry_ok_kb keyboard 构造
    - bot.handlers.lottery_entry._render_entry_result ok 分支接入 keyboard

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §1 C1 + §3.2 痛点 11 + §11.3）：
    抽奖参与成功私聊回执是一次性消息无后续 action，本批附 CTA：

        - [🎁 抽奖详情]    url=t.me/c/<x>/<msg_id>   仅当 channel_chat_id+msg_id 存在
        - [🏠 返回主菜单]  callback=user:main         兜底

约束：
    - "我的抽奖" 按钮等 UX-6.1 落地后再加（本批不放避免死按钮）
    - 不改 callback_data；user:main 早已存在
    - 不改 try_enter_lottery 业务逻辑（扣分 / 关注校验 / audit 顺序）
    - 不改非 ok 分支（need_subscribe / need_points / time_window / already_entered）
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


# ============================================================
# 1. build_lottery_channel_url 单元测试
# ============================================================


def test_build_url_with_supergroup_chat_id():
    """私有频道（chat_id 以 -100 开头）→ t.me/c/<trimmed>/<msg_id>。"""
    from bot.utils.lottery_publish import build_lottery_channel_url
    url = build_lottery_channel_url(-1001234567890, 42)
    assert url == "https://t.me/c/1234567890/42"


def test_build_url_returns_none_when_chat_id_missing():
    from bot.utils.lottery_publish import build_lottery_channel_url
    assert build_lottery_channel_url(None, 42) is None
    assert build_lottery_channel_url(0, 42) is None


def test_build_url_returns_none_when_msg_id_missing():
    from bot.utils.lottery_publish import build_lottery_channel_url
    assert build_lottery_channel_url(-1001234567890, None) is None
    assert build_lottery_channel_url(-1001234567890, 0) is None


def test_build_url_returns_none_for_non_supergroup_chat_id():
    """非 -100 开头的 chat_id（公开频道需 username，本批不支持） → None。"""
    from bot.utils.lottery_publish import build_lottery_channel_url
    assert build_lottery_channel_url(12345, 42) is None
    assert build_lottery_channel_url(-12345, 42) is None
    assert build_lottery_channel_url(-200999, 42) is None


def test_build_url_handles_string_msg_id_safely():
    """msg_id 接受 int-like 输入（DB 行有时返回 str / int 不一）。"""
    from bot.utils.lottery_publish import build_lottery_channel_url
    url = build_lottery_channel_url(-1001234567890, "42")
    assert url == "https://t.me/c/1234567890/42"


# ============================================================
# 2. _build_lottery_entry_ok_kb keyboard 契约
# ============================================================


def test_kb_with_channel_link_has_both_buttons():
    from bot.handlers.lottery_entry import _build_lottery_entry_ok_kb
    lottery = {
        "id": 7,
        "name": "周末活动",
        "channel_chat_id": -1001234567890,
        "channel_msg_id": 99,
    }
    kb = _build_lottery_entry_ok_kb(lottery)
    btns = _flat_buttons(kb)
    assert len(btns) == 2
    # 第一个按钮：URL
    assert btns[0].url == "https://t.me/c/1234567890/99"
    assert "抽奖详情" in btns[0].text
    # 第二个按钮：主菜单 callback
    assert btns[1].callback_data == "user:main"
    assert btns[1].url is None


def test_kb_without_channel_link_has_only_main_button():
    """未发布到频道（channel_chat_id/msg_id 缺失）→ 仅 [🏠 主菜单] 一个按钮，
    不引入死链。"""
    from bot.handlers.lottery_entry import _build_lottery_entry_ok_kb
    lottery = {"id": 7, "name": "x"}
    kb = _build_lottery_entry_ok_kb(lottery)
    btns = _flat_buttons(kb)
    assert len(btns) == 1
    assert btns[0].callback_data == "user:main"


def test_kb_handles_zero_msg_id_as_unpublished():
    from bot.handlers.lottery_entry import _build_lottery_entry_ok_kb
    lottery = {"channel_chat_id": -1001234567890, "channel_msg_id": 0}
    kb = _build_lottery_entry_ok_kb(lottery)
    btns = _flat_buttons(kb)
    assert len(btns) == 1
    assert btns[0].callback_data == "user:main"


def test_kb_does_not_include_my_lottery_placeholder():
    """UX-4.5 不应加"我的抽奖"占位按钮（依赖 UX-6.1 未落地）。"""
    from bot.handlers.lottery_entry import _build_lottery_entry_ok_kb
    lottery = {
        "channel_chat_id": -1001234567890, "channel_msg_id": 99,
    }
    kb = _build_lottery_entry_ok_kb(lottery)
    cbs = [b.callback_data for b in _flat_buttons(kb) if b.callback_data]
    # 不应有 user:lottery / user:my_lottery 之类的尚未实现的 callback
    for cb in cbs:
        assert cb in {"user:main"}, f"未预期的 callback: {cb}"


# ============================================================
# 3. _render_entry_result ok 分支行为
# ============================================================


def test_render_ok_branch_attaches_keyboard():
    """ok 分支：send_message 调用应含 reply_markup。"""
    from bot.handlers.lottery_entry import _render_entry_result
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    lottery = {
        "id": 7, "name": "活动",
        "draw_at": "2026-05-21 10:00",
        "channel_chat_id": -1001234567890, "channel_msg_id": 99,
    }
    extra = {"entry_id": 100, "lottery_id": 7, "cost_deducted": 5}
    _run(_render_entry_result(
        bot, user_id=1001, chat_id=1001,
        lottery=lottery, status="ok", extra=extra,
    ))
    bot.send_message.assert_awaited_once()
    call = bot.send_message.await_args
    kb = call.kwargs.get("reply_markup")
    assert kb is not None
    btns = _flat_buttons(kb)
    assert any(b.url == "https://t.me/c/1234567890/99" for b in btns)
    assert any(b.callback_data == "user:main" for b in btns)


def test_render_ok_branch_text_still_contains_required():
    """UX-4.5 不应破坏既有 ok 文案（已参与 + 开奖时间）。"""
    from bot.handlers.lottery_entry import _render_entry_result
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    lottery = {
        "id": 7, "name": "活动",
        "draw_at": "2026-05-21 10:00",
    }
    extra = {"cost_deducted": 5}
    _run(_render_entry_result(
        bot, user_id=1001, chat_id=1001,
        lottery=lottery, status="ok", extra=extra,
    ))
    text = bot.send_message.await_args.kwargs["text"]
    assert "已参与" in text
    assert "活动" in text
    assert "2026-05-21 10:00" in text
    assert "5 积分" in text  # cost > 0 时 cost_line 应展示


def test_render_ok_branch_no_cost_line_when_free():
    """免费抽奖（cost_deducted=0）不应展示 "已扣除" 行。"""
    from bot.handlers.lottery_entry import _render_entry_result
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    lottery = {"id": 7, "name": "免费", "draw_at": "2026-05-21 10:00"}
    extra = {"cost_deducted": 0}
    _run(_render_entry_result(
        bot, user_id=1001, chat_id=1001,
        lottery=lottery, status="ok", extra=extra,
    ))
    text = bot.send_message.await_args.kwargs["text"]
    assert "已扣除" not in text


# ============================================================
# 4. 非 ok 分支不应被 UX-4.5 影响
# ============================================================


def test_render_already_entered_branch_unchanged():
    """already_entered 分支文案 + 行为不变（本批仅改 ok 分支）。"""
    from bot.handlers.lottery_entry import _render_entry_result
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    lottery = {"id": 7, "name": "活动"}
    _run(_render_entry_result(
        bot, user_id=1001, chat_id=1001,
        lottery=lottery, status="already_entered", extra={},
    ))
    text = bot.send_message.await_args.kwargs["text"]
    assert "已参与" in text and "1 次" in text


def test_render_need_points_kb_unchanged():
    """need_points 分支 keyboard 仍为 [💰 查看我的积分] 单按钮（本批不动）。"""
    from bot.handlers.lottery_entry import _render_entry_result
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    lottery = {"id": 7, "name": "x"}
    _run(_render_entry_result(
        bot, user_id=1001, chat_id=1001,
        lottery=lottery, status="need_points",
        extra={"required": 10, "current": 3},
    ))
    kb = bot.send_message.await_args.kwargs.get("reply_markup")
    btns = _flat_buttons(kb)
    cbs = [b.callback_data for b in btns]
    assert "user:points" in cbs
    # 不应被 UX-4.5 误加 user:main
    assert "user:main" not in cbs


# ============================================================
# 5. 静态契约
# ============================================================


def test_lottery_entry_imports_build_url():
    import bot.handlers.lottery_entry as mod
    src = _src(mod)
    assert "build_lottery_channel_url" in src


def test_render_ok_uses_kb_helper():
    """render 函数 ok 分支应通过 _build_lottery_entry_ok_kb 取 keyboard。"""
    import bot.handlers.lottery_entry as mod
    src = _src(mod)
    idx = src.find("async def _render_entry_result(")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "_build_lottery_entry_ok_kb" in body


def test_user_main_callback_handler_still_registered():
    """user:main callback 必须仍有 handler 注册，避免本批引入死按钮。"""
    import bot.handlers.user_panel as mod
    src = _src(mod)
    assert 'F.data == "user:main"' in src


# ============================================================
# 6. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states"}
