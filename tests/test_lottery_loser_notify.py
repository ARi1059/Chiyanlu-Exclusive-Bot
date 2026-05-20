"""Sprint UX-8 第四项（UX-8.4）：抽奖未中奖通知 + active 改 cost 提示契约测试。

范围：
    - bot.utils.lottery_draw._try_notify_losers 新增 helper
      （受 lottery_notify_losers config 开关控制，默认 off；1/s 节流；容错）
    - bot.utils.lottery_draw.run_lottery_draw 集成调用 _try_notify_losers
    - bot.handlers.admin_lottery.on_lottery_edit_value 当 active 期间
      entry_cost_points 变更时 → side_effects 追加"建议公告"提示

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §3.2 痛点 5 + §11.1 决策 4 + §11.3）：
    - 抽奖未中奖者完全无反馈（POLICY-lottery §9.4 既有策略）；本批让运营**按需开启**
      （`lottery_notify_losers` config，默认 off）。
    - active 期间改 entry_cost_points 不触发公告，先参与的用户被"偷偷涨价"无感知；
      本批超管收到"建议公告"提示。

约束（§11.1 决策 4）：
    - 默认 off：未配置 / "0" / 空白都视为关闭
    - 不破坏 POLICY-lottery §9.4 既有策略（保守默认）
    - 1/s 节流防 Telegram flood
    - disable_notification=True 减少打扰
    - 单条 Forbidden / BadRequest 不阻塞其它
    - 不引入 schema 迁移
"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============ helpers ============


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_ln_{uuid.uuid4().hex}_", suffix=".db",
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


@pytest.fixture(autouse=True)
def _patch_sleep():
    """节流 sleep(1.0) 不应阻塞测试；replace 为 no-op。"""
    with patch("asyncio.sleep", AsyncMock(return_value=None)):
        yield


# ============================================================
# 1. _try_notify_losers 开关 / 节流 / 容错
# ============================================================


def test_loser_notify_off_by_default(temp_db):
    """config 未配置 → 视为 off，不发任何通知。"""
    from bot.utils.lottery_draw import _try_notify_losers
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    entries = [{"user_id": 1}, {"user_id": 2}]
    winners = [{"user_id": 1}]
    n = _run(_try_notify_losers(bot, entries, winners, {"id": 1, "name": "X"}))
    assert n == 0
    bot.send_message.assert_not_called()


def test_loser_notify_off_when_config_is_zero(temp_db):
    """显式 "0" 视为关闭。"""
    from bot.database import set_config
    from bot.utils.lottery_draw import _try_notify_losers
    _run(set_config("lottery_notify_losers", "0"))
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    entries = [{"user_id": 1}, {"user_id": 2}]
    winners = [{"user_id": 1}]
    n = _run(_try_notify_losers(bot, entries, winners, {"id": 1, "name": "X"}))
    assert n == 0
    bot.send_message.assert_not_called()


def test_loser_notify_off_when_config_blank(temp_db):
    """空白 / 任意非 "1" 字符串视为 off。"""
    from bot.database import set_config
    from bot.utils.lottery_draw import _try_notify_losers
    _run(set_config("lottery_notify_losers", "   "))
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    n = _run(_try_notify_losers(
        bot, [{"user_id": 1}], [], {"id": 1, "name": "X"},
    ))
    assert n == 0


def test_loser_notify_on_when_config_is_1(temp_db):
    """显式 "1" 启用通知。"""
    from bot.database import set_config
    from bot.utils.lottery_draw import _try_notify_losers
    _run(set_config("lottery_notify_losers", "1"))
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    entries = [{"user_id": 100}, {"user_id": 200}, {"user_id": 300}]
    winners = [{"user_id": 100}]  # 100 中奖；200, 300 未中
    n = _run(_try_notify_losers(bot, entries, winners, {"id": 1, "name": "测试"}))
    assert n == 2
    assert bot.send_message.await_count == 2


def test_loser_notify_excludes_winners(temp_db):
    """中奖者不应收到"未中奖"通知（user_id 集合排除）。"""
    from bot.database import set_config
    from bot.utils.lottery_draw import _try_notify_losers
    _run(set_config("lottery_notify_losers", "1"))
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    entries = [{"user_id": 100}, {"user_id": 200}]
    winners = [{"user_id": 100}]
    _run(_try_notify_losers(bot, entries, winners, {"id": 1, "name": "X"}))
    sent_to = [c.kwargs.get("chat_id") for c in bot.send_message.await_args_list]
    assert 100 not in sent_to
    assert 200 in sent_to


def test_loser_notify_message_uses_silent(temp_db):
    """通知应 disable_notification=True 减少打扰。"""
    from bot.database import set_config
    from bot.utils.lottery_draw import _try_notify_losers
    _run(set_config("lottery_notify_losers", "1"))
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(_try_notify_losers(
        bot, [{"user_id": 100}], [], {"id": 1, "name": "X"},
    ))
    call = bot.send_message.await_args
    assert call.kwargs.get("disable_notification") is True


def test_loser_notify_text_contains_lottery_name(temp_db):
    """通知文案应含活动名（让用户知道是哪个抽奖）。"""
    from bot.database import set_config
    from bot.utils.lottery_draw import _try_notify_losers
    _run(set_config("lottery_notify_losers", "1"))
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(_try_notify_losers(
        bot, [{"user_id": 100}], [], {"id": 1, "name": "周末活动"},
    ))
    text = bot.send_message.await_args.kwargs.get("text", "")
    assert "周末活动" in text
    assert "未中奖" in text or "感谢" in text


def test_loser_notify_swallows_forbidden_error(temp_db):
    """TelegramForbiddenError 单条失败不阻塞其它通知。"""
    from aiogram.exceptions import TelegramForbiddenError
    from bot.database import set_config
    from bot.utils.lottery_draw import _try_notify_losers
    _run(set_config("lottery_notify_losers", "1"))
    bot = MagicMock()
    # 第 1 条 Forbidden，第 2 条 OK，第 3 条 OK
    bot.send_message = AsyncMock(side_effect=[
        TelegramForbiddenError(method="send_message", message="blocked"),
        None,
        None,
    ])
    entries = [{"user_id": 100}, {"user_id": 200}, {"user_id": 300}]
    n = _run(_try_notify_losers(bot, entries, [], {"id": 1, "name": "X"}))
    # 仅 2 条成功
    assert n == 2
    assert bot.send_message.await_count == 3


def test_loser_notify_returns_zero_when_no_losers(temp_db):
    """所有 entries 都中奖 → losers 集合空 → 直接返回 0，不调 send。"""
    from bot.database import set_config
    from bot.utils.lottery_draw import _try_notify_losers
    _run(set_config("lottery_notify_losers", "1"))
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    entries = [{"user_id": 100}]
    winners = [{"user_id": 100}]
    n = _run(_try_notify_losers(bot, entries, winners, {"id": 1, "name": "X"}))
    assert n == 0
    bot.send_message.assert_not_called()


def test_loser_notify_throttles_between_sends(temp_db):
    """每条通知之间应 sleep(1.0)（除最后一条）—— 静态契约。"""
    import bot.utils.lottery_draw as mod
    src = _src(mod)
    idx = src.find("async def _try_notify_losers(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    # asyncio.sleep / _asyncio.sleep（别名）二选一
    assert "sleep(1.0)" in body or "sleep(1)" in body


# ============================================================
# 2. run_lottery_draw 集成 _try_notify_losers
# ============================================================


def test_run_lottery_draw_calls_loser_notify():
    """run_lottery_draw 在 _try_notify_winners 后应调用 _try_notify_losers。"""
    import bot.utils.lottery_draw as mod
    src = _src(mod)
    idx = src.find("async def run_lottery_draw(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 6000]
    notify_winners_pos = body.find("_try_notify_winners")
    notify_losers_pos = body.find("_try_notify_losers")
    assert 0 < notify_winners_pos < notify_losers_pos


def test_run_lottery_draw_loser_notify_wrapped_in_try():
    """_try_notify_losers 调用应包 try/except 避免阻塞日志 / 返回。"""
    import bot.utils.lottery_draw as mod
    src = _src(mod)
    idx = src.find("async def run_lottery_draw(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 6000]
    losers_pos = body.find("_try_notify_losers")
    try_pos = body.rfind("try:", 0, losers_pos)
    assert 0 < try_pos < losers_pos


# ============================================================
# 3. admin_lottery.on_lottery_edit_value cost change alert
# ============================================================


def test_cost_change_alert_in_handler():
    """on_lottery_edit_value 处理 entry_cost_points 变更时
    应追加"建议公告"提示到 side_effects。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    idx = src.find("async def on_lottery_edit_value(")
    end = src.find("\n\n\n", idx + 1) if src.find("\n\n\n", idx + 1) > 0 else idx + 8000
    body = src[idx:end]
    # 必须判断 field == "entry_cost_points"
    assert 'field == "entry_cost_points"' in body
    # 必须只在 active 期间提示（已 drawn/cancelled 不再发公告）
    assert 'status' in body and '"active"' in body
    # 文案
    assert "参与积分变更" in body or "建议在频道" in body


def test_cost_change_only_when_value_changes():
    """old_value == new_value 时不追加 side_effect（避免冗余提示）。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    idx = src.find("async def on_lottery_edit_value(")
    body = src[idx:idx + 8000]
    # 应有 old_v != new_v 判断
    assert "old_v != new_v" in body or "old_v !=  new_v" in body


# ============================================================
# 4. POLICY 兼容（默认 off）
# ============================================================


def test_loser_notify_helper_signature():
    """signature 保持向后兼容；可用 keyword 调用。"""
    import inspect
    from bot.utils.lottery_draw import _try_notify_losers
    sig = inspect.signature(_try_notify_losers)
    params = list(sig.parameters)
    assert params == ["bot", "all_entries", "winners", "lottery"]


# ============================================================
# 5. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords"}
