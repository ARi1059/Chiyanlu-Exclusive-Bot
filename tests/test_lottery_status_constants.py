"""bot.database 抽奖状态常量测试。

这两个常量在 bot/database.py 顶层定义，是模块级常量，import 即可读取，
不涉及任何 IO 副作用。
"""

from __future__ import annotations

from bot.database import LOTTERY_STATUSES, LOTTERY_TERMINAL_STATUSES


# ============ 终态集合 ============


def test_terminal_contains_drawn():
    assert "drawn" in LOTTERY_TERMINAL_STATUSES


def test_terminal_contains_cancelled():
    assert "cancelled" in LOTTERY_TERMINAL_STATUSES


def test_terminal_contains_no_entries():
    assert "no_entries" in LOTTERY_TERMINAL_STATUSES


def test_active_not_in_terminal():
    assert "active" not in LOTTERY_TERMINAL_STATUSES


def test_draft_and_scheduled_not_in_terminal():
    assert "draft" not in LOTTERY_TERMINAL_STATUSES
    assert "scheduled" not in LOTTERY_TERMINAL_STATUSES


def test_terminal_is_exactly_three_states():
    """终态集合恰好为 {drawn, cancelled, no_entries}，防止误添加新元素"""
    assert LOTTERY_TERMINAL_STATUSES == {"drawn", "cancelled", "no_entries"}


# ============ 状态机定义 ============


def test_lottery_statuses_contains_all_required_keys():
    keys = {s["key"] for s in LOTTERY_STATUSES}
    required = {"draft", "scheduled", "active", "drawn", "cancelled", "no_entries"}
    assert required <= keys


def test_lottery_statuses_each_entry_has_key_and_label():
    for s in LOTTERY_STATUSES:
        assert "key" in s and isinstance(s["key"], str) and s["key"]
        assert "label" in s and isinstance(s["label"], str) and s["label"]


def test_terminal_is_subset_of_status_machine():
    """终态必须是状态机定义的子集（不能存在状态机里没有的终态）"""
    keys = {s["key"] for s in LOTTERY_STATUSES}
    assert LOTTERY_TERMINAL_STATUSES <= keys
