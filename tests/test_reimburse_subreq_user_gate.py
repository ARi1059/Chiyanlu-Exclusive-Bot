"""报销专用必关 - 用户报销准入 gate 契约测试。

覆盖 spec 报销校验 6 个点 + 隔离性 5 个：
    12. 空配置时不拦截
    13. 用户已加入全部时放行
    14. 用户缺任意一个时拦截
    15. 拦截文案列出缺失列表
    16. "我已加入，重新检查" callback 存在
    17. 重新检查通过后可继续
    18-22. 隔离性
    28. 新增 callback 字面量
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
        prefix=f"test_gate_{uuid.uuid4().hex}_", suffix=".db",
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


def _fake_bot_with_status(status_by_chat_id: dict) -> MagicMock:
    """构造一个 fake bot，其 get_chat_member 按 chat_id 返回指定 status。

    status_by_chat_id: {chat_id: "member" / "left" / "kicked" / Exception 等}
    Exception 实例会被 raise 模拟 bot.get_chat_member 失败（容错路径）。
    """
    bot = MagicMock()
    async def fake_gcm(chat_id, user_id):
        v = status_by_chat_id.get(chat_id, "left")
        if isinstance(v, Exception):
            raise v
        cm = MagicMock()
        cm.status = v
        return cm
    bot.get_chat_member = AsyncMock(side_effect=fake_gcm)
    return bot


# ============ 12. 空配置 → 放行 ============


def test_empty_config_does_not_block(temp_db):
    """配置为空 → check 返回 (True, [])，不调 bot.get_chat_member。"""
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    bot = _fake_bot_with_status({})  # 任何 chat 都视为 left
    ok, missing = _run(check_user_subscribed_for_reimburse(bot, user_id=10001))
    assert ok is True
    assert missing == []
    bot.get_chat_member.assert_not_called()


# ============ 13. 全已加入 → 放行 ============


def test_all_joined_passes(temp_db):
    from bot.database import add_reimburse_required_chat
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    _run(add_reimburse_required_chat(-1001, "channel", "A", "https://t.me/a"))
    _run(add_reimburse_required_chat(-1002, "supergroup", "B", "https://t.me/b"))
    bot = _fake_bot_with_status({-1001: "member", -1002: "administrator"})
    ok, missing = _run(check_user_subscribed_for_reimburse(bot, user_id=10001))
    assert ok is True
    assert missing == []


# ============ 14. 缺任意一个 → 拦截 ============


def test_missing_any_one_blocks_with_list(temp_db):
    from bot.database import add_reimburse_required_chat
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    _run(add_reimburse_required_chat(-1001, "channel", "频道A", "https://t.me/a"))
    _run(add_reimburse_required_chat(-1002, "supergroup", "群B", "https://t.me/b"))
    bot = _fake_bot_with_status({-1001: "member", -1002: "left"})
    ok, missing = _run(check_user_subscribed_for_reimburse(bot, user_id=10001))
    assert ok is False
    assert len(missing) == 1
    assert missing[0]["chat_id"] == -1002
    # 15. 拦截 list 含 display_name 与 invite_link，供 UI 渲染
    assert missing[0]["display_name"] == "群B"
    assert missing[0]["invite_link"] == "https://t.me/b"


def test_all_left_blocks_with_full_list(temp_db):
    """用户一个都没加入 → missing 含全部。"""
    from bot.database import add_reimburse_required_chat
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    _run(add_reimburse_required_chat(-1001, "channel", "A", "https://t.me/a"))
    _run(add_reimburse_required_chat(-1002, "group", "B", "https://t.me/b"))
    _run(add_reimburse_required_chat(-1003, "supergroup", "C", "https://t.me/c"))
    bot = _fake_bot_with_status({})  # all left
    ok, missing = _run(check_user_subscribed_for_reimburse(bot, user_id=10001))
    assert ok is False
    assert {m["chat_id"] for m in missing} == {-1001, -1002, -1003}


def test_kicked_status_treated_as_missing(temp_db):
    """status=kicked 视为未加入。"""
    from bot.database import add_reimburse_required_chat
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    _run(add_reimburse_required_chat(-1001, "channel", "A", "https://t.me/a"))
    bot = _fake_bot_with_status({-1001: "kicked"})
    ok, missing = _run(check_user_subscribed_for_reimburse(bot, user_id=10001))
    assert ok is False
    assert missing[0]["chat_id"] == -1001


def test_member_administrator_creator_all_treated_as_joined(temp_db):
    """三种"已加入"status 都应通过。"""
    from bot.database import add_reimburse_required_chat
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    _run(add_reimburse_required_chat(-1001, "channel", "A", "https://t.me/a"))
    _run(add_reimburse_required_chat(-1002, "group", "B", "https://t.me/b"))
    _run(add_reimburse_required_chat(-1003, "supergroup", "C", "https://t.me/c"))
    bot = _fake_bot_with_status({
        -1001: "member", -1002: "administrator", -1003: "creator",
    })
    ok, missing = _run(check_user_subscribed_for_reimburse(bot, user_id=10001))
    assert ok is True
    assert missing == []


def test_bot_api_exception_skipped_not_blocking(temp_db):
    """bot.get_chat_member 抛异常的项 → 跳过（容错），不计入 missing。"""
    from bot.database import add_reimburse_required_chat
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    _run(add_reimburse_required_chat(-1001, "channel", "正常", "https://t.me/a"))
    _run(add_reimburse_required_chat(-1002, "channel", "Bot 异常", "https://t.me/b"))
    bot = _fake_bot_with_status({
        -1001: "member",
        -1002: RuntimeError("bot 无权限"),
    })
    ok, missing = _run(check_user_subscribed_for_reimburse(bot, user_id=10001))
    # -1002 调用失败 → 跳过；-1001 正常 → 通过
    assert ok is True
    assert missing == []


def test_disabled_item_not_enforced(temp_db):
    """enabled=False 的项不参与校验（即便用户未加入也放行）。"""
    from bot.database import (
        add_reimburse_required_chat, get_reimburse_required_chats,
        set_reimburse_required_chats,
    )
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    _run(add_reimburse_required_chat(-1001, "channel", "禁用项", "https://t.me/d"))
    # 手动把它标 disabled
    chats = _run(get_reimburse_required_chats())
    chats[0]["enabled"] = False
    _run(set_reimburse_required_chats(chats))

    bot = _fake_bot_with_status({-1001: "left"})  # 未加入也无所谓
    ok, missing = _run(check_user_subscribed_for_reimburse(bot, user_id=10001))
    assert ok is True
    assert missing == []


# ============ 16-17. recheck / back callbacks 已注册 ============


def test_recheck_submit_callback_registered_in_review_submit():
    """review_submit.py 注册 reimburse:subreq:recheck:submit handler。"""
    import bot.handlers.review_submit as mod
    src = inspect.getsource(mod)
    assert '"reimburse:subreq:recheck:submit"' in src
    assert "cb_reimburse_subreq_recheck_submit" in src


def test_back_submit_callback_registered_in_review_submit():
    import bot.handlers.review_submit as mod
    src = inspect.getsource(mod)
    assert '"reimburse:subreq:back:submit"' in src
    assert "cb_reimburse_subreq_back_submit" in src


def test_recheck_card_callback_registered_in_review_card():
    import bot.handlers.review_card as mod
    src = inspect.getsource(mod)
    assert '"reimburse:subreq:recheck:card"' in src
    assert "cb_reimburse_subreq_recheck_card" in src


def test_back_card_callback_registered_in_review_card():
    import bot.handlers.review_card as mod
    src = inspect.getsource(mod)
    assert '"reimburse:subreq:back:card"' in src
    assert "cb_reimburse_subreq_back_card" in src


# ============ Gate keyboard 渲染 ============


def test_user_gate_kb_renders_recheck_and_back():
    """reimburse_subreq_user_gate_kb 必须含 recheck + back 两个 callback。"""
    from bot.keyboards.admin_kb import reimburse_subreq_user_gate_kb
    missing = [{"chat_id": -1001, "display_name": "A", "invite_link": "https://t.me/a"}]
    kb = reimburse_subreq_user_gate_kb(missing, context="submit")
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
    assert "reimburse:subreq:recheck:submit" in cbs
    assert "reimburse:subreq:back:submit" in cbs


def test_user_gate_kb_renders_recheck_back_for_card_context():
    from bot.keyboards.admin_kb import reimburse_subreq_user_gate_kb
    missing = [{"chat_id": -1001, "display_name": "A", "invite_link": "https://t.me/a"}]
    kb = reimburse_subreq_user_gate_kb(missing, context="card")
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
    assert "reimburse:subreq:recheck:card" in cbs
    assert "reimburse:subreq:back:card" in cbs


def test_user_gate_kb_renders_join_url_button_per_missing_item():
    """每个 missing 项含 invite_link 时渲染 URL 按钮。"""
    from bot.keyboards.admin_kb import reimburse_subreq_user_gate_kb
    missing = [
        {"chat_id": -1001, "display_name": "频道A", "invite_link": "https://t.me/a"},
        {"chat_id": -1002, "display_name": "群B", "invite_link": "https://t.me/b"},
    ]
    kb = reimburse_subreq_user_gate_kb(missing, context="submit")
    urls = [b.url for row in kb.inline_keyboard for b in row if b.url]
    assert "https://t.me/a" in urls
    assert "https://t.me/b" in urls


# ============ Submit FSM 路径：cb_review_reimburse_yes 调 gate ============


def test_review_submit_handler_calls_check_user_subscribed_for_reimburse():
    """cb_review_reimburse_yes 内调用 check_user_subscribed_for_reimburse。"""
    import bot.handlers.review_submit as mod
    src = inspect.getsource(mod)
    idx = src.find("async def cb_review_reimburse_yes(")
    assert idx > 0
    body = src[idx:idx + 1500]
    assert "check_user_subscribed_for_reimburse" in body


def test_card_review_handler_calls_check_user_subscribed_for_reimburse():
    """cb_card_reimburse_yes 内调用 check_user_subscribed_for_reimburse。"""
    import bot.handlers.review_card as mod
    src = inspect.getsource(mod)
    idx = src.find("async def cb_card_reimburse_yes(")
    assert idx > 0
    body = src[idx:idx + 1500]
    assert "check_user_subscribed_for_reimburse" in body


def test_review_submit_no_handler_does_not_call_gate():
    """cb_review_reimburse_no（用户选不申请）不应触发 gate（spec §22）。"""
    import bot.handlers.review_submit as mod
    src = inspect.getsource(mod)
    idx = src.find("async def cb_review_reimburse_no(")
    assert idx > 0
    # 在下一个 async def 之前提取本函数体
    end = src.find("async def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 1000]
    assert "check_user_subscribed_for_reimburse" not in body


def test_card_review_no_handler_does_not_call_gate():
    """cb_card_reimburse_no（用户选不申请）不应触发 gate。"""
    import bot.handlers.review_card as mod
    src = inspect.getsource(mod)
    idx = src.find("async def cb_card_reimburse_no(")
    assert idx > 0
    end = src.find("async def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 1000]
    assert "check_user_subscribed_for_reimburse" not in body
