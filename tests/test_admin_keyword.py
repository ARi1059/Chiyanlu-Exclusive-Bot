"""Sprint UX-9 第一项（UX-9.1）：群组快捷词配置表 + 管理面板契约测试。

范围：
    - bot.database CRUD: list/get_by_id/get_by_trigger/create/update/delete/toggle/increment_hit
    - bot.database MIGRATIONS 注册 + seed 5 条默认快捷词
    - bot.handlers.keyword._get_quick_entry_config 表优先 + 硬编码 fallback
    - bot.handlers.keyword._send_quick_entry 命中后 hit_count +1
    - bot.keyboards.admin_kb 4 个新 keyboard
    - bot.handlers.admin_keyword router + 关键 callback 注册
    - bot.routers 注册位置

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §5.3 §1 + §11.5）：
    硬编码 _QUICK_ENTRY_CONFIG（菜单/今日/热门/推荐/筛选）改为 DB 表驱动，
    超管可在线增删改改启停；表为空时 handler 走硬编码 fallback 保证不掉线。

约束：
    - 不改 callback_data；既有 admin:settings 入口加 admin:keywords 子项
    - 不改 _PERSONAL_QUERY_POINTS / _PERSONAL_QUERY_REIMBURSE_POOL（触发代码而非文案）
    - 表清空时 keyword.py 仍能用硬编码兜底（双跑期）
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
        prefix=f"test_kwadm_{uuid.uuid4().hex}_", suffix=".db",
    )
    os.close(fd)
    from bot.config import config as _config
    original_path = _config.database_path
    _config.database_path = path
    try:
        from bot.database import init_db, run_registered_migrations, get_db
        asyncio.run(init_db())

        # 跑一次注册迁移，确保 quick_entry_keywords 表 + 5 条 seed 落地
        async def _bootstrap():
            db = await get_db()
            try:
                await run_registered_migrations(db)
            finally:
                await db.close()
        asyncio.run(_bootstrap())
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


def _flat_buttons(kb) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            out.append(btn)
    return out


# ============================================================
# 1. Migration 注册 + seed
# ============================================================


def test_migration_registered():
    from bot.database import MIGRATIONS
    versions = {m.version for m in MIGRATIONS}
    assert "20260520_002_quick_entry_keywords" in versions


def test_migration_creates_table_and_seeds_5_rows(temp_db):
    from bot.database import list_quick_entry_keywords
    rows = _run(list_quick_entry_keywords())
    triggers = {r["trigger"] for r in rows}
    # A0 后下线 菜单/热门/推荐/筛选，仅保留"今日"快捷词
    assert triggers == {"今日"}
    for r in rows:
        assert r["seeded"] == 1
        assert r["enabled"] == 1
        assert isinstance(r["buttons"], list)
        assert len(r["buttons"]) == 1  # 今日项按钮精简为仅"打开今日开课"


def test_seed_buttons_match_legacy_hardcoded(temp_db):
    """seed 数据应与硬编码 _QUICK_ENTRY_CONFIG 完全同构（双跑期保证）。"""
    from bot.database import list_quick_entry_keywords
    from bot.handlers.keyword import _QUICK_ENTRY_CONFIG
    rows = _run(list_quick_entry_keywords())
    by_trigger = {r["trigger"]: r for r in rows}
    for trigger, legacy in _QUICK_ENTRY_CONFIG.items():
        db_row = by_trigger.get(trigger)
        assert db_row is not None, f"seed 缺少 {trigger}"
        assert db_row["banner"] == legacy["banner"]
        assert db_row["body"] == legacy["body"]
        # buttons JSON 解码后是 list[list]；与 tuple 比较时按值对齐
        assert [tuple(b) for b in db_row["buttons"]] == list(legacy["buttons"])


def test_migration_is_idempotent(temp_db):
    """重跑 migration 不应重复插入（INSERT OR IGNORE）。"""
    from bot.database import (
        get_db, list_quick_entry_keywords, run_registered_migrations,
    )

    async def go():
        db = await get_db()
        try:
            await run_registered_migrations(db)
        finally:
            await db.close()
    _run(go())
    rows = _run(list_quick_entry_keywords())
    assert len(rows) == 1  # A0 后仅"今日"一条；重跑不重复插入


# ============================================================
# 2. CRUD
# ============================================================


def test_get_by_trigger_case_insensitive(temp_db):
    from bot.database import get_quick_entry_by_trigger
    for input_ in ("今日", "TODAY", "today"):
        row = _run(get_quick_entry_by_trigger(input_))
        # 中文 trigger "今日"必中；英文 "today" 不在 seed 中应返回 None
        if input_ == "今日":
            assert row is not None and row["trigger"] == "今日"
        else:
            assert row is None


def test_get_by_trigger_case_insensitive_for_ascii(temp_db):
    from bot.database import (
        create_quick_entry_keyword, get_quick_entry_by_trigger,
    )
    kid = _run(create_quick_entry_keyword(
        trigger="Menu", banner="b", body="x", buttons=[],
    ))
    assert kid is not None
    for q in ("menu", "Menu", "MENU"):
        row = _run(get_quick_entry_by_trigger(q))
        assert row is not None and row["id"] == kid


def test_create_returns_none_on_duplicate(temp_db):
    """trigger UNIQUE → 重复插入返回 None。"""
    from bot.database import create_quick_entry_keyword
    kid1 = _run(create_quick_entry_keyword(
        trigger="测试", banner="b", body="x", buttons=[],
    ))
    kid2 = _run(create_quick_entry_keyword(
        trigger="测试", banner="b2", body="x2", buttons=[],
    ))
    assert kid1 is not None
    assert kid2 is None


def test_create_returns_none_on_empty_trigger(temp_db):
    from bot.database import create_quick_entry_keyword
    kid = _run(create_quick_entry_keyword(
        trigger="   ", banner="b", body="x", buttons=[],
    ))
    assert kid is None


def test_update_partial_fields(temp_db):
    from bot.database import (
        create_quick_entry_keyword, get_quick_entry_keyword, update_quick_entry_keyword,
    )
    kid = _run(create_quick_entry_keyword(
        trigger="原", banner="b1", body="x1", buttons=[],
    ))
    ok = _run(update_quick_entry_keyword(kid, banner="b2", body="x2"))
    assert ok is True
    row = _run(get_quick_entry_keyword(kid))
    assert row["banner"] == "b2" and row["body"] == "x2"
    # trigger 未传 → 应保持不变
    assert row["trigger"] == "原"


def test_update_rejects_duplicate_trigger(temp_db):
    """改 trigger 冲突 → 返回 False，原行不变。"""
    from bot.database import (
        create_quick_entry_keyword, get_quick_entry_keyword, update_quick_entry_keyword,
    )
    kid_a = _run(create_quick_entry_keyword(
        trigger="A", banner="b", body="x", buttons=[],
    ))
    kid_b = _run(create_quick_entry_keyword(
        trigger="B", banner="b", body="x", buttons=[],
    ))
    ok = _run(update_quick_entry_keyword(kid_b, trigger="A"))
    assert ok is False
    row = _run(get_quick_entry_keyword(kid_b))
    assert row["trigger"] == "B"


def test_update_no_op_returns_false(temp_db):
    """所有字段都 None → 返回 False。"""
    from bot.database import create_quick_entry_keyword, update_quick_entry_keyword
    kid = _run(create_quick_entry_keyword(
        trigger="t", banner="b", body="x", buttons=[],
    ))
    ok = _run(update_quick_entry_keyword(kid))
    assert ok is False


def test_toggle_flips_enabled(temp_db):
    from bot.database import (
        create_quick_entry_keyword, get_quick_entry_keyword, toggle_quick_entry_enabled,
    )
    kid = _run(create_quick_entry_keyword(
        trigger="t", banner="b", body="x", buttons=[], enabled=True,
    ))
    new1 = _run(toggle_quick_entry_enabled(kid))
    new2 = _run(toggle_quick_entry_enabled(kid))
    assert new1 is False  # True → False
    assert new2 is True   # False → True
    row = _run(get_quick_entry_keyword(kid))
    assert row["enabled"] == 1


def test_toggle_returns_none_when_missing(temp_db):
    from bot.database import toggle_quick_entry_enabled
    assert _run(toggle_quick_entry_enabled(99999)) is None


def test_delete_works_and_returns_false_when_missing(temp_db):
    from bot.database import (
        create_quick_entry_keyword, delete_quick_entry_keyword,
        get_quick_entry_keyword,
    )
    kid = _run(create_quick_entry_keyword(
        trigger="del", banner="b", body="x", buttons=[],
    ))
    assert _run(delete_quick_entry_keyword(kid)) is True
    assert _run(get_quick_entry_keyword(kid)) is None
    assert _run(delete_quick_entry_keyword(kid)) is False  # 已删


def test_increment_hit_count(temp_db):
    from bot.database import (
        create_quick_entry_keyword, get_quick_entry_keyword,
        increment_quick_entry_hit_count,
    )
    kid = _run(create_quick_entry_keyword(
        trigger="hit", banner="b", body="x", buttons=[],
    ))
    _run(increment_quick_entry_hit_count(kid))
    _run(increment_quick_entry_hit_count(kid))
    row = _run(get_quick_entry_keyword(kid))
    assert row["hit_count"] == 2


def test_list_enabled_only(temp_db):
    from bot.database import (
        create_quick_entry_keyword, list_quick_entry_keywords,
        toggle_quick_entry_enabled,
    )
    kid_off = _run(create_quick_entry_keyword(
        trigger="off", banner="b", body="x", buttons=[],
    ))
    _run(toggle_quick_entry_enabled(kid_off))  # → disabled
    all_rows = _run(list_quick_entry_keywords(enabled_only=False))
    on_rows = _run(list_quick_entry_keywords(enabled_only=True))
    assert any(r["trigger"] == "off" for r in all_rows)
    assert not any(r["trigger"] == "off" for r in on_rows)


# ============================================================
# 3. handler 端 _get_quick_entry_config 行为
# ============================================================


def test_handler_uses_db_when_available(temp_db):
    """seed 的"今日"应通过 _get_quick_entry_config 返回（含 id）。"""
    from bot.handlers.keyword import _get_quick_entry_config
    cfg = _run(_get_quick_entry_config("今日"))
    assert cfg is not None
    assert cfg["id"] is not None  # DB 命中
    assert cfg["banner"] and cfg["body"]
    assert isinstance(cfg["buttons"], list)


def test_handler_falls_back_to_hardcoded_when_table_empty(temp_db):
    """表清空后 → 5 条硬编码 trigger 仍能命中（id=None）。"""
    from bot.database import delete_quick_entry_keyword, list_quick_entry_keywords
    from bot.handlers.keyword import _get_quick_entry_config, _QUICK_ENTRY_CONFIG
    # 清空全部 seed
    rows = _run(list_quick_entry_keywords())
    for r in rows:
        _run(delete_quick_entry_keyword(r["id"]))
    assert _run(list_quick_entry_keywords()) == []
    for trigger in _QUICK_ENTRY_CONFIG.keys():
        cfg = _run(_get_quick_entry_config(trigger))
        assert cfg is not None, f"fallback 未命中 {trigger}"
        assert cfg["id"] is None  # 硬编码路径无 id
        assert cfg["banner"] and cfg["body"]


def test_handler_returns_none_when_disabled_and_no_fallback(temp_db):
    """新建 + 立刻 disable → DB 行存在但 enabled=0；非硬编码 trigger 也无 fallback → None。"""
    from bot.database import create_quick_entry_keyword, toggle_quick_entry_enabled
    from bot.handlers.keyword import _get_quick_entry_config
    kid = _run(create_quick_entry_keyword(
        trigger="新词不在硬编码中", banner="b", body="x", buttons=[],
    ))
    _run(toggle_quick_entry_enabled(kid))  # disable
    cfg = _run(_get_quick_entry_config("新词不在硬编码中"))
    assert cfg is None


def test_handler_disabled_falls_back_to_hardcoded(temp_db):
    """seed 的"今日"被 disable → fallback 硬编码（仍命中）。"""
    from bot.database import get_quick_entry_by_trigger, toggle_quick_entry_enabled
    from bot.handlers.keyword import _get_quick_entry_config
    row = _run(get_quick_entry_by_trigger("今日"))
    _run(toggle_quick_entry_enabled(row["id"]))  # disable
    cfg = _run(_get_quick_entry_config("今日"))
    assert cfg is not None
    assert cfg["id"] is None  # fallback 路径


def test_handler_empty_keyword_returns_none(temp_db):
    from bot.handlers.keyword import _get_quick_entry_config
    assert _run(_get_quick_entry_config("")) is None
    assert _run(_get_quick_entry_config(None)) is None  # type: ignore[arg-type]


# ============================================================
# 4. keyboards
# ============================================================


def test_admin_settings_kb_has_keywords_entry():
    """系统配置面板应含 [🗝 关键词管理] 入口（admin:keywords callback）。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    kb = admin_settings_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "admin:keywords" in cbs


def test_admin_keyword_list_kb_empty():
    """空列表 → 仍有 [➕ 新增] + [⬅️ 返回]。"""
    from bot.keyboards.admin_kb import admin_keyword_list_kb
    kb = admin_keyword_list_kb([])
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "admin:keywords:add" in cbs
    assert "admin:settings" in cbs  # 返回入口


def test_admin_keyword_list_kb_renders_each_item():
    from bot.keyboards.admin_kb import admin_keyword_list_kb
    items = [
        {"id": 1, "trigger": "菜单", "enabled": 1, "hit_count": 7},
        {"id": 2, "trigger": "今日", "enabled": 0, "hit_count": 0},
    ]
    kb = admin_keyword_list_kb(items)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    # 每行应有 view/edit/toggle/delete 4 个 callback
    for kid in (1, 2):
        assert f"admin:keywords:view:{kid}" in cbs
        assert f"admin:keywords:edit:{kid}" in cbs
        assert f"admin:keywords:toggle:{kid}" in cbs
        assert f"admin:keywords:delete:{kid}" in cbs


def test_admin_keyword_edit_kb_has_all_fields():
    from bot.keyboards.admin_kb import admin_keyword_edit_kb
    kb = admin_keyword_edit_kb(42)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    for field in ("set_trigger", "set_banner", "set_body", "set_buttons"):
        assert f"admin:keywords:{field}:42" in cbs
    assert "admin:keywords:toggle:42" in cbs
    assert "admin:keywords" in cbs  # 返回


def test_admin_keyword_confirm_delete_kb():
    from bot.keyboards.admin_kb import admin_keyword_confirm_delete_kb
    kb = admin_keyword_confirm_delete_kb(7)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "admin:keywords:delete_yes:7" in cbs
    assert "admin:keywords:edit:7" in cbs  # 取消 → 返编辑


def test_admin_keyword_cancel_input_kb():
    from bot.keyboards.admin_kb import admin_keyword_cancel_input_kb
    kb = admin_keyword_cancel_input_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert cbs == ["admin:keywords"]


# ============================================================
# 5. router 注册 + handler 静态契约
# ============================================================


def test_admin_keyword_router_name():
    from bot.handlers.admin_keyword import router
    assert router.name == "admin_keyword"


def test_admin_keyword_registered_in_routers():
    import bot.routers as mod
    src = _src(mod)
    assert "admin_keyword_router" in src
    # 应在 reimburse_settings_admin_router 之后注册
    pos_a = src.find("dp.include_router(reimburse_settings_admin_router)")
    pos_b = src.find("dp.include_router(admin_keyword_router)")
    pos_c = src.find("dp.include_router(keyword_router)")
    assert 0 < pos_a < pos_b < pos_c


def test_admin_keyword_has_required_callbacks():
    import bot.handlers.admin_keyword as mod
    src = _src(mod)
    for cb in (
        'F.data == "admin:keywords"',
        'F.data == "admin:keywords:add"',
        'F.data.startswith("admin:keywords:edit:")',
        'F.data.startswith("admin:keywords:toggle:")',
        'F.data.startswith("admin:keywords:delete:")',
        'F.data.startswith("admin:keywords:delete_yes:")',
        'F.data.startswith("admin:keywords:set_")',
    ):
        assert cb in src, f"missing callback: {cb}"


# ============================================================
# 6. handler 端 _send_quick_entry 命中后 hit_count +1
# ============================================================


def test_send_quick_entry_increments_hit_count_on_db_path(temp_db, monkeypatch):
    """DB 命中路径 → 成功发送后 hit_count +1。"""
    from bot.database import get_quick_entry_by_trigger
    from bot.handlers import keyword as kw_mod

    # Mock bot username 获取
    async def _fake_get_bot_username(_msg):
        return "fakebot"
    monkeypatch.setattr(kw_mod, "_get_bot_username", _fake_get_bot_username)

    # Mock message.reply
    msg = MagicMock()
    msg.reply = AsyncMock(return_value=None)

    cfg = _run(kw_mod._get_quick_entry_config("今日"))
    assert cfg["id"] is not None  # DB 路径
    before = _run(get_quick_entry_by_trigger("今日"))["hit_count"]
    sent = _run(kw_mod._send_quick_entry(msg, "今日", cfg=cfg))
    assert sent is True
    after = _run(get_quick_entry_by_trigger("今日"))["hit_count"]
    assert after == before + 1


def test_send_quick_entry_no_increment_on_fallback_path(temp_db, monkeypatch):
    """硬编码 fallback 路径（id=None）→ 不应触发 hit_count 累计（无 id 可累）。"""
    from bot.database import delete_quick_entry_keyword, list_quick_entry_keywords
    from bot.handlers import keyword as kw_mod

    # 清空 DB，强制走 fallback
    for r in _run(list_quick_entry_keywords()):
        _run(delete_quick_entry_keyword(r["id"]))

    async def _fake_get_bot_username(_msg):
        return "fakebot"
    monkeypatch.setattr(kw_mod, "_get_bot_username", _fake_get_bot_username)

    msg = MagicMock()
    msg.reply = AsyncMock(return_value=None)

    cfg = _run(kw_mod._get_quick_entry_config("今日"))
    assert cfg["id"] is None  # fallback 路径
    sent = _run(kw_mod._send_quick_entry(msg, "今日", cfg=cfg))
    assert sent is True  # 仍能发送
    # 列表仍是空（无 id 不写表）
    assert _run(list_quick_entry_keywords()) == []
