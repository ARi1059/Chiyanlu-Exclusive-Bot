"""Sprint UX-9 第六项（UX-9.6）：管理员操作日志分页 + action 筛选契约测试。

范围：
    - bot.database.list_admin_audits_paged + count_admin_audits 新查询
    - bot.keyboards.admin_kb.dashboard_audit_paginated_kb 分页 keyboard
    - bot.keyboards.admin_kb.dashboard_audit_filter_menu_kb 筛选子菜单 keyboard
    - bot.handlers.admin_panel.cb_dashboard_audit 扩展支持分页 + 筛选
    - bot.handlers.admin_panel.cb_dashboard_audit_filter 筛选子菜单 handler
    - bot.handlers.admin_panel._parse_audit_callback callback 解析

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §7 痛点 9 + §11.3）：
    操作日志当前固定显示最近 20 条，无分页 / 无筛选；超管想查"某管理员上周操作"
    或"最近所有报销审核"必须翻 DB 原表。本批扩展：
      - 分页（每页 10 条）
      - 按 action 筛选（10 个高频 action）
      - 旧 callback "dashboard:audit" 仍是主入口

约束：
    - 不引入 schema 迁移
    - 既有 list_recent_admin_audits 保留不动（向后兼容）
    - 旧 callback "dashboard:audit" 仍可用（默认 page=0 无过滤）
    - 新增 callback：dashboard:audit:p:N / dashboard:audit:f:<action>:N /
      dashboard:audit:filter / dashboard:audit:all
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
        prefix=f"test_audit_{uuid.uuid4().hex}_", suffix=".db",
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


async def _insert_audit(admin_id: int, action: str, **kwargs):
    from bot.database import log_admin_audit
    await log_admin_audit(
        admin_id=admin_id,
        action=action,
        target_type=kwargs.get("target_type"),
        target_id=kwargs.get("target_id"),
        detail=kwargs.get("detail"),
    )


# ============================================================
# 1. DB 查询契约
# ============================================================


def test_list_admin_audits_paged_empty(temp_db):
    from bot.database import list_admin_audits_paged
    rows = _run(list_admin_audits_paged(offset=0, limit=10))
    assert rows == []


def test_list_admin_audits_paged_returns_newest_first(temp_db):
    """按 id DESC 排序：最新插入的在前。"""
    from bot.database import list_admin_audits_paged
    _run(_insert_audit(100, "lottery_create"))
    _run(_insert_audit(200, "review_approve"))
    rows = _run(list_admin_audits_paged(offset=0, limit=10))
    assert len(rows) == 2
    # 后插入的 review_approve 应排第一
    assert rows[0]["action"] == "review_approve"


def test_list_admin_audits_paged_offset_limit(temp_db):
    """分页：offset + limit 共同决定切片。"""
    from bot.database import list_admin_audits_paged
    for i in range(15):
        _run(_insert_audit(100, "lottery_create", target_id=str(i)))
    page0 = _run(list_admin_audits_paged(offset=0, limit=10))
    page1 = _run(list_admin_audits_paged(offset=10, limit=10))
    assert len(page0) == 10
    assert len(page1) == 5
    # 两页 id 不重叠
    p0_ids = {r["id"] for r in page0}
    p1_ids = {r["id"] for r in page1}
    assert p0_ids.isdisjoint(p1_ids)


def test_list_admin_audits_paged_filter_by_action(temp_db):
    """按 action 过滤：仅返回匹配的记录。"""
    from bot.database import list_admin_audits_paged
    _run(_insert_audit(100, "lottery_create"))
    _run(_insert_audit(200, "review_approve"))
    _run(_insert_audit(300, "review_approve"))
    _run(_insert_audit(400, "reimburse_approve"))
    rows = _run(list_admin_audits_paged(
        offset=0, limit=10, action="review_approve",
    ))
    assert len(rows) == 2
    assert all(r["action"] == "review_approve" for r in rows)


def test_list_admin_audits_paged_joins_admin_username(temp_db):
    """JOIN admins 表拿 admin_username（与既有 list_recent_admin_audits 一致）。"""
    from bot.database import get_db, list_admin_audits_paged
    # 插入 admins 表
    db = _run(get_db())
    _run(db.execute(
        """INSERT OR IGNORE INTO admins (user_id, username, is_super)
           VALUES (?, ?, 0)""",
        (123, "test_admin"),
    ))
    _run(db.commit())
    _run(db.close())
    _run(_insert_audit(123, "review_approve"))
    rows = _run(list_admin_audits_paged(offset=0, limit=10))
    assert "admin_username" in rows[0]
    assert rows[0]["admin_username"] == "test_admin"


def test_count_admin_audits_empty(temp_db):
    from bot.database import count_admin_audits
    assert _run(count_admin_audits()) == 0


def test_count_admin_audits_total(temp_db):
    from bot.database import count_admin_audits
    for _ in range(7):
        _run(_insert_audit(100, "lottery_create"))
    assert _run(count_admin_audits()) == 7


def test_count_admin_audits_filter_by_action(temp_db):
    from bot.database import count_admin_audits
    _run(_insert_audit(100, "lottery_create"))
    _run(_insert_audit(100, "review_approve"))
    _run(_insert_audit(100, "review_approve"))
    assert _run(count_admin_audits(action="review_approve")) == 2
    assert _run(count_admin_audits(action="lottery_create")) == 1
    assert _run(count_admin_audits(action="nonexistent")) == 0


# ============================================================
# 2. _parse_audit_callback callback 解析
# ============================================================


def test_parse_callback_main_entry():
    from bot.handlers.admin_panel import _parse_audit_callback
    assert _parse_audit_callback("dashboard:audit") == (0, None)


def test_parse_callback_page():
    from bot.handlers.admin_panel import _parse_audit_callback
    assert _parse_audit_callback("dashboard:audit:p:3") == (3, None)


def test_parse_callback_filter_page():
    from bot.handlers.admin_panel import _parse_audit_callback
    assert _parse_audit_callback("dashboard:audit:f:review_approve:2") == (
        2, "review_approve",
    )


def test_parse_callback_all_clears_filter():
    from bot.handlers.admin_panel import _parse_audit_callback
    assert _parse_audit_callback("dashboard:audit:all") == (0, None)


def test_parse_callback_negative_page_clamped():
    """负数页码应被 clamp 到 0。"""
    from bot.handlers.admin_panel import _parse_audit_callback
    assert _parse_audit_callback("dashboard:audit:p:-5") == (0, None)


def test_parse_callback_malformed_returns_default():
    from bot.handlers.admin_panel import _parse_audit_callback
    assert _parse_audit_callback("dashboard:audit:p:notanumber") == (0, None)
    assert _parse_audit_callback("dashboard:audit:xyz") == (0, None)


# ============================================================
# 3. dashboard_audit_paginated_kb keyboard
# ============================================================


def test_paginated_kb_first_page_no_prev():
    """第一页不显示上一页按钮。"""
    from bot.keyboards.admin_kb import dashboard_audit_paginated_kb
    kb = dashboard_audit_paginated_kb(page=0, total_pages=5)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    # 不应有"上一页"
    assert "dashboard:audit:p:-1" not in cbs
    # 应有"下一页"
    assert "dashboard:audit:p:1" in cbs


def test_paginated_kb_last_page_no_next():
    """最后一页不显示下一页按钮。"""
    from bot.keyboards.admin_kb import dashboard_audit_paginated_kb
    kb = dashboard_audit_paginated_kb(page=4, total_pages=5)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "dashboard:audit:p:5" not in cbs
    assert "dashboard:audit:p:3" in cbs  # 上一页


def test_paginated_kb_with_filter_uses_filter_callback():
    """有 action_filter 时翻页按钮 callback 应携带 filter。"""
    from bot.keyboards.admin_kb import dashboard_audit_paginated_kb
    kb = dashboard_audit_paginated_kb(
        page=2, total_pages=10, action_filter="review_approve",
    )
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "dashboard:audit:f:review_approve:1" in cbs  # 上一页
    assert "dashboard:audit:f:review_approve:3" in cbs  # 下一页


def test_paginated_kb_filter_button_shown_when_no_filter():
    """无过滤时显示 [🔍 筛选 action] 按钮。"""
    from bot.keyboards.admin_kb import dashboard_audit_paginated_kb
    kb = dashboard_audit_paginated_kb(page=0, total_pages=1)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "dashboard:audit:filter" in cbs


def test_paginated_kb_show_all_button_when_filter_active():
    """有过滤时按钮变为 [🔁 显示全部]。"""
    from bot.keyboards.admin_kb import dashboard_audit_paginated_kb
    kb = dashboard_audit_paginated_kb(
        page=0, total_pages=1, action_filter="review_approve",
    )
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "dashboard:audit:all" in cbs
    assert "dashboard:audit:filter" not in cbs


def test_paginated_kb_has_back_buttons():
    """末行始终含 [🔙 返回看板] + [🏠 主菜单]。"""
    from bot.keyboards.admin_kb import dashboard_audit_paginated_kb
    kb = dashboard_audit_paginated_kb(page=0, total_pages=1)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "dashboard:enter" in cbs
    assert "menu:main" in cbs


# ============================================================
# 4. dashboard_audit_filter_menu_kb 筛选子菜单
# ============================================================


def test_filter_menu_kb_contains_options():
    """筛选子菜单含传入的 action_options。"""
    from bot.keyboards.admin_kb import dashboard_audit_filter_menu_kb
    options = [
        ("review_approve", "✅ 审核通过"),
        ("reimburse_reject", "🛑 驳回报销"),
    ]
    kb = dashboard_audit_filter_menu_kb(options)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "dashboard:audit:f:review_approve:0" in cbs
    assert "dashboard:audit:f:reimburse_reject:0" in cbs


def test_filter_menu_kb_has_back_to_audit():
    from bot.keyboards.admin_kb import dashboard_audit_filter_menu_kb
    kb = dashboard_audit_filter_menu_kb([("x", "X")])
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "dashboard:audit" in cbs


# ============================================================
# 5. cb_dashboard_audit handler 行为
# ============================================================


def test_handler_renders_empty_state(temp_db):
    """无 audit 记录时渲染"暂无记录"。"""
    from bot.handlers.admin_panel import cb_dashboard_audit
    cb = MagicMock()
    cb.data = "dashboard:audit"
    from bot.config import config as _config
    cb.from_user.id = _config.super_admin_id
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    # 绕过 @admin_required 装饰器直接调 wrapped 函数
    _run(cb_dashboard_audit.__wrapped__(cb))
    text = cb.message.edit_text.await_args.kwargs.get("text") or cb.message.edit_text.await_args.args[0]
    assert "暂无记录" in text


def test_handler_renders_pagination_with_data(temp_db):
    """有 15 条记录 → 第 0 页应显示"共 15 条 · 第 1/2 页"。"""
    from bot.handlers.admin_panel import cb_dashboard_audit
    for _ in range(15):
        _run(_insert_audit(100, "lottery_create"))
    cb = MagicMock()
    cb.data = "dashboard:audit"
    from bot.config import config as _config
    cb.from_user.id = _config.super_admin_id
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    # 绕过 @admin_required 装饰器直接调 wrapped 函数
    _run(cb_dashboard_audit.__wrapped__(cb))
    text = cb.message.edit_text.await_args.args[0]
    assert "共 15 条" in text
    assert "第 1/2 页" in text


def test_handler_filter_callback_shows_filter_title(temp_db):
    """带过滤的 callback 渲染应在标题显示"筛选：xxx"。"""
    from bot.handlers.admin_panel import cb_dashboard_audit
    _run(_insert_audit(100, "review_approve"))
    cb = MagicMock()
    cb.data = "dashboard:audit:f:review_approve:0"
    from bot.config import config as _config
    cb.from_user.id = _config.super_admin_id
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    # 绕过 @admin_required 装饰器直接调 wrapped 函数
    _run(cb_dashboard_audit.__wrapped__(cb))
    text = cb.message.edit_text.await_args.args[0]
    assert "筛选" in text
    # _AUDIT_ACTION_LABELS 应把 review_approve → "审核通过"
    assert "审核通过" in text


def test_filter_menu_handler_registered():
    """dashboard:audit:filter 应有独立 handler。"""
    import bot.handlers.admin_panel as mod
    src = _src(mod)
    assert 'F.data == "dashboard:audit:filter"' in src
    assert "async def cb_dashboard_audit_filter(" in src


# ============================================================
# 6. 既有 list_recent_admin_audits 不变（向后兼容）
# ============================================================


def test_legacy_list_recent_unchanged(temp_db):
    """list_recent_admin_audits 行为完全保留（业务保护）。"""
    from bot.database import list_recent_admin_audits
    _run(_insert_audit(100, "lottery_create"))
    rows = _run(list_recent_admin_audits(limit=20))
    assert len(rows) == 1


# ============================================================
# 7. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert MIGRATIONS == []
