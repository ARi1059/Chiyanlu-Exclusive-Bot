"""Sprint UX-6 第一项（UX-6.1）：用户「🎁 抽奖中心」契约测试。

范围：
    - bot.database.list_user_lottery_entries + count_user_lottery_entries 新查询
    - bot.keyboards.user_kb.user_lottery_menu_kb + user_lottery_back_kb 新 keyboard
    - bot.keyboards.user_kb.user_main_menu_kb 加 [🎁 抽奖中心] 入口
    - bot.handlers.user_lottery 4 个 callback handler
        (user:lottery / user:lottery:active / :joined / :drawn)
    - bot.routers 注册 user_lottery_router

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §3.2 痛点 1 + §11.3）：
    用户在 bot 内无任何"我的抽奖"入口，中奖通知是一次性消息，事后无法回查。
    本批主菜单新增「🎁 抽奖中心」二级页，3 tab：进行中可参与 / 我已参与 / 已开奖记录。

约束：
    - 纯只读，不动 entry / draw / publish 业务逻辑
    - 不引入 schema 迁移（新查询仅 JOIN 既有表）
    - 不改任何既有 callback_data
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
        prefix=f"test_ul_{uuid.uuid4().hex}_", suffix=".db",
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


def _flat_buttons(kb) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            out.append(btn)
    return out


async def _make_lottery(name: str, status: str = "active") -> int:
    """便利：插入一条抽奖记录，返回 lottery_id。"""
    from bot.database import get_db
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO lotteries (
                name, description, entry_method, prize_count, prize_description,
                required_chat_ids, publish_at, draw_at, status, created_by
            ) VALUES (?, '', 'button', 1, 'X', '[]', '2026-05-20', '2026-05-21', ?, 1)""",
            (name, status),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def _make_entry(lottery_id: int, user_id: int, won: int = 0) -> int:
    from bot.database import get_db
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO lottery_entries (lottery_id, user_id, won) VALUES (?, ?, ?)""",
            (lottery_id, user_id, won),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


# ============================================================
# 1. DB 查询新函数：list_user_lottery_entries / count_user_lottery_entries
# ============================================================


def test_list_user_lottery_entries_empty(temp_db):
    from bot.database import list_user_lottery_entries
    rows = _run(list_user_lottery_entries(1001))
    assert rows == []


def test_list_user_lottery_entries_returns_joined_rows(temp_db):
    """JOIN 后应含 lottery_name / lottery_status / won 等字段。"""
    from bot.database import list_user_lottery_entries
    lid = _run(_make_lottery("活动A", status="active"))
    _run(_make_entry(lid, user_id=1001))
    rows = _run(list_user_lottery_entries(1001))
    assert len(rows) == 1
    r = rows[0]
    assert r["lottery_name"] == "活动A"
    assert r["lottery_status"] == "active"
    assert r["won"] == 0
    assert "draw_at" in r and "entered_at" in r


def test_list_user_lottery_entries_filters_by_status(temp_db):
    """lottery_statuses 过滤 + 跨用户隔离。"""
    from bot.database import list_user_lottery_entries
    l1 = _run(_make_lottery("活动A", status="active"))
    l2 = _run(_make_lottery("活动B", status="drawn"))
    _run(_make_entry(l1, 1001))
    _run(_make_entry(l2, 1001))
    _run(_make_entry(l1, 9999))  # 别人的

    active = _run(list_user_lottery_entries(1001, lottery_statuses=["active"]))
    drawn = _run(list_user_lottery_entries(1001, lottery_statuses=["drawn"]))
    assert len(active) == 1 and active[0]["lottery_name"] == "活动A"
    assert len(drawn) == 1 and drawn[0]["lottery_name"] == "活动B"


def test_count_user_lottery_entries(temp_db):
    from bot.database import count_user_lottery_entries
    l1 = _run(_make_lottery("A", "active"))
    l2 = _run(_make_lottery("B", "drawn"))
    _run(_make_entry(l1, 1001))
    _run(_make_entry(l2, 1001))
    assert _run(count_user_lottery_entries(1001)) == 2
    assert _run(count_user_lottery_entries(1001, lottery_statuses=["drawn"])) == 1
    assert _run(count_user_lottery_entries(9999)) == 0


def test_list_user_lottery_entries_sorts_active_first(temp_db):
    """排序：active 状态的 entry 应排在 drawn 之前。"""
    from bot.database import list_user_lottery_entries
    drawn_l = _run(_make_lottery("已开奖", "drawn"))
    active_l = _run(_make_lottery("进行中", "active"))
    _run(_make_entry(drawn_l, 1001))
    _run(_make_entry(active_l, 1001))
    rows = _run(list_user_lottery_entries(1001))
    # 进行中应排第一
    assert rows[0]["lottery_status"] == "active"


# ============================================================
# 2. keyboard：user_lottery_menu_kb + user_lottery_back_kb
# ============================================================


def test_user_lottery_menu_kb_has_3_tab_callbacks():
    from bot.keyboards.user_kb import user_lottery_menu_kb
    kb = user_lottery_menu_kb(active_count=0, joined_count=0, drawn_count=0)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "user:lottery:active" in cbs
    assert "user:lottery:joined" in cbs
    assert "user:lottery:drawn" in cbs
    assert "user:main" in cbs


def test_user_lottery_menu_kb_shows_count_badge_when_positive():
    from bot.keyboards.user_kb import user_lottery_menu_kb
    kb = user_lottery_menu_kb(active_count=5, joined_count=3, drawn_count=0)
    texts = [b.text for b in _flat_buttons(kb)]
    assert any("(5)" in t for t in texts)
    assert any("(3)" in t for t in texts)
    # drawn=0 时不应有 "(0)"
    assert not any("(0)" in t for t in texts)


def test_user_lottery_back_kb_returns_to_lottery_menu():
    from bot.keyboards.user_kb import user_lottery_back_kb
    kb = user_lottery_back_kb()
    btns = _flat_buttons(kb)
    assert len(btns) == 1
    assert btns[0].callback_data == "user:lottery"


# ============================================================
# 3. user_main_menu_kb 入口接入
# ============================================================


def test_main_menu_has_lottery_entry():
    from bot.keyboards.user_kb import user_main_menu_kb
    kb = user_main_menu_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "user:lottery" in cbs


def test_main_menu_lottery_button_in_last_row_with_write_review():
    """[🎁 抽奖中心] 与 [📝 写评价] 同一行（行为入口同区域）。"""
    from bot.keyboards.user_kb import user_main_menu_kb
    kb = user_main_menu_kb()
    last_row_cbs = [b.callback_data for b in kb.inline_keyboard[-1]]
    assert "user:write_review" in last_row_cbs
    assert "user:lottery" in last_row_cbs


def test_main_menu_button_count_increased_by_one():
    """主菜单按钮总数应增加 1（原有 14 → 现在 15）。"""
    from bot.keyboards.user_kb import user_main_menu_kb
    kb = user_main_menu_kb()
    assert len(_flat_buttons(kb)) == 15


# ============================================================
# 4. handler 注册 + 静态契约
# ============================================================


def test_user_lottery_router_imports():
    from bot.handlers.user_lottery import router
    assert router is not None
    assert router.name == "user_lottery"


def test_user_lottery_registered_in_routers():
    """routers.py 应在 user_reimburse 之后、keyword 之前注册 user_lottery_router。"""
    import bot.routers as mod
    src = _src(mod)
    assert "user_lottery_router" in src
    reimb_pos = src.find("dp.include_router(user_reimburse_router)")
    lottery_pos = src.find("dp.include_router(user_lottery_router)")
    keyword_pos = src.find("dp.include_router(keyword_router)")
    assert 0 < reimb_pos < lottery_pos < keyword_pos


def test_handler_module_has_4_callbacks():
    import bot.handlers.user_lottery as mod
    src = _src(mod)
    for cb in (
        'F.data == "user:lottery"',
        'F.data == "user:lottery:active"',
        'F.data == "user:lottery:joined"',
        'F.data == "user:lottery:drawn"',
    ):
        assert cb in src


def test_lottery_center_count_queries_wrapped_in_try():
    """主入口的 3 个计数查询应各自包 try/except 容错。"""
    import bot.handlers.user_lottery as mod
    src = _src(mod)
    idx = src.find("async def cb_user_lottery(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert body.count("try:") >= 3
    assert body.count("except") >= 3


# ============================================================
# 5. handler 端到端行为（mock callback + edit_text）
# ============================================================


def test_cb_user_lottery_renders_summary(temp_db):
    """主入口应渲染 3 个 count + keyboard。"""
    from bot.handlers.user_lottery import cb_user_lottery
    _run(_make_lottery("A", "active"))
    _run(_make_lottery("B", "active"))
    cb = MagicMock()
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    _run(cb_user_lottery(cb))
    call = cb.message.edit_text.await_args
    text = call.args[0] if call.args else call.kwargs.get("text", "")
    assert "抽奖中心" in text
    assert "2 场" in text  # active_count


def test_cb_active_empty_uses_back_kb(temp_db):
    """无 active 抽奖时仍渲染空提示 + back kb。"""
    from bot.handlers.user_lottery import cb_user_lottery_active
    cb = MagicMock()
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    _run(cb_user_lottery_active(cb))
    call = cb.message.edit_text.await_args
    text = call.args[0] if call.args else call.kwargs.get("text", "")
    assert "暂无" in text or "可参与" in text
    kb = call.kwargs.get("reply_markup")
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "user:lottery" in cbs


def test_cb_drawn_renders_won_summary(temp_db):
    """已开奖 tab 应显示中奖统计 + 各条 ✅/⚪ 标记。"""
    from bot.handlers.user_lottery import cb_user_lottery_drawn
    l1 = _run(_make_lottery("中奖了", "drawn"))
    l2 = _run(_make_lottery("没中", "drawn"))
    _run(_make_entry(l1, 1001, won=1))
    _run(_make_entry(l2, 1001, won=0))
    cb = MagicMock()
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    _run(cb_user_lottery_drawn(cb))
    text = cb.message.edit_text.await_args.args[0]
    assert "中奖 1 次" in text
    assert "✅ 中奖" in text
    assert "⚪ 未中" in text


# ============================================================
# 6. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states"}
