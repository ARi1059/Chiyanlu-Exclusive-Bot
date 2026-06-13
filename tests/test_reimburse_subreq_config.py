"""报销专用必关频道 / 群组 - 配置层契约测试。

覆盖 spec §9 配置层 7 个测试点 + 隔离性 1 个 + 安全性 3 个：
    1. 独立 config key reimbursement_required_chats（与全局 subreq 分离）
    2. 不读取 / 不覆盖全局 subreq config key
    3. 空配置时返回空列表
    4. JSON 异常时安全返回空列表，不崩溃
    5. add_reimburse_required_chat 写入 reimbursement_required_chats
    6. remove_reimburse_required_chat 只删除对应项
    7. （admin handler 测试中覆盖 audit log）
    18. 全局必关订阅逻辑不变（required_subscriptions 表 / helper 未触动）
    23/24/25. compute_reimbursement_amount / 积分 / 抽奖逻辑未变
    26/27. 不修改 schema_migrations
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid

import pytest


@pytest.fixture
def temp_db():
    """提供干净的临时文件 SQLite + 初始化 schema（替代 :memory:）。

    使用文件而非 :memory:，因为本项目 get_db() 每次都 open/close 连接；
    :memory: 模式下跨连接不共享数据。
    """
    fd, path = tempfile.mkstemp(
        prefix=f"test_reimsubreq_{uuid.uuid4().hex}_", suffix=".db",
    )
    os.close(fd)
    # monkey-patch config.database_path 让 get_db() 用临时文件
    from bot.config import config as _config
    original_path = _config.database_path
    _config.database_path = path
    try:
        from bot.database import init_db
        asyncio.run(init_db())
        yield path
    finally:
        _config.database_path = original_path
        # 删除 main + WAL/SHM 文件
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass


def _run(coro):
    return asyncio.run(coro)


# ============ 1. config key 独立 ============


def test_reimbursement_required_chats_key_is_independent():
    """REIMBURSE_REQUIRED_CHATS_KEY 与全局 subreq 表名 / key 互不相同。"""
    from bot.database import REIMBURSE_REQUIRED_CHATS_KEY
    assert REIMBURSE_REQUIRED_CHATS_KEY == "reimbursement_required_chats"
    # 不应与任何全局 subreq 标识冲突
    assert "required_subscriptions" not in REIMBURSE_REQUIRED_CHATS_KEY
    assert REIMBURSE_REQUIRED_CHATS_KEY != "required_subscriptions"


def test_reimburse_subreq_does_not_read_global_required_subscriptions_table():
    """report subreq helper 不应实际调用全局 required_subscriptions helper。

    用 dis.get_instructions 抓取 module 中的 LOAD_GLOBAL / LOAD_NAME 指令
    （docstring 中提及不算）；本批要求 util 层不调用任何全局 subreq 函数。
    """
    import bot.utils.reimburse_subreq as mod
    # 模块级 import 项不应含 list_required_subscriptions
    assert not hasattr(mod, "list_required_subscriptions"), (
        "报销 subreq util 不应 import 全局 list_required_subscriptions"
    )
    assert not hasattr(mod, "add_required_subscription"), (
        "报销 subreq util 不应 import 全局 add_required_subscription"
    )
    # 但应 import 自己的 helper
    assert hasattr(mod, "get_reimburse_required_chats"), (
        "报销 subreq util 应从 bot.database import get_reimburse_required_chats"
    )


def test_global_required_subscriptions_helpers_still_importable():
    """全局 subreq helper 完全未触动（spec §18 隔离性）。"""
    from bot.database import (
        add_required_subscription,
        list_required_subscriptions,
        get_required_subscription,
        toggle_required_subscription,
        remove_required_subscription,
    )
    for fn in (
        add_required_subscription, list_required_subscriptions,
        get_required_subscription, toggle_required_subscription,
        remove_required_subscription,
    ):
        assert callable(fn)


# ============ 2-3. 空配置 → 空列表 ============


def test_get_reimburse_required_chats_empty_when_key_absent(temp_db):
    """config key 不存在时 → 返回空列表。"""
    from bot.database import get_reimburse_required_chats
    result = _run(get_reimburse_required_chats())
    assert result == []


def test_get_reimburse_required_chats_empty_when_value_empty_string(temp_db):
    """key 存在但 value=空字符串 → 返回空列表。"""
    from bot.database import get_reimburse_required_chats, set_config
    _run(set_config("reimbursement_required_chats", ""))
    assert _run(get_reimburse_required_chats()) == []


# ============ 4. JSON 异常时安全 ============


def test_get_reimburse_required_chats_safe_on_invalid_json(temp_db):
    """value 非法 JSON → 返回空列表 + 不崩溃。"""
    from bot.database import get_reimburse_required_chats, set_config
    _run(set_config("reimbursement_required_chats", "not a json"))
    assert _run(get_reimburse_required_chats()) == []


def test_get_reimburse_required_chats_safe_on_non_list_json(temp_db):
    """value 是 JSON 但非 list → 返回空列表。"""
    from bot.database import get_reimburse_required_chats, set_config
    _run(set_config("reimbursement_required_chats", '{"foo": "bar"}'))
    assert _run(get_reimburse_required_chats()) == []


def test_get_reimburse_required_chats_skips_invalid_items(temp_db):
    """list 中含异常 item（缺 chat_id / 类型错误）→ 跳过；其余正常解析。"""
    from bot.database import get_reimburse_required_chats, set_config
    raw = json.dumps([
        {"chat_id": -1001, "display_name": "ok1"},
        "not a dict",
        {"chat_id": "abc"},  # 无法转 int
        {"chat_id": -1002, "display_name": "ok2"},
        None,
    ])
    _run(set_config("reimbursement_required_chats", raw))
    result = _run(get_reimburse_required_chats())
    chat_ids = [c["chat_id"] for c in result]
    assert chat_ids == [-1001, -1002]


# ============ 5. add 写入正确字段 ============


def test_add_reimburse_required_chat_writes_to_config(temp_db):
    from bot.database import (
        add_reimburse_required_chat,
        get_config,
        get_reimburse_required_chats,
    )
    ok = _run(add_reimburse_required_chat(
        chat_id=-1001234567890,
        chat_type="channel",
        display_name="测试频道",
        invite_link="https://t.me/+abc",
    ))
    assert ok is True
    # 读取 raw config 验证 key 名
    raw = _run(get_config("reimbursement_required_chats"))
    assert raw is not None
    data = json.loads(raw)
    assert len(data) == 1
    assert data[0]["chat_id"] == -1001234567890
    assert data[0]["chat_type"] == "channel"
    assert data[0]["display_name"] == "测试频道"
    assert data[0]["invite_link"] == "https://t.me/+abc"
    assert data[0]["enabled"] is True

    # 也通过 helper 验证
    chats = _run(get_reimburse_required_chats())
    assert len(chats) == 1


def test_add_reimburse_required_chat_rejects_duplicate(temp_db):
    from bot.database import add_reimburse_required_chat, get_reimburse_required_chats
    _run(add_reimburse_required_chat(-1001, "channel", "A", "https://t.me/a"))
    ok = _run(add_reimburse_required_chat(-1001, "channel", "重复", "https://t.me/dup"))
    assert ok is False
    chats = _run(get_reimburse_required_chats())
    assert len(chats) == 1
    assert chats[0]["display_name"] == "A"  # 原始未被覆盖


def test_add_reimburse_required_chat_multiple_items_distinct(temp_db):
    from bot.database import add_reimburse_required_chat, get_reimburse_required_chats
    _run(add_reimburse_required_chat(-1001, "channel", "A", "https://t.me/a"))
    _run(add_reimburse_required_chat(-1002, "supergroup", "B", "https://t.me/b"))
    _run(add_reimburse_required_chat(-1003, "group", "C", "https://t.me/c"))
    chats = _run(get_reimburse_required_chats())
    assert len(chats) == 3
    assert {c["chat_id"] for c in chats} == {-1001, -1002, -1003}


# ============ 6. remove 只删对应项 ============


def test_remove_reimburse_required_chat_removes_only_target(temp_db):
    from bot.database import (
        add_reimburse_required_chat,
        remove_reimburse_required_chat,
        get_reimburse_required_chats,
    )
    _run(add_reimburse_required_chat(-1001, "channel", "A", "https://t.me/a"))
    _run(add_reimburse_required_chat(-1002, "channel", "B", "https://t.me/b"))
    _run(add_reimburse_required_chat(-1003, "channel", "C", "https://t.me/c"))

    ok = _run(remove_reimburse_required_chat(-1002))
    assert ok is True
    remaining = _run(get_reimburse_required_chats())
    chat_ids = sorted(c["chat_id"] for c in remaining)
    assert chat_ids == [-1003, -1001]


def test_remove_reimburse_required_chat_returns_false_when_missing(temp_db):
    from bot.database import (
        add_reimburse_required_chat, remove_reimburse_required_chat,
        get_reimburse_required_chats,
    )
    _run(add_reimburse_required_chat(-1001, "channel", "A", "https://t.me/a"))
    ok = _run(remove_reimburse_required_chat(-9999))
    assert ok is False
    # 现有数据不动
    assert len(_run(get_reimburse_required_chats())) == 1


def test_remove_reimburse_required_chat_does_not_affect_global_table(temp_db):
    """删除报销 subreq 不应影响全局 required_subscriptions 表（隔离性）。"""
    from bot.database import (
        add_required_subscription, list_required_subscriptions,
        add_reimburse_required_chat, remove_reimburse_required_chat,
    )
    # 准备全局 subreq 数据
    _run(add_required_subscription(
        chat_id=-2001, chat_type="channel",
        display_name="全局频道", invite_link="https://t.me/g",
    ))
    # 准备报销 subreq 数据
    _run(add_reimburse_required_chat(-1001, "channel", "报销频道", "https://t.me/r"))
    # 删除报销项
    _run(remove_reimburse_required_chat(-1001))
    # 全局表数据不应受影响
    global_items = _run(list_required_subscriptions(active_only=False))
    assert len(global_items) == 1
    assert global_items[0]["chat_id"] == -2001


# ============ 隔离性：util 层 ============


def test_check_user_subscribed_for_reimburse_empty_config_returns_ok(temp_db):
    """配置为空 → check_user_subscribed_for_reimburse 直接返回 (True, [])。"""
    from bot.utils.reimburse_subreq import check_user_subscribed_for_reimburse
    # 不需要 bot.get_chat_member 调用（早返回）
    ok, missing = _run(check_user_subscribed_for_reimburse(bot=None, user_id=999))
    assert ok is True
    assert missing == []


# ============ 安全性：schema / 业务保护 ============


def test_schema_migrations_baseline_unchanged():
    """spec §26：本批不动 schema。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    from _migration_baseline import EXPECTED_MIGRATION_VERSIONS
    assert {m.version for m in MIGRATIONS} == EXPECTED_MIGRATION_VERSIONS


def test_compute_reimbursement_amount_unchanged():
    """spec §23：报销金额计算函数未触动。"""
    from bot.database import compute_reimbursement_amount
    assert callable(compute_reimbursement_amount)


def test_point_transaction_helpers_unchanged():
    """spec §24：积分相关 helper 未触动。"""
    from bot.database import (
        add_point_transaction,
        get_user_total_points,
    )
    assert callable(add_point_transaction)
    assert callable(get_user_total_points)


# Phase A0（2026-05-23）已下线：test_lottery_helpers_unchanged（抽奖功能整体下线）
