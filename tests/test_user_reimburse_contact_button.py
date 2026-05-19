"""Sprint UX-6 第四项（UX-6.4）：用户「我的报销」页面附"联系客服申诉"按钮契约测试。

范围：
    - bot.utils.reimburse_notify.get_reimburse_contact_url   公共 helper（UX-4.1 + UX-6.4 共用）
    - bot.utils.reimburse_notify.build_user_reimburse_reject_kb 重构为复用 helper（行为不变）
    - bot.keyboards.user_kb.user_reimburse_menu_kb 增 contact_url 参数
    - bot.keyboards.user_kb.user_reimburse_pagination_kb 增 contact_url 参数
    - bot.handlers.user_reimburse.cb_user_reimburse 接入
    - bot.handlers.user_reimburse.cb_user_reimburse_list 接入

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §1 C1 + §4.3.5 + §11.3）：
    用户在私聊主动进入「我的报销」想申诉时，找不到客服入口；本批让两个页面
    （总览 + 明细分页）都展示 [📩 联系客服申诉] URL 按钮，仅当 config 配置了 url 时显示。

设计决策（与 §11.3 范围里"rejected 记录后"的差异）：
    按钮**始终显示**（前提：contact_url 已配置），不限制只有"有 rejected 记录"才显示。
    理由：
      1. "联系客服"是通用咨询入口，不仅用于驳回申诉（"我什么时候审？"等）
      2. 减少 DB 查询和状态判断复杂度
      3. 与 UX-4.1 通知 keyboard 风格一致（未基于 rejected 状态做条件）
    contact_url 未配置时按钮不显示，保护避免死链。

约束：
    - 不改 callback_data；user:reimburse / user:reimburse:list / user:main 早已存在
    - 不引入 schema 迁移
    - 不动业务逻辑（report stats / 分页 / status_label）
    - UX-4.1 build_user_reimburse_reject_kb 行为不变（重构通过 helper）
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
        prefix=f"test_reim_ctb_{uuid.uuid4().hex}_", suffix=".db",
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


# ============================================================
# 1. get_reimburse_contact_url helper（公共）
# ============================================================


def test_contact_url_returns_none_when_unconfigured(temp_db):
    """config 双空 → 返回 None。"""
    from bot.utils.reimburse_notify import get_reimburse_contact_url
    assert _run(get_reimburse_contact_url()) is None


def test_contact_url_falls_back_to_lottery(temp_db):
    """lottery_contact_url 配置 → fallback 命中。"""
    from bot.database import set_config
    from bot.utils.reimburse_notify import get_reimburse_contact_url
    _run(set_config("lottery_contact_url", "https://t.me/L"))
    assert _run(get_reimburse_contact_url()) == "https://t.me/L"


def test_contact_url_prefers_reimburse_over_lottery(temp_db):
    """两个都配 → reimburse_contact_url 优先。"""
    from bot.database import set_config
    from bot.utils.reimburse_notify import get_reimburse_contact_url
    _run(set_config("lottery_contact_url", "https://t.me/L"))
    _run(set_config("reimburse_contact_url", "https://t.me/R"))
    assert _run(get_reimburse_contact_url()) == "https://t.me/R"


def test_contact_url_blank_string_treated_as_unconfigured(temp_db):
    """空白字符串视为未配，fallback 到下一级。"""
    from bot.database import set_config
    from bot.utils.reimburse_notify import get_reimburse_contact_url
    _run(set_config("reimburse_contact_url", "   "))
    _run(set_config("lottery_contact_url", "https://t.me/L"))
    assert _run(get_reimburse_contact_url()) == "https://t.me/L"


def test_contact_url_both_blank_returns_none(temp_db):
    from bot.database import set_config
    from bot.utils.reimburse_notify import get_reimburse_contact_url
    _run(set_config("reimburse_contact_url", "   "))
    _run(set_config("lottery_contact_url", ""))
    assert _run(get_reimburse_contact_url()) is None


# ============================================================
# 2. user_reimburse_menu_kb 接受 contact_url
# ============================================================


def test_menu_kb_without_contact_url_has_no_appeal_button():
    """contact_url=None → 不应出现 URL 按钮。"""
    from bot.keyboards.user_kb import user_reimburse_menu_kb
    kb = user_reimburse_menu_kb()
    btns = _flat_buttons(kb)
    assert all(b.url is None for b in btns)
    cbs = [b.callback_data for b in btns]
    assert "user:reimburse:list" in cbs
    assert "user:main" in cbs


def test_menu_kb_with_contact_url_adds_appeal_button():
    from bot.keyboards.user_kb import user_reimburse_menu_kb
    kb = user_reimburse_menu_kb(contact_url="https://t.me/admin")
    btns = _flat_buttons(kb)
    url_btns = [b for b in btns if b.url]
    assert len(url_btns) == 1
    assert url_btns[0].url == "https://t.me/admin"
    assert "申诉" in url_btns[0].text or "客服" in url_btns[0].text


def test_menu_kb_order_appeal_before_back():
    """申诉按钮应在「返回主菜单」之前（位置更显眼）。"""
    from bot.keyboards.user_kb import user_reimburse_menu_kb
    kb = user_reimburse_menu_kb(contact_url="https://t.me/admin")
    # 找按钮的 row 索引
    rows = kb.inline_keyboard
    url_row = next(i for i, row in enumerate(rows) if any(b.url for b in row))
    main_row = next(
        i for i, row in enumerate(rows)
        if any(b.callback_data == "user:main" for b in row)
    )
    assert url_row < main_row


def test_menu_kb_keyword_only_contact_url():
    """contact_url 必须 keyword-only，防止位置调用混淆。"""
    from bot.keyboards.user_kb import user_reimburse_menu_kb
    sig = inspect.signature(user_reimburse_menu_kb)
    p = sig.parameters["contact_url"]
    assert p.kind == inspect.Parameter.KEYWORD_ONLY
    assert p.default is None


# ============================================================
# 3. user_reimburse_pagination_kb 接受 contact_url
# ============================================================


def test_pagination_kb_without_contact_url_no_appeal_button():
    from bot.keyboards.user_kb import user_reimburse_pagination_kb
    kb = user_reimburse_pagination_kb(0, 2)
    btns = _flat_buttons(kb)
    assert all(b.url is None for b in btns)


def test_pagination_kb_with_contact_url_adds_appeal_button():
    from bot.keyboards.user_kb import user_reimburse_pagination_kb
    kb = user_reimburse_pagination_kb(0, 2, contact_url="https://t.me/admin")
    btns = _flat_buttons(kb)
    url_btns = [b for b in btns if b.url]
    assert len(url_btns) == 1
    assert url_btns[0].url == "https://t.me/admin"


def test_pagination_kb_nav_buttons_still_work_with_contact():
    """业务保护：分页 prev / next 按钮仍生效。"""
    from bot.keyboards.user_kb import user_reimburse_pagination_kb
    kb = user_reimburse_pagination_kb(1, 5, contact_url="https://t.me/admin")
    cbs = [b.callback_data for b in _flat_buttons(kb) if b.callback_data]
    assert "user:reimburse:list:0" in cbs  # 上一页
    assert "user:reimburse:list:2" in cbs  # 下一页
    assert "user:reimburse" in cbs  # 返回报销


# ============================================================
# 4. handler 接入静态契约
# ============================================================


def test_cb_user_reimburse_uses_contact_url_helper():
    import bot.handlers.user_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_user_reimburse(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "get_reimburse_contact_url" in body
    assert "contact_url=contact_url" in body


def test_cb_user_reimburse_list_uses_contact_url_helper():
    import bot.handlers.user_reimburse as mod
    src = _src(mod)
    idx = src.find("async def cb_user_reimburse_list(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert "get_reimburse_contact_url" in body
    assert "contact_url=contact_url" in body


# ============================================================
# 5. UX-4.1 reject kb 行为通过 helper 重构后保持不变
# ============================================================


def test_reject_kb_uses_helper(temp_db):
    """build_user_reimburse_reject_kb 应通过 get_reimburse_contact_url 解析 URL。"""
    import bot.utils.reimburse_notify as mod
    src = _src(mod)
    idx = src.find("async def build_user_reimburse_reject_kb(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "get_reimburse_contact_url" in body


def test_reject_kb_behavior_unchanged_when_no_config(temp_db):
    """config 双空时 reject kb 仍只显示 [📋 我的报销]（与 UX-4.1 既有行为一致）。"""
    from bot.utils.reimburse_notify import build_user_reimburse_reject_kb
    kb = _run(build_user_reimburse_reject_kb())
    btns = _flat_buttons(kb)
    assert len(btns) == 1
    assert btns[0].callback_data == "user:reimburse"


def test_reject_kb_behavior_unchanged_with_config(temp_db):
    """config 配置 lottery_contact_url 时 reject kb 仍显示申诉 + 我的报销两个按钮。"""
    from bot.database import set_config
    from bot.utils.reimburse_notify import build_user_reimburse_reject_kb
    _run(set_config("lottery_contact_url", "https://t.me/L"))
    kb = _run(build_user_reimburse_reject_kb())
    btns = _flat_buttons(kb)
    assert len(btns) == 2
    assert btns[0].url == "https://t.me/L"
    assert btns[1].callback_data == "user:reimburse"


# ============================================================
# 6. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert MIGRATIONS == []
