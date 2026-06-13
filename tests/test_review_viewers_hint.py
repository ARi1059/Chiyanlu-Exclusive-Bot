"""Sprint UX-7 第四项（UX-7.4）：审核详情页"近期查看者"提示契约测试。

范围：
    - bot.database.list_recent_target_viewers 新查询（按 target + action + 时间窗）
    - bot.utils.review_viewers_hint.format_recent_viewers_hint 文案 helper
    - bot.handlers.admin_review._format_request_detail viewers_hint 注入 + handler 内查询/audit
    - bot.handlers.rreview_admin._render_review_text viewers_hint 注入 +
      _send_review_at_index 修复 admin_id=0 placeholder + viewer hint 接入

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §1 C5 + §7.2 痛点 2-3-15 + §11.3）：
    并发审核场景下，管理员进入同一条审核时被动报"已被处理"；本批让详情页
    顶部主动提示 "⚠️ 管理员 #123 1 分钟前查看过此条"，让超管协作不"撞车"。

修复：
    - rreview_admin.py:678 audit log placeholder admin_id=0 → 改为真实 admin_id
    - 同步给 admin_review.py 也写 review_view audit（之前无）

约束：
    - 不改任何 callback_data
    - 不引入 schema 迁移（仅查既有 admin_audit_logs 表）
    - 不动 entry/draw/approve/reject 业务逻辑
    - 渲染前查询 + audit 写入 包 try/except，单点失败不阻塞详情页
"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


# ============ helpers ============


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_vh_{uuid.uuid4().hex}_", suffix=".db",
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


# ============================================================
# 1. format_recent_viewers_hint 文案 helper
# ============================================================


def test_hint_returns_none_for_empty_list():
    from bot.utils.review_viewers_hint import format_recent_viewers_hint
    assert format_recent_viewers_hint([]) is None


def test_hint_skips_admin_id_zero():
    """admin_id=0 是历史 placeholder，应被跳过。"""
    from bot.utils.review_viewers_hint import format_recent_viewers_hint
    now = datetime.now(timezone.utc)
    one_min_ago = (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    result = format_recent_viewers_hint(
        [{"admin_id": 0, "created_at": one_min_ago}], now=now,
    )
    assert result is None


def test_hint_single_admin_relative_time():
    from bot.utils.review_viewers_hint import format_recent_viewers_hint
    now = datetime.now(timezone.utc)
    one_min_ago = (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    result = format_recent_viewers_hint(
        [{"admin_id": 123, "created_at": one_min_ago}], now=now,
    )
    assert result is not None
    assert "#123" in result
    assert "1 分钟前" in result
    assert "查看过此条" in result


def test_hint_seconds_resolution():
    """< 60 秒应显示秒数。"""
    from bot.utils.review_viewers_hint import format_recent_viewers_hint
    now = datetime.now(timezone.utc)
    ten_sec_ago = (now - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
    result = format_recent_viewers_hint(
        [{"admin_id": 1, "created_at": ten_sec_ago}], now=now,
    )
    assert "10 秒前" in result


def test_hint_just_now_for_very_recent():
    """< 5 秒应显示"刚刚"。"""
    from bot.utils.review_viewers_hint import format_recent_viewers_hint
    now = datetime.now(timezone.utc)
    two_sec_ago = (now - timedelta(seconds=2)).strftime("%Y-%m-%d %H:%M:%S")
    result = format_recent_viewers_hint(
        [{"admin_id": 1, "created_at": two_sec_ago}], now=now,
    )
    assert "刚刚" in result


def test_hint_multiple_admins_joined():
    """多个 admin 用 ' / ' 拼接（最多 max_show 个）。"""
    from bot.utils.review_viewers_hint import format_recent_viewers_hint
    now = datetime.now(timezone.utc)
    t1 = (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    t2 = (now - timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")
    result = format_recent_viewers_hint(
        [
            {"admin_id": 1, "created_at": t1},
            {"admin_id": 2, "created_at": t2},
        ], now=now,
    )
    assert "#1" in result and "#2" in result
    assert " / " in result


def test_hint_truncates_with_etc_when_exceeds_max():
    """超过 max_show 时显示"等 N 人"。"""
    from bot.utils.review_viewers_hint import format_recent_viewers_hint
    now = datetime.now(timezone.utc)
    t = (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    rows = [{"admin_id": i, "created_at": t} for i in range(1, 6)]
    result = format_recent_viewers_hint(rows, now=now, max_show=2)
    assert "#1" in result and "#2" in result
    assert "#3" not in result
    assert "等 5 人" in result


def test_hint_warning_emoji():
    """提示行必须以 ⚠️ 开头（视觉警示）。"""
    from bot.utils.review_viewers_hint import format_recent_viewers_hint
    now = datetime.now(timezone.utc)
    t = (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    result = format_recent_viewers_hint([{"admin_id": 1, "created_at": t}], now=now)
    assert result.startswith("⚠️")


# ============================================================
# 2. list_recent_target_viewers DB 查询
# ============================================================


async def _insert_audit(admin_id, action, target_type, target_id, *, ts_offset_sec=0):
    """便利：插入 audit log，可指定相对时间偏移。"""
    from bot.database import get_db
    db = await get_db()
    try:
        if ts_offset_sec == 0:
            sql = (
                "INSERT INTO admin_audit_logs (admin_id, action, target_type, target_id) "
                "VALUES (?, ?, ?, ?)"
            )
            args = (admin_id, action, target_type, str(target_id))
        else:
            sql = (
                "INSERT INTO admin_audit_logs "
                "(admin_id, action, target_type, target_id, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now', ?))"
            )
            args = (admin_id, action, target_type, str(target_id), f"{ts_offset_sec} seconds")
        await db.execute(sql, args)
        await db.commit()
    finally:
        await db.close()


def test_list_viewers_empty(temp_db):
    from bot.database import list_recent_target_viewers
    rows = _run(list_recent_target_viewers(
        "teacher_review", 42, action="rreview_view",
    ))
    assert rows == []


def test_list_viewers_returns_recent_within_window(temp_db):
    """5 分钟内 + 匹配 target → 返回；超出窗口的不返回。"""
    from bot.database import list_recent_target_viewers
    _run(_insert_audit(100, "rreview_view", "teacher_review", 42, ts_offset_sec=-60))
    # 10 分钟前的不应进入 5 分钟窗口
    _run(_insert_audit(200, "rreview_view", "teacher_review", 42, ts_offset_sec=-600))
    rows = _run(list_recent_target_viewers(
        "teacher_review", 42, action="rreview_view", since_seconds=300,
    ))
    ids = [r["admin_id"] for r in rows]
    assert 100 in ids
    assert 200 not in ids


def test_list_viewers_filters_by_target_id(temp_db):
    """不同 target_id 不混。"""
    from bot.database import list_recent_target_viewers
    _run(_insert_audit(100, "rreview_view", "teacher_review", 42))
    _run(_insert_audit(101, "rreview_view", "teacher_review", 999))
    rows = _run(list_recent_target_viewers(
        "teacher_review", 42, action="rreview_view",
    ))
    ids = [r["admin_id"] for r in rows]
    assert ids == [100]


def test_list_viewers_filters_by_action(temp_db):
    """不同 action 不混（review_view vs rreview_view 应隔离）。"""
    from bot.database import list_recent_target_viewers
    _run(_insert_audit(100, "rreview_view", "teacher_review", 42))
    _run(_insert_audit(101, "review_approve", "teacher_review", 42))
    rows = _run(list_recent_target_viewers(
        "teacher_review", 42, action="rreview_view",
    ))
    ids = [r["admin_id"] for r in rows]
    assert ids == [100]


def test_list_viewers_excludes_self(temp_db):
    """exclude_admin_id 排除自己。"""
    from bot.database import list_recent_target_viewers
    _run(_insert_audit(100, "rreview_view", "teacher_review", 42))
    _run(_insert_audit(200, "rreview_view", "teacher_review", 42))
    rows = _run(list_recent_target_viewers(
        "teacher_review", 42, action="rreview_view", exclude_admin_id=100,
    ))
    ids = [r["admin_id"] for r in rows]
    assert ids == [200]


def test_list_viewers_skips_admin_id_zero(temp_db):
    """admin_id=0（旧 placeholder）不应被计入。"""
    from bot.database import list_recent_target_viewers
    _run(_insert_audit(0, "rreview_view", "teacher_review", 42))
    _run(_insert_audit(123, "rreview_view", "teacher_review", 42))
    rows = _run(list_recent_target_viewers(
        "teacher_review", 42, action="rreview_view",
    ))
    ids = [r["admin_id"] for r in rows]
    assert ids == [123]


def test_list_viewers_dedupes_admin_with_max_created_at(temp_db):
    """同一 admin 多次查看，取最新时间一条；不重复显示。"""
    from bot.database import list_recent_target_viewers
    _run(_insert_audit(100, "rreview_view", "teacher_review", 42, ts_offset_sec=-180))
    _run(_insert_audit(100, "rreview_view", "teacher_review", 42, ts_offset_sec=-60))
    rows = _run(list_recent_target_viewers(
        "teacher_review", 42, action="rreview_view",
    ))
    assert len([r for r in rows if r["admin_id"] == 100]) == 1


# ============================================================
# 3. admin_review _format_request_detail + handler 接入
# ============================================================


def test_admin_review_detail_renders_viewer_hint():
    """_format_request_detail viewers_hint 参数被渲染到顶部。"""
    from bot.handlers.admin_review import _format_request_detail
    req = {
        "id": 1, "teacher_id": 99, "teacher_display_name": "A",
        "field_name": "display_name", "old_value": "old", "new_value": "new",
        "created_at": "2026-05-20 10:00:00",
    }
    text = _format_request_detail(
        req, 1, 1, viewers_hint="⚠️ 管理员 #123 1 分钟前 查看过此条",
    )
    assert "⚠️ 管理员 #123" in text
    # 标题行应仍在
    assert "待审核 [1/1]" in text


def test_admin_review_detail_without_hint_unchanged():
    """viewers_hint=None 时渲染保持原契约（无 ⚠️ 头部）。"""
    from bot.handlers.admin_review import _format_request_detail
    req = {
        "id": 1, "teacher_id": 99, "teacher_display_name": "A",
        "field_name": "display_name", "old_value": "old", "new_value": "new",
        "created_at": "2026-05-20 10:00:00",
    }
    text = _format_request_detail(req, 1, 1)
    assert "⚠️" not in text
    assert "待审核 [1/1]" in text


def test_show_request_at_index_logs_view_audit():
    """_show_request_at_index 应用真实 admin_id 写入 review_view audit。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    idx = src.find("async def _show_request_at_index(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert 'action="review_view"' in body
    assert "log_admin_audit" in body
    # 应使用 admin_id 而非 placeholder 0
    assert "admin_id=admin_id" in body or "admin_id=callback.from_user.id" in body


def test_show_request_at_index_calls_viewer_helpers():
    """_show_request_at_index 应调 list_recent_target_viewers + format_recent_viewers_hint。"""
    import bot.handlers.admin_review as mod
    src = _src(mod)
    idx = src.find("async def _show_request_at_index(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    assert "list_recent_target_viewers" in body
    assert "format_recent_viewers_hint" in body


# ============================================================
# 4. rreview_admin _render_review_text + _send_review_at_index 修复
# ============================================================


def test_rreview_render_text_renders_viewer_hint():
    from bot.handlers.rreview_admin import _render_review_text
    review = {
        "id": 1, "teacher_id": 99, "user_id": 1001,
        "rating": "positive", "overall_score": 9,
        "score_humanphoto": 9, "score_appearance": 9, "score_body": 9,
        "score_service": 9, "score_attitude": 9, "score_environment": 9,
        "summary": "good", "anonymous": 0, "created_at": "2026-05-20 10:00:00",
    }
    teacher = {"display_name": "T"}
    text = _render_review_text(
        review, teacher, 0, 1,
        viewers_hint="⚠️ 管理员 #456 30 秒前 查看过此条",
    )
    assert "⚠️ 管理员 #456" in text
    assert "[报告审核 1/1]" in text


def test_rreview_render_text_without_hint_unchanged():
    from bot.handlers.rreview_admin import _render_review_text
    review = {
        "id": 1, "teacher_id": 99, "user_id": 1001,
        "rating": "positive", "overall_score": 9,
        "score_humanphoto": 9, "score_appearance": 9, "score_body": 9,
        "score_service": 9, "score_attitude": 9, "score_environment": 9,
        "summary": "good", "anonymous": 0, "created_at": "2026-05-20 10:00:00",
    }
    teacher = {"display_name": "T"}
    text = _render_review_text(review, teacher, 0, 1)
    assert "⚠️" not in text


def test_send_review_at_index_signature_has_viewer_admin_id():
    """_send_review_at_index 新增 keyword-only viewer_admin_id 参数。"""
    from bot.handlers.rreview_admin import _send_review_at_index
    sig = inspect.signature(_send_review_at_index)
    p = sig.parameters["viewer_admin_id"]
    assert p.kind == inspect.Parameter.KEYWORD_ONLY
    assert p.default is None


def test_send_review_at_index_uses_real_admin_id_in_audit():
    """rreview_view audit 应用 viewer_admin_id 而非 placeholder 0（修复关键）。"""
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    idx = src.find("async def _send_review_at_index(")
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert 'action="rreview_view"' in body
    # 新代码应使用 viewer_admin_id 替换原 placeholder
    assert "viewer_admin_id" in body
    # log_admin_audit 调用必须基于 viewer_admin_id，而非硬编码 0
    # 旧代码 "admin_id=0,  # placeholder" 模式应已不存在
    assert "admin_id=0," not in body


def test_send_review_at_index_callers_pass_viewer_admin_id():
    """所有 _send_review_at_index 调用方都应显式传 viewer_admin_id（5 处）。"""
    import bot.handlers.rreview_admin as mod
    src = _src(mod)
    # 函数定义在 line 604 附近；定义之外其它出现的 _send_review_at_index 应是调用
    # 统计调用方式：每处都带 viewer_admin_id=
    call_count = src.count("_send_review_at_index(")
    # 1 个 def + N 个调用
    viewer_arg_count = src.count("viewer_admin_id=")
    # 加 helper signature 自身的 viewer_admin_id 出现：def 行 + N 个调用都带
    # 最少 5 个调用 + def signature = 6 个 viewer_admin_id 出现
    assert viewer_arg_count >= 5, (
        f"_send_review_at_index 应至少 5 处调用 + 1 处 def 都带 viewer_admin_id；"
        f"实际 viewer_admin_id 出现 {viewer_arg_count} 次, "
        f"_send_review_at_index( 出现 {call_count} 次"
    )


# ============================================================
# 5. handler 行为：end-to-end with viewer hint
# ============================================================


def test_show_request_renders_hint_when_others_viewed(temp_db, monkeypatch):
    """_show_request_at_index 端到端：先注入 audit log，验证 detail 含 hint。"""
    from bot.handlers.admin_review import _show_request_at_index

    # 注入另一管理员的 review_view 记录
    _run(_insert_audit(999, "review_view", "edit_request", 42))

    pending = [{
        "id": 42, "teacher_id": 99, "teacher_display_name": "A",
        "field_name": "display_name", "old_value": "old", "new_value": "new",
        "created_at": "2026-05-20 10:00:00",
    }]
    cb = MagicMock()
    cb.from_user.id = 1001  # 自己
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    _run(_show_request_at_index(cb, pending, 0))
    call = cb.message.edit_text.await_args
    text = call.args[0] if call.args else call.kwargs.get("text", "")
    assert "#999" in text
    assert "查看过此条" in text


def test_show_request_excludes_self_from_hint(temp_db):
    """自己刚才查看过自己的不应进入 hint。"""
    from bot.handlers.admin_review import _show_request_at_index

    _run(_insert_audit(1001, "review_view", "edit_request", 42))  # 自己

    pending = [{
        "id": 42, "teacher_id": 99, "teacher_display_name": "A",
        "field_name": "display_name", "old_value": "old", "new_value": "new",
        "created_at": "2026-05-20 10:00:00",
    }]
    cb = MagicMock()
    cb.from_user.id = 1001
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock(return_value=None)
    _run(_show_request_at_index(cb, pending, 0))
    text = cb.message.edit_text.await_args.args[0]
    assert "#1001" not in text
    # 自己仍写 audit
    # （这是 UX-7.4 修复的副效果 —— audit log 不再是 placeholder 0）


# ============================================================
# 6. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    from _migration_baseline import EXPECTED_MIGRATION_VERSIONS
    assert {m.version for m in MIGRATIONS} == EXPECTED_MIGRATION_VERSIONS
