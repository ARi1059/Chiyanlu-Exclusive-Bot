"""Sprint UX-7 第一项（UX-7.1）：审核 claim 内存锁契约测试。

范围：
    - bot.utils.review_claim 内存 TTL 锁（try_claim / force_claim / release_claim / get_claim）
    - bot.keyboards.admin_kb.review_claim_conflict_kb 冲突页 keyboard
    - bot.handlers.admin_review.cb_review_force_claim 强制接管 handler
    - bot.handlers.admin_review._show_request_at_index 进入前 try_claim
    - bot.handlers.admin_review.cb_review_approve / _perform_reject_from_message
      处理成功后 release_claim
    - bot.handlers.rreview_admin.cb_rreview_force_claim 同
    - bot.handlers.rreview_admin._send_review_at_index 同（含 viewer_admin_id 路径）
    - bot.handlers.rreview_admin._do_approve_inner / _do_reject release

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §1 C5 + §7.2 痛点 3 + §11.3）：
    并发审核时，第二个超管进入同一条审核会渲染"冲突页"而非详情；
    冲突页含 [🛡 强制接管] + [🔙 返回审核处理] 两个出口。
    强制接管会写 audit log（含 previous_holder）。

约束：
    - 单副本内存 dict + 5 分钟 TTL；多副本部署本锁失效（已在 module docstring 说明）
    - 不引入 schema 迁移（仅扩展 audit log 用既有表）
    - 不改既有 callback_data；新增 review:force_claim:* / rreview:force_claim:*
"""
from __future__ import annotations

import inspect
import time
from unittest.mock import AsyncMock, MagicMock

import pytest


# ============ helpers ============


@pytest.fixture(autouse=True)
def _reset_claims():
    """每个测试前后清空锁状态，避免测试间互相污染。"""
    from bot.utils.review_claim import reset_for_test
    reset_for_test()
    yield
    reset_for_test()


def _src(module) -> str:
    return inspect.getsource(module)


def _flat_buttons(kb) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            out.append(btn)
    return out


# ============================================================
# 1. review_claim 核心 API
# ============================================================


def test_get_claim_none_when_empty():
    from bot.utils.review_claim import get_claim
    assert get_claim("teacher_review", 42) is None


def test_try_claim_success_when_no_lock():
    from bot.utils.review_claim import try_claim, get_claim
    ok, existing = try_claim("teacher_review", 42, admin_id=100)
    assert ok is True
    assert existing is None
    info = get_claim("teacher_review", 42)
    assert info is not None
    assert info.admin_id == 100
    assert info.target_id == "42"


def test_try_claim_blocked_by_other_admin():
    from bot.utils.review_claim import try_claim
    ok1, _ = try_claim("teacher_review", 42, admin_id=100)
    ok2, existing = try_claim("teacher_review", 42, admin_id=200)
    assert ok1 is True
    assert ok2 is False
    assert existing is not None
    assert existing.admin_id == 100


def test_try_claim_same_admin_refreshes_timestamp():
    """同一 admin 重复 claim 应成功（刷新时间戳）。"""
    from bot.utils.review_claim import try_claim, get_claim
    now = time.time()
    ok1, _ = try_claim("teacher_review", 42, 100, now=now)
    info1 = get_claim("teacher_review", 42, now=now)
    ok2, existing = try_claim("teacher_review", 42, 100, now=now + 10)
    info2 = get_claim("teacher_review", 42, now=now + 10)
    assert ok1 is True and ok2 is True
    assert existing is None
    assert info2.acquired_at > info1.acquired_at


def test_try_claim_after_ttl_expired():
    """锁过期后另一个 admin 可成功 claim。"""
    from bot.utils.review_claim import try_claim, CLAIM_TTL_SECONDS
    now = time.time()
    try_claim("teacher_review", 42, 100, now=now)
    # 6 分钟后
    ok, existing = try_claim(
        "teacher_review", 42, 200, now=now + CLAIM_TTL_SECONDS + 1,
    )
    assert ok is True
    assert existing is None


def test_force_claim_overrides_existing():
    from bot.utils.review_claim import try_claim, force_claim, get_claim
    try_claim("teacher_review", 42, 100)
    force_claim("teacher_review", 42, 200)
    info = get_claim("teacher_review", 42)
    assert info.admin_id == 200


def test_release_claim_by_owner():
    from bot.utils.review_claim import try_claim, release_claim, get_claim
    try_claim("teacher_review", 42, 100)
    assert release_claim("teacher_review", 42, 100) is True
    assert get_claim("teacher_review", 42) is None


def test_release_claim_by_non_owner_returns_false():
    """非持有者尝试 release → 不应释放（防止误释放）。"""
    from bot.utils.review_claim import try_claim, release_claim, get_claim
    try_claim("teacher_review", 42, 100)
    assert release_claim("teacher_review", 42, 999) is False
    assert get_claim("teacher_review", 42) is not None  # 仍在


def test_release_claim_when_no_lock_returns_false():
    from bot.utils.review_claim import release_claim
    assert release_claim("teacher_review", 42, 100) is False


def test_claim_admin_id_zero_skipped():
    """admin_id=0（历史 placeholder）→ try_claim 视为成功但不写入锁。"""
    from bot.utils.review_claim import try_claim, get_claim
    ok, existing = try_claim("teacher_review", 42, 0)
    assert ok is True
    assert get_claim("teacher_review", 42) is None


def test_claim_namespaces_isolated():
    """不同 kind 的相同 target_id 不应互相干扰。"""
    from bot.utils.review_claim import try_claim
    ok1, _ = try_claim("edit_request", 42, 100)
    ok2, _ = try_claim("teacher_review", 42, 200)
    assert ok1 is True and ok2 is True


def test_get_claim_auto_cleans_expired():
    """get_claim 读到过期锁时应自动清理。"""
    from bot.utils.review_claim import try_claim, get_claim, CLAIM_TTL_SECONDS
    now = time.time()
    try_claim("teacher_review", 42, 100, now=now)
    assert get_claim("teacher_review", 42, now=now + CLAIM_TTL_SECONDS + 1) is None


# ============================================================
# 2. review_claim_conflict_kb 冲突页 keyboard
# ============================================================


def test_conflict_kb_for_edit_request():
    from bot.keyboards.admin_kb import review_claim_conflict_kb
    kb = review_claim_conflict_kb("edit_request", 42)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "review:force_claim:42" in cbs
    assert "admin:review_tasks" in cbs


def test_conflict_kb_for_teacher_review():
    from bot.keyboards.admin_kb import review_claim_conflict_kb
    kb = review_claim_conflict_kb("teacher_review", 99)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "rreview:force_claim:99" in cbs
    assert "admin:review_tasks" in cbs


def test_conflict_kb_unknown_kind_safe_fallback():
    """未知 kind 应回退到仅返回按钮（不出现 force_claim 死链）。"""
    from bot.keyboards.admin_kb import review_claim_conflict_kb
    kb = review_claim_conflict_kb("unknown_kind", 1)
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert all("force_claim" not in c for c in cbs)
    assert "admin:review_tasks" in cbs


# ============================================================
# 3. admin_review 接入静态契约
# ============================================================


def test_show_request_at_index_tries_claim():
    """_show_request_at_index 进入前应 try_claim。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    idx = src.find("async def _show_request_at_index(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert "try_claim" in body
    # 渲染冲突的 helper 也应被调用
    assert "_render_claim_conflict" in body


def test_force_claim_handler_registered():
    import bot.handlers.admin_review as mod
    src = _src(mod)
    assert 'F.data.startswith("review:force_claim:")' in src


def test_force_claim_handler_writes_audit_with_previous_holder():
    import bot.handlers.admin_review as mod
    src = _src(mod)
    idx = src.find("async def cb_review_force_claim(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "force_claim" in body
    assert 'action="review_force_claim"' in body
    assert "previous_holder" in body


def test_cb_review_approve_releases_claim():
    import bot.handlers.admin_review as mod
    src = _src(mod)
    idx = src.find("async def cb_review_approve(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "release_claim" in body


def test_perform_reject_releases_claim():
    import bot.handlers.admin_review as mod
    src = _src(mod)
    idx = src.find("async def _perform_reject_from_message(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "release_claim" in body


# ============================================================
# 4. rreview_admin 接入静态契约
# ============================================================


def test_send_review_at_index_tries_claim_with_viewer_admin_id():
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    idx = src.find("async def _send_review_at_index(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert "try_claim" in body
    assert "_render_claim_conflict_message" in body


def test_rreview_force_claim_handler_registered():
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    assert 'F.data.startswith("rreview:force_claim:")' in src


def test_rreview_force_claim_handler_writes_audit():
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    idx = src.find("async def cb_rreview_force_claim(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "force_claim" in body
    assert 'action="rreview_force_claim"' in body


def test_do_approve_inner_releases_claim():
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    idx = src.find("async def _do_approve_inner(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 12000]
    assert "release_claim" in body


def test_do_reject_releases_claim():
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    idx = src.find("async def _do_reject(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert "release_claim" in body


# ============================================================
# 5. handler 行为：冲突场景
# ============================================================


def test_show_request_renders_conflict_page_when_locked_by_other():
    """模拟：管理员 A claim 后，管理员 B 进入应渲染冲突页。"""
    import asyncio
    from bot.handlers.admin_review import _show_request_at_index
    from bot.utils.review_claim import try_claim

    # admin A=999 持有锁
    try_claim("edit_request", 42, 999)

    pending = [{
        "id": 42, "teacher_id": 99, "teacher_display_name": "A",
        "field_name": "display_name", "old_value": "old", "new_value": "new",
        "created_at": "2026-05-20 10:00:00",
    }]
    cb = MagicMock()
    cb.from_user.id = 1001  # admin B
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    asyncio.run(_show_request_at_index(cb, pending, 0))
    # 渲染的应是冲突页（含 #999）
    text = cb.message.edit_text.await_args.args[0]
    assert "审核冲突" in text
    assert "#999" in text


def test_show_request_renders_detail_when_self_holds_lock():
    """同一管理员重复进入应正常渲染详情（不显示冲突页）。"""
    import asyncio
    from bot.handlers.admin_review import _show_request_at_index
    from bot.utils.review_claim import try_claim

    try_claim("edit_request", 42, 1001)  # 自己

    pending = [{
        "id": 42, "teacher_id": 99, "teacher_display_name": "A",
        "field_name": "display_name", "old_value": "old", "new_value": "new",
        "created_at": "2026-05-20 10:00:00",
    }]
    cb = MagicMock()
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    cb.answer = AsyncMock(return_value=None)
    asyncio.run(_show_request_at_index(cb, pending, 0))
    text = cb.message.edit_text.await_args.args[0]
    # 应是详情页（含字段名"display_name"对应的中文 label）
    assert "审核冲突" not in text
    assert "待审核" in text


# ============================================================
# 6. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable", "20260613_001_teacher_is_deleted", "20260613_002_remove_quick_entry_keywords"}
