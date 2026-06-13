"""Sprint UX-5 第二项（UX-5.2）：审核通过给老师推送通知契约测试。

范围：
    - bot.handlers.admin_review._notify_teacher_approved 新增函数
    - bot.handlers.admin_review.cb_review_approve 接入新通知

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §6 痛点 8 + §11.3）：
    老师改资料后管理员审核驳回会通知（_notify_teacher_rejected 早已存在），
    但审核通过**完全静默** —— 老师只能反复刷面板才知通过。本批新增
    _notify_teacher_approved 与 rejected 对称：

        ✅ 你的资料修改已通过审核
        ━━━━━━━━━━━━━━━
        字段：{label}
        {value_line}                ← photo_file_id 不展示 file_id 字符串
        ━━━━━━━━━━━━━━━
        感谢配合！

约束：
    - 通知失败仅 logger.warning，不影响 audit log 写入与 next 推送
    - 不改 approve_edit_request 业务逻辑
    - 不改 callback_data；不引入 schema 迁移
    - photo_file_id 字段刻意不展示 file_id 字符串（对用户是乱码）
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


# ============================================================
# 1. _notify_teacher_approved 文案契约
# ============================================================


def test_approved_text_for_text_field_contains_label_and_value():
    """文字字段：含 label + 当前生效值。"""
    from bot.handlers.admin_review import _notify_teacher_approved
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(_notify_teacher_approved(bot, 1001, "display_name", "新艺名"))
    bot.send_message.assert_awaited_once()
    text = bot.send_message.await_args.kwargs.get("text", "")
    assert "通过审核" in text
    assert "新艺名" in text
    assert "感谢" in text


def test_approved_text_for_photo_field_hides_file_id():
    """photo_file_id：不应把 file_id 字符串展示给用户（视觉上是乱码）。"""
    from bot.handlers.admin_review import _notify_teacher_approved
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    file_id = "AgACAgIAAxkBAAIBxYZ_FAKE_FILE_ID_XYZ"
    _run(_notify_teacher_approved(bot, 1001, "photo_file_id", file_id))
    text = bot.send_message.await_args.kwargs.get("text", "")
    assert file_id not in text
    assert "新图片" in text or "图片" in text


def test_approved_text_for_empty_value_shows_placeholder():
    """new_value 为空（清空字段）→ 显示「（空）」占位，而不是 None / 空白。"""
    from bot.handlers.admin_review import _notify_teacher_approved
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(_notify_teacher_approved(bot, 1001, "button_text", None))
    text = bot.send_message.await_args.kwargs.get("text", "")
    assert "（空）" in text
    assert "None" not in text


def test_approved_signature_mirrors_rejected():
    """approved 与 rejected 的位置参数前 4 个对齐：bot, teacher_id, field_name, new_value。"""
    from bot.handlers.admin_review import (
        _notify_teacher_approved, _notify_teacher_rejected,
    )
    sig_a = inspect.signature(_notify_teacher_approved)
    sig_r = inspect.signature(_notify_teacher_rejected)
    params_a = list(sig_a.parameters)
    params_r = list(sig_r.parameters)
    assert params_a == ["bot", "teacher_id", "field_name", "new_value"]
    # rejected 在 4 个共享参数后多 reason
    assert params_r[:4] == params_a


# ============================================================
# 2. 通知失败容错
# ============================================================


def test_approved_notification_swallows_exceptions():
    """bot.send_message 抛异常时 _notify_teacher_approved 不应向上抛。"""
    from bot.handlers.admin_review import _notify_teacher_approved

    class BoomError(Exception):
        pass

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=BoomError("blocked"))
    # 不抛
    _run(_notify_teacher_approved(bot, 1001, "display_name", "x"))


# ============================================================
# 3. cb_review_approve 接入静态契约
# ============================================================


def test_approve_handler_calls_notify_approved():
    """cb_review_approve 必须调用 _notify_teacher_approved。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    idx = src.find("async def cb_review_approve(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "_notify_teacher_approved" in body


def test_notify_approved_called_after_audit_log():
    """通知必须在 audit log 写入之后；如果通知失败也不应丢失 audit。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    idx = src.find("async def cb_review_approve(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    audit_pos = body.find('action="review_approve"')
    notify_pos = body.find("_notify_teacher_approved")
    assert 0 < audit_pos < notify_pos, (
        "通知应在 audit log 写入之后调用，确保 audit 永远先写入"
    )


def test_notify_approved_only_when_approved_dict_truthy():
    """approved=None（极端并发场景）时不应调用通知，避免 KeyError。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    idx = src.find("async def cb_review_approve(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    # 应有 if approved: 守卫
    notify_pos = body.find("_notify_teacher_approved")
    guard_pos = body.rfind("if approved:", 0, notify_pos)
    assert 0 < guard_pos < notify_pos, (
        "_notify_teacher_approved 调用应在 'if approved:' 守卫内"
    )


def test_approve_handler_still_writes_audit_log():
    """业务保护：UX-5.2 不动 audit log 写入契约。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    idx = src.find("async def cb_review_approve(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "log_admin_audit" in body
    assert 'action="review_approve"' in body


def test_approve_handler_still_calls_approve_edit_request():
    """业务保护：仍调 approve_edit_request 切换状态。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    idx = src.find("async def cb_review_approve(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "approve_edit_request" in body


def test_approve_handler_still_answers_callback():
    """业务保护：仍调 callback.answer 通知超管。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    idx = src.find("async def cb_review_approve(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert 'callback.answer("✅ 已通过")' in body


# ============================================================
# 4. _notify_teacher_rejected 行为保护
# ============================================================


def test_notify_teacher_rejected_still_exists():
    """UX-5.2 不应误删 _notify_teacher_rejected。"""
    from bot.handlers.admin_review import _notify_teacher_rejected
    assert callable(_notify_teacher_rejected)


def test_notify_teacher_rejected_text_unchanged():
    """旧驳回通知文案保留 ❌ + "已被驳回" 关键标识。"""
    from bot.handlers.admin_review import _notify_teacher_rejected
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    _run(_notify_teacher_rejected(bot, 1001, "display_name", "x", "证据不足"))
    text = bot.send_message.await_args.kwargs.get("text", "")
    assert "❌" in text
    assert "驳回" in text
    assert "证据不足" in text


# ============================================================
# 5. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    from _migration_baseline import EXPECTED_MIGRATION_VERSIONS
    assert {m.version for m in MIGRATIONS} == EXPECTED_MIGRATION_VERSIONS
