"""Sprint UX-5 第一项（UX-5.1）：签到按钮置顶 + 状态文案动态化契约测试。

范围：
    - bot.keyboards.teacher_self_kb.teacher_main_menu_kb 接受 checked_in 参数
      + 签到按钮置顶第一行 + 文案动态切换
    - bot.utils.teacher_status.teacher_checked_in_today 异步 helper
    - bot.handlers.start_router / teacher_self 各 caller 接入

UX 目标（参见 docs/UX-EFFICIENCY-PLAN.md §3.3.A + UX-FEATURE-ITERATION §6 痛点 5/6）：
    - 签到按钮排在主菜单第一行（PLAN §3.5「第一按钮固定为今日签到」）
    - 文案根据当日是否已签到动态切换：
        - 未签到 → "✅ 今日签到"
        - 已签到 → "✅ 今日已签到"
    - 签到成功后立即刷新当前菜单（用户不必离开再回来才能看到状态变化）

约束：
    - 不改 callback_data（teacher_self:checkin / teacher_self:profile / teacher:status 不变）
    - keyboard 仍 sync（接受预查 bool 参数，与项目其它 menu_kb 风格一致）
    - checked_in 默认 False 保留旧文案 "✅ 今日签到"，向后兼容
    - 不引入 schema 迁移
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest  # noqa: F401


# ============ helpers ============


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
# 1. teacher_main_menu_kb 契约
# ============================================================


def test_checkin_button_is_first_row():
    """签到按钮置顶第一行（PLAN §3.5 + UX-5.1）。"""
    from bot.keyboards.teacher_self_kb import teacher_main_menu_kb
    kb = teacher_main_menu_kb()
    # 第一行的第一个按钮应是签到
    first_btn = kb.inline_keyboard[0][0]
    assert first_btn.callback_data == "teacher_self:checkin"
    assert "签到" in first_btn.text


def test_checkin_label_when_not_checked_in():
    """未签到（默认）→ "✅ 今日签到"。"""
    from bot.keyboards.teacher_self_kb import teacher_main_menu_kb
    kb = teacher_main_menu_kb()
    first_btn = kb.inline_keyboard[0][0]
    assert first_btn.text == "✅ 今日签到"


def test_checkin_label_when_checked_in_true():
    """checked_in=True → "✅ 今日已签到"。"""
    from bot.keyboards.teacher_self_kb import teacher_main_menu_kb
    kb = teacher_main_menu_kb(checked_in=True)
    first_btn = kb.inline_keyboard[0][0]
    assert first_btn.text == "✅ 今日已签到"


def test_checkin_label_when_checked_in_false():
    """checked_in=False 显式 → "✅ 今日签到"（与默认行为一致）。"""
    from bot.keyboards.teacher_self_kb import teacher_main_menu_kb
    kb = teacher_main_menu_kb(checked_in=False)
    first_btn = kb.inline_keyboard[0][0]
    assert first_btn.text == "✅ 今日签到"


def test_all_three_buttons_present():
    """主菜单仍有 3 个按钮：签到 / 我的资料 / 今日状态。"""
    from bot.keyboards.teacher_self_kb import teacher_main_menu_kb
    kb = teacher_main_menu_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "teacher_self:checkin" in cbs
    assert "teacher_self:profile" in cbs
    assert "teacher:status" in cbs
    assert len(cbs) == 3


def test_button_callback_data_unchanged():
    """callback_data 与 UX-5.1 前完全一致，确保旧 inline button 不报错。"""
    from bot.keyboards.teacher_self_kb import teacher_main_menu_kb
    for kb in (teacher_main_menu_kb(), teacher_main_menu_kb(checked_in=True)):
        cbs = sorted(b.callback_data for b in _flat_buttons(kb))
        assert cbs == sorted([
            "teacher_self:checkin",
            "teacher_self:profile",
            "teacher:status",
        ])


def test_keyboard_remains_sync():
    """teacher_main_menu_kb 仍是同步函数（与项目其它 menu_kb 风格一致）。"""
    from bot.keyboards.teacher_self_kb import teacher_main_menu_kb
    assert not inspect.iscoroutinefunction(teacher_main_menu_kb)


def test_signature_is_keyword_only_for_checked_in():
    """checked_in 必须 keyword-only（防止位置调用，避免与未来位置参数冲突）。"""
    from bot.keyboards.teacher_self_kb import teacher_main_menu_kb
    sig = inspect.signature(teacher_main_menu_kb)
    p = sig.parameters["checked_in"]
    assert p.kind == inspect.Parameter.KEYWORD_ONLY
    assert p.default is False


# ============================================================
# 2. teacher_checked_in_today helper
# ============================================================


def test_teacher_checked_in_today_returns_false_on_exception(monkeypatch):
    """is_checked_in 抛异常时 helper 应回退 False，不向上抛。"""
    async def _fake_raise(*args, **kwargs):
        raise RuntimeError("db down")
    monkeypatch.setattr(
        "bot.utils.teacher_status.is_checked_in", _fake_raise,
    )
    from bot.utils.teacher_status import teacher_checked_in_today
    result = _run(teacher_checked_in_today(1001))
    assert result is False


def test_teacher_checked_in_today_returns_true_when_db_says_yes(monkeypatch):
    async def _fake_yes(*args, **kwargs):
        return True
    monkeypatch.setattr(
        "bot.utils.teacher_status.is_checked_in", _fake_yes,
    )
    from bot.utils.teacher_status import teacher_checked_in_today
    assert _run(teacher_checked_in_today(1001)) is True


def test_teacher_checked_in_today_passes_today_local_str(monkeypatch):
    """helper 应传 %Y-%m-%d 格式的本地日期给 is_checked_in。"""
    received = {}

    async def _fake_check(user_id, date_str):
        received["user_id"] = user_id
        received["date_str"] = date_str
        return False

    monkeypatch.setattr(
        "bot.utils.teacher_status.is_checked_in", _fake_check,
    )
    from bot.utils.teacher_status import teacher_checked_in_today
    _run(teacher_checked_in_today(1001))
    assert received["user_id"] == 1001
    # date_str 应符合 %Y-%m-%d 格式
    date_str = received["date_str"]
    assert len(date_str) == 10
    assert date_str[4] == "-" and date_str[7] == "-"
    # 年份 4 位数字
    assert date_str[:4].isdigit()


# ============================================================
# 3. 各 caller 接入静态契约
# ============================================================


def test_start_router_passes_checked_in_to_kb():
    import bot.handlers.start_router as mod
    src = _src(mod)
    # 找到老师分支
    idx = src.find("teacher_main_menu_kb(checked_in=")
    assert idx > 0, "start_router 应调 teacher_main_menu_kb(checked_in=...)"
    assert "teacher_checked_in_today" in src


def test_teacher_self_menu_passes_checked_in_to_kb():
    """cb_menu_back（teacher_self.py:215+）应预查并传 checked_in。"""
    import bot.handlers.teacher_self as mod
    src = _src(mod)
    # 应至少 2 处调用 teacher_main_menu_kb(checked_in=)
    assert src.count("teacher_main_menu_kb(checked_in=") >= 2
    assert "teacher_checked_in_today" in src


def test_cb_button_checkin_refreshes_menu_after_success():
    """签到成功后立即 edit_reply_markup 刷新菜单（让按钮立即变成"已签到"）。"""
    import bot.handlers.teacher_self as mod
    src = _src(mod)
    idx = src.find("async def cb_button_checkin(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    # checkin_teacher 成功之后应有 edit_reply_markup + checked_in=True
    success_pos = body.find("checkin_teacher(")
    assert success_pos > 0
    after_success = body[success_pos:]
    assert "edit_reply_markup" in after_success
    assert "checked_in=True" in after_success


def test_cb_button_checkin_refresh_wrapped_in_try():
    """edit_reply_markup 应包 try/except 避免 BadRequest 阻塞 alert。"""
    import bot.handlers.teacher_self as mod
    src = _src(mod)
    idx = src.find("async def cb_button_checkin(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    edit_pos = body.find("edit_reply_markup")
    try_pos = body.rfind("try:", 0, edit_pos)
    # try 应在 edit_reply_markup 之前
    assert 0 < try_pos < edit_pos


def test_cmd_cancel_edit_passes_checked_in():
    """cmd_cancel_edit 也应接入动态文案。"""
    import bot.handlers.teacher_self as mod
    src = _src(mod)
    idx = src.find("async def cmd_cancel_edit(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 2000]
    assert "teacher_main_menu_kb(checked_in=" in body


# ============================================================
# 4. 业务保护
# ============================================================


def test_checkin_callback_still_writes_to_db():
    """cb_button_checkin 仍调 checkin_teacher 写库（业务保护）。"""
    import bot.handlers.teacher_self as mod
    src = _src(mod)
    idx = src.find("async def cb_button_checkin(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "checkin_teacher" in body


def test_checkin_callback_still_checks_deadline():
    """签到截止时间窗口校验仍在（业务保护）。"""
    import bot.handlers.teacher_self as mod
    src = _src(mod)
    idx = src.find("async def cb_button_checkin(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "publish_time" in body
    assert "签到已截止" in body


def test_checkin_callback_still_blocks_duplicate():
    """已签到提示仍在（避免重复签到）。"""
    import bot.handlers.teacher_self as mod
    src = _src(mod)
    idx = src.find("async def cb_button_checkin(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "今日已签到" in body
    assert "is_checked_in" in body


# ============================================================
# 5. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords"}
