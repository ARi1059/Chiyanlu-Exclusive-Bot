"""Sprint UX-10 第二项（UX-10.2）：群组关键词冷却 config 化 + silenced 埋点契约测试。

范围：
    - bot.utils.group_search.check_group_cooldown 改为 async，从 config 读取每层秒数
    - bot.utils.group_search._read_cooldown_seconds 读取 + 校验 + 回退默认
    - bot.handlers.keyword 4 处 cooldown 调用全部加 await + reason 捕获
    - bot.handlers.keyword 命中冷却时落 keyword_silenced 事件

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §6 + §11.3）：
    群组冷却三层硬编码（5s / 30s / 15s），运营无法在线调整；命中冷却完全静默
    既无文案也无埋点，超管线上无从评估"少回复 vs 多打扰"。
    本批：
        - 三个 config key（keyword.cooldown.{user,keyword,group}）覆盖默认
        - 命中冷却时落 keyword_silenced 事件，便于离线分析

约束：
    - 不改 callback_data；不改 record_group_cooldown 签名
    - 不引入 schema 迁移（只用既有 config 表的 KV）
    - 命中冷却时仍然静默不回复（行为一致）
"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
import time
import uuid

import pytest


# ============ helpers ============


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_kwcd_{uuid.uuid4().hex}_", suffix=".db",
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


def _reset_cooldown_state():
    """清空进程内冷却 dict，避免跨 case 污染。"""
    from bot.utils import group_search as gs
    gs._user_in_group_last.clear()
    gs._keyword_in_group_last.clear()
    gs._group_total_last.clear()


# ============================================================
# 1. check_group_cooldown 是 async（签名契约）
# ============================================================


def test_check_group_cooldown_is_async():
    from bot.utils.group_search import check_group_cooldown
    assert inspect.iscoroutinefunction(check_group_cooldown)


def test_read_cooldown_seconds_helper_exists():
    from bot.utils.group_search import _read_cooldown_seconds
    assert inspect.iscoroutinefunction(_read_cooldown_seconds)


def test_cooldown_config_keys_dict_exposed():
    """UX-10.2：3 层 config key 应在模块级表里暴露，方便 admin 面板 / 文档同源引用。"""
    from bot.utils.group_search import _COOLDOWN_CONFIG_KEYS
    assert set(_COOLDOWN_CONFIG_KEYS.keys()) == {"user", "keyword", "group"}
    # value 是 (config_key, default) 二元组
    for layer, (key, default) in _COOLDOWN_CONFIG_KEYS.items():
        assert isinstance(key, str) and key.startswith("keyword.cooldown.")
        assert isinstance(default, int) and default >= 0


# ============================================================
# 2. _read_cooldown_seconds 行为
# ============================================================


def test_read_cooldown_returns_default_when_unset(temp_db):
    from bot.utils.group_search import (
        _read_cooldown_seconds,
        USER_GROUP_COOLDOWN_SECONDS,
        KEYWORD_GROUP_COOLDOWN_SECONDS,
        GROUP_TOTAL_COOLDOWN_SECONDS,
    )
    assert _run(_read_cooldown_seconds("user")) == USER_GROUP_COOLDOWN_SECONDS
    assert _run(_read_cooldown_seconds("keyword")) == KEYWORD_GROUP_COOLDOWN_SECONDS
    assert _run(_read_cooldown_seconds("group")) == GROUP_TOTAL_COOLDOWN_SECONDS


def test_read_cooldown_uses_config_value_when_set(temp_db):
    from bot.database import set_config
    from bot.utils.group_search import _read_cooldown_seconds
    _run(set_config("keyword.cooldown.user", "7"))
    _run(set_config("keyword.cooldown.keyword", "20"))
    _run(set_config("keyword.cooldown.group", "3"))
    assert _run(_read_cooldown_seconds("user")) == 7
    assert _run(_read_cooldown_seconds("keyword")) == 20
    assert _run(_read_cooldown_seconds("group")) == 3


def test_read_cooldown_blank_falls_back_to_default(temp_db):
    """config 空字符串 / 纯空白 → 回退默认（运营误删值的兜底）。"""
    from bot.database import set_config
    from bot.utils.group_search import (
        _read_cooldown_seconds,
        USER_GROUP_COOLDOWN_SECONDS,
    )
    _run(set_config("keyword.cooldown.user", ""))
    assert _run(_read_cooldown_seconds("user")) == USER_GROUP_COOLDOWN_SECONDS
    _run(set_config("keyword.cooldown.user", "   "))
    assert _run(_read_cooldown_seconds("user")) == USER_GROUP_COOLDOWN_SECONDS


def test_read_cooldown_invalid_value_falls_back_to_default(temp_db):
    """非整数值 → 回退默认。"""
    from bot.database import set_config
    from bot.utils.group_search import (
        _read_cooldown_seconds,
        KEYWORD_GROUP_COOLDOWN_SECONDS,
    )
    _run(set_config("keyword.cooldown.keyword", "abc"))
    assert _run(_read_cooldown_seconds("keyword")) == KEYWORD_GROUP_COOLDOWN_SECONDS
    _run(set_config("keyword.cooldown.keyword", "1.5"))
    assert _run(_read_cooldown_seconds("keyword")) == KEYWORD_GROUP_COOLDOWN_SECONDS


def test_read_cooldown_negative_value_falls_back_to_default(temp_db):
    """负数 → 回退默认（防止运营手抖把冷却关掉再开导致积分泄漏式刷屏）。"""
    from bot.database import set_config
    from bot.utils.group_search import (
        _read_cooldown_seconds,
        GROUP_TOTAL_COOLDOWN_SECONDS,
    )
    _run(set_config("keyword.cooldown.group", "-5"))
    assert _run(_read_cooldown_seconds("group")) == GROUP_TOTAL_COOLDOWN_SECONDS


def test_read_cooldown_oversize_value_falls_back_to_default(temp_db):
    """> 3600 秒（1 小时）视作配置失误 → 回退默认。"""
    from bot.database import set_config
    from bot.utils.group_search import (
        _read_cooldown_seconds,
        USER_GROUP_COOLDOWN_SECONDS,
    )
    _run(set_config("keyword.cooldown.user", "999999"))
    assert _run(_read_cooldown_seconds("user")) == USER_GROUP_COOLDOWN_SECONDS


def test_read_cooldown_zero_is_valid_means_disabled(temp_db):
    """0 是合法值（表示关闭该层冷却）；不应回退默认。"""
    from bot.database import set_config
    from bot.utils.group_search import _read_cooldown_seconds
    _run(set_config("keyword.cooldown.user", "0"))
    assert _run(_read_cooldown_seconds("user")) == 0


# ============================================================
# 3. check_group_cooldown 行为（端到端：config + 三层）
# ============================================================


def test_check_default_cooldowns_block_repeat_in_window(temp_db):
    """默认值下：连续两次同 user + 同 keyword + 同 group → 第 2 次被挡。"""
    from bot.utils.group_search import check_group_cooldown, record_group_cooldown
    _reset_cooldown_state()
    group_id, user_id, q = 100, 200, "hello"
    ok1, _ = _run(check_group_cooldown(group_id, user_id, q))
    assert ok1 is True
    record_group_cooldown(group_id, user_id, q)
    ok2, reason = _run(check_group_cooldown(group_id, user_id, q))
    assert ok2 is False
    # group_total 是第一层校验，命中后 reason="group_total"
    assert reason in ("group_total", "same_keyword", "user_per_group")


def test_check_config_override_zero_disables_all_layers(temp_db):
    """3 层都设为 0 → 任意重复都通过（运营紧急关闭冷却的逃生口）。"""
    from bot.database import set_config
    from bot.utils.group_search import check_group_cooldown, record_group_cooldown
    _reset_cooldown_state()
    _run(set_config("keyword.cooldown.user", "0"))
    _run(set_config("keyword.cooldown.keyword", "0"))
    _run(set_config("keyword.cooldown.group", "0"))
    group_id, user_id, q = 100, 200, "hi"
    ok1, _ = _run(check_group_cooldown(group_id, user_id, q))
    record_group_cooldown(group_id, user_id, q)
    ok2, _ = _run(check_group_cooldown(group_id, user_id, q))
    assert ok1 is True and ok2 is True


def test_check_config_override_group_layer_stricter(temp_db):
    """把群组层调到很大（如 60s）→ 即便换用户换关键词也被挡。"""
    from bot.database import set_config
    from bot.utils.group_search import check_group_cooldown, record_group_cooldown
    _reset_cooldown_state()
    _run(set_config("keyword.cooldown.group", "60"))
    group_id = 100
    ok1, _ = _run(check_group_cooldown(group_id, 200, "a"))
    record_group_cooldown(group_id, 200, "a")
    # 换 user + 换 keyword 仍被群组层挡住
    ok2, reason = _run(check_group_cooldown(group_id, 999, "different"))
    assert ok1 is True
    assert ok2 is False
    assert reason == "group_total"


def test_skip_user_layer_still_obeys_group_and_keyword(temp_db):
    """skip_user_layer=True 时（老师精准命中场景）：跳过用户层但 group/keyword 仍校验。"""
    from bot.utils.group_search import check_group_cooldown, record_group_cooldown
    _reset_cooldown_state()
    group_id, user_id, q = 100, 200, "Mr.X"
    ok1, _ = _run(check_group_cooldown(group_id, user_id, q, skip_user_layer=True))
    assert ok1 is True
    record_group_cooldown(group_id, user_id, q, skip_user_layer=True)
    ok2, reason = _run(check_group_cooldown(group_id, 999, q, skip_user_layer=True))
    assert ok2 is False
    assert reason in ("group_total", "same_keyword")


# ============================================================
# 4. handler 端：4 处调用全部加了 await + silenced 埋点
# ============================================================


def test_keyword_handler_all_callers_await_check_group_cooldown():
    """4 处 check_group_cooldown 都应是 await 形式。"""
    import bot.handlers.keyword as mod
    src = _src(mod)
    # 不应有任何非 await 的调用形式（== 直接 `check_group_cooldown(`）
    occurrences = src.count("check_group_cooldown(")
    # 1 次 import + 4 次 await 调用 = 5 次
    assert occurrences >= 4
    # 所有调用站点都应被 `await ` 前缀（除了 import 行）
    await_count = src.count("await check_group_cooldown(")
    assert await_count == 4


def test_keyword_handler_silenced_event_logged():
    """4 处冷却挡截分支都应调 _safe_log_event(..., 'keyword_silenced', ...)。"""
    import bot.handlers.keyword as mod
    src = _src(mod)
    assert src.count('"keyword_silenced"') == 4


def test_keyword_handler_silenced_payload_includes_reason():
    """埋点 payload 应含 reason 字段，方便离线分析哪一层挡住。"""
    import bot.handlers.keyword as mod
    src = _src(mod)
    # 至少包含 "reason": reason 模式
    assert src.count('"reason": reason') == 4


def test_keyword_handler_silenced_payload_includes_route():
    """埋点 payload 应含 route 字段（teacher_exact / personal_query / quick_entry / combo_search）。"""
    import bot.handlers.keyword as mod
    src = _src(mod)
    for route in ("teacher_exact", "personal_query", "quick_entry", "combo_search"):
        assert f'"{route}"' in src, f"missing route={route}"


# ============================================================
# 5. config 表注释 / 默认值同步
# ============================================================


def test_default_constants_unchanged():
    """默认值（无 config 时）不应变动；运营升级前后行为一致。"""
    from bot.utils.group_search import (
        USER_GROUP_COOLDOWN_SECONDS,
        KEYWORD_GROUP_COOLDOWN_SECONDS,
        GROUP_TOTAL_COOLDOWN_SECONDS,
    )
    assert USER_GROUP_COOLDOWN_SECONDS == 15
    assert KEYWORD_GROUP_COOLDOWN_SECONDS == 30
    assert GROUP_TOTAL_COOLDOWN_SECONDS == 5


def test_config_key_strings_documented_in_module():
    """3 个 config key 名都应出现在 group_search.py 源码里（运维 grep 可定位）。"""
    import bot.utils.group_search as mod
    src = _src(mod)
    assert '"keyword.cooldown.user"' in src
    assert '"keyword.cooldown.keyword"' in src
    assert '"keyword.cooldown.group"' in src


# ============================================================
# 6. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable", "20260613_001_teacher_is_deleted", "20260613_002_remove_quick_entry_keywords"}
