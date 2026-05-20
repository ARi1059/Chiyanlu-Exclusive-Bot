"""报销每周 approved 上限 config 化（2026-05）契约 + 集成测试。

测试范围：
    1. 常量 REIMBURSE_WEEKLY_LIMIT_DEFAULT/MIN/MAX 值
    2. get_reimbursement_weekly_limit 默认 / 越界回退 / 解析失败回退
    3. set_reimbursement_weekly_limit 边界 + ValueError
    4. admin_reimburse_config_kb 新增按钮
    5. keyboard 契约（weekly_limit_menu / cancel / confirm）
    6. handler 源码静态契约（callback 字面量 / 写 audit）
    7. snapshot 读 config（不再硬编码）
    8. 集成断言：旧 `>= 1` 硬编码已替换
"""

from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from unittest.mock import patch

import pytest


# ============================================================
# 1. 常量
# ============================================================


def test_constants_values():
    from bot.database import (
        REIMBURSE_WEEKLY_LIMIT_DEFAULT,
        REIMBURSE_WEEKLY_LIMIT_MAX,
        REIMBURSE_WEEKLY_LIMIT_MIN,
    )
    assert REIMBURSE_WEEKLY_LIMIT_DEFAULT == 1
    assert REIMBURSE_WEEKLY_LIMIT_MIN == 1
    assert REIMBURSE_WEEKLY_LIMIT_MAX == 10


# ============================================================
# 2. get/set 行为（与 config 表交互）
# ============================================================


@pytest.fixture
def temp_db_path():
    """临时 DB + 隔离 config 表。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


def _setup_config_table(db_path: str):
    """建最小 config 表（不依赖完整 schema）。"""
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()


def _run(coro):
    return asyncio.run(coro)


def test_get_default_when_unset(temp_db_path, monkeypatch):
    _setup_config_table(temp_db_path)
    monkeypatch.setattr("bot.config.config.database_path", temp_db_path)
    from bot.database import get_reimbursement_weekly_limit, REIMBURSE_WEEKLY_LIMIT_DEFAULT
    v = _run(get_reimbursement_weekly_limit())
    assert v == REIMBURSE_WEEKLY_LIMIT_DEFAULT


def test_set_and_get_within_range(temp_db_path, monkeypatch):
    _setup_config_table(temp_db_path)
    monkeypatch.setattr("bot.config.config.database_path", temp_db_path)
    from bot.database import (
        get_reimbursement_weekly_limit,
        set_reimbursement_weekly_limit,
    )
    _run(set_reimbursement_weekly_limit(3))
    assert _run(get_reimbursement_weekly_limit()) == 3
    _run(set_reimbursement_weekly_limit(10))
    assert _run(get_reimbursement_weekly_limit()) == 10
    _run(set_reimbursement_weekly_limit(1))
    assert _run(get_reimbursement_weekly_limit()) == 1


def test_set_below_min_raises(temp_db_path, monkeypatch):
    _setup_config_table(temp_db_path)
    monkeypatch.setattr("bot.config.config.database_path", temp_db_path)
    from bot.database import set_reimbursement_weekly_limit
    with pytest.raises(ValueError):
        _run(set_reimbursement_weekly_limit(0))


def test_set_above_max_raises(temp_db_path, monkeypatch):
    _setup_config_table(temp_db_path)
    monkeypatch.setattr("bot.config.config.database_path", temp_db_path)
    from bot.database import set_reimbursement_weekly_limit
    with pytest.raises(ValueError):
        _run(set_reimbursement_weekly_limit(11))


def test_get_invalid_string_falls_back_to_default(temp_db_path, monkeypatch):
    """config 值非整数 → 回退到 default，不抛异常。"""
    _setup_config_table(temp_db_path)
    monkeypatch.setattr("bot.config.config.database_path", temp_db_path)
    import sqlite3
    conn = sqlite3.connect(temp_db_path)
    conn.execute(
        "INSERT INTO config (key, value) VALUES (?, ?)",
        ("reimbursement_weekly_limit", "abc"),
    )
    conn.commit()
    conn.close()
    from bot.database import get_reimbursement_weekly_limit, REIMBURSE_WEEKLY_LIMIT_DEFAULT
    assert _run(get_reimbursement_weekly_limit()) == REIMBURSE_WEEKLY_LIMIT_DEFAULT


def test_get_out_of_range_falls_back_to_default(temp_db_path, monkeypatch):
    """config 值越界（如 99）→ 回退到 default。"""
    _setup_config_table(temp_db_path)
    monkeypatch.setattr("bot.config.config.database_path", temp_db_path)
    import sqlite3
    conn = sqlite3.connect(temp_db_path)
    conn.execute(
        "INSERT INTO config (key, value) VALUES (?, ?)",
        ("reimbursement_weekly_limit", "99"),
    )
    conn.commit()
    conn.close()
    from bot.database import get_reimbursement_weekly_limit, REIMBURSE_WEEKLY_LIMIT_DEFAULT
    assert _run(get_reimbursement_weekly_limit()) == REIMBURSE_WEEKLY_LIMIT_DEFAULT


# ============================================================
# 3. admin_reimburse_config_kb 新增按钮
# ============================================================


def _flat(kb):
    return [b for row in kb.inline_keyboard for b in row]


def test_admin_reimburse_config_kb_has_weekly_limit_entry():
    from bot.keyboards.admin_kb import admin_reimburse_config_kb
    kb = admin_reimburse_config_kb()
    cbs = [b.callback_data for b in _flat(kb)]
    assert "system:reimburse_weekly_limit" in cbs


# ============================================================
# 4. weekly_limit keyboard 契约
# ============================================================


def test_weekly_limit_menu_kb_has_edit_and_back():
    from bot.keyboards.admin_kb import reimburse_weekly_limit_menu_kb
    kb = reimburse_weekly_limit_menu_kb()
    cbs = [b.callback_data for b in _flat(kb)]
    assert "system:reimburse_weekly_limit:edit" in cbs
    assert "admin:reimburse_config" in cbs


def test_weekly_limit_cancel_kb_returns_to_menu():
    from bot.keyboards.admin_kb import reimburse_weekly_limit_cancel_kb
    kb = reimburse_weekly_limit_cancel_kb()
    cbs = [b.callback_data for b in _flat(kb)]
    assert "system:reimburse_weekly_limit" in cbs


def test_weekly_limit_confirm_kb_has_confirm_and_cancel():
    from bot.keyboards.admin_kb import reimburse_weekly_limit_confirm_kb
    kb = reimburse_weekly_limit_confirm_kb()
    cbs = [b.callback_data for b in _flat(kb)]
    assert "system:reimburse_weekly_limit:confirm" in cbs
    assert "system:reimburse_weekly_limit" in cbs


def test_all_weekly_limit_callbacks_within_64b():
    from bot.keyboards.admin_kb import (
        reimburse_weekly_limit_cancel_kb,
        reimburse_weekly_limit_confirm_kb,
        reimburse_weekly_limit_menu_kb,
    )
    for kb in (
        reimburse_weekly_limit_menu_kb(),
        reimburse_weekly_limit_cancel_kb(),
        reimburse_weekly_limit_confirm_kb(),
    ):
        for b in _flat(kb):
            assert b.callback_data is not None
            assert len(b.callback_data.encode("utf-8")) <= 64


# ============================================================
# 5. handler 源码静态契约
# ============================================================


def _src(mod):
    return inspect.getsource(mod)


def test_handler_module_registers_weekly_limit_callbacks():
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    assert '"system:reimburse_weekly_limit"' in src
    assert '"system:reimburse_weekly_limit:edit"' in src
    assert '"system:reimburse_weekly_limit:confirm"' in src


def test_handler_writes_audit_log():
    """confirm handler 必须调用 log_admin_audit 且 action='reimburse_weekly_limit_set'。"""
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    # action 字符串字面量（单/双引号都可）
    assert "reimburse_weekly_limit_set" in src
    assert "log_admin_audit" in src


def test_handler_uses_set_helper_not_direct_set_config():
    """confirm handler 必须经 set_reimbursement_weekly_limit 落库，
    不允许直接 set_config（保证边界校验生效）。"""
    import bot.handlers.reimburse_settings_admin as mod
    src = _src(mod)
    # confirm 上下文段
    idx = src.find("async def cb_weekly_limit_confirm(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "set_reimbursement_weekly_limit" in body
    # 不应在 confirm 函数体内直接 set_config(REIMBURSE_WEEKLY_LIMIT_KEY, ...)
    assert "REIMBURSE_WEEKLY_LIMIT_KEY" not in body


# ============================================================
# 6. snapshot 读 config（不再硬编码 1）
# ============================================================


def test_snapshot_reads_weekly_limit_from_config():
    """get_reimbursement_rules_snapshot 必须调用 get_reimbursement_weekly_limit。"""
    import bot.services.reimbursement_rules as mod
    src = _src(mod)
    assert "get_reimbursement_weekly_limit" in src
    # 不应再有 WEEKLY_APPROVED_LIMIT 模块级常量
    assert "WEEKLY_APPROVED_LIMIT = 1" not in src


def test_render_rules_now_marks_configurable():
    """render_reimbursement_rules 应说明可配置范围 + 不再标硬编码。"""
    from datetime import datetime
    from bot.services.reimbursement_rules import (
        ReimbursementRulesSnapshot,
        render_reimbursement_rules,
    )
    snap = ReimbursementRulesSnapshot(
        feature_enabled=True,
        monthly_pool=3000,
        current_month_key="2026-05",
        min_points=10,
        weekly_approved_limit=2,
        queued_count=4,
        current_week_key="2026-W21",
        required_chats_total=2,
        required_chats_enabled=2,
        generated_at=datetime(2026, 5, 20, 14, 30, 0),
    )
    text = render_reimbursement_rules(snap)
    assert "每用户每周 approved 上限：2 次" in text
    assert "可配置 1-10" in text
    assert "硬编码" not in text


# ============================================================
# 7. 业务校验集成（admin_reimburse + user_reimburse）
# ============================================================


def test_admin_reimburse_uses_get_helper():
    """admin_reimburse.py 必须调用 get_reimbursement_weekly_limit。"""
    import bot.handlers.admin_reimburse as mod
    src = _src(mod)
    assert "get_reimbursement_weekly_limit" in src
    # 不应再含 ">= 1" 硬编码的 weekly check 上下文（week_used >= 1）
    assert "week_used >= 1" not in src
    assert "week_full = week_used >= 1" not in src


def test_user_reimburse_uses_get_helper():
    """user_reimburse.py 必须调用 get_reimbursement_weekly_limit 并渲染动态值。"""
    import bot.handlers.user_reimburse as mod
    src = _src(mod)
    assert "get_reimbursement_weekly_limit" in src
    # 不再硬编码 "/1 笔"
    assert "/1 笔" not in src
