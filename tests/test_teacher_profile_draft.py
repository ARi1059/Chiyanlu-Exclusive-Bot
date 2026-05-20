"""Sprint UX-9 第三项（UX-9.3）：teacher_profile 录入草稿保存契约测试。

范围：
    - bot.database 新表 teacher_draft_states + Migration 注册
    - bot.database.save_teacher_draft / load_teacher_draft / clear_teacher_draft
    - bot.keyboards.admin_kb.teacher_profile_draft_restore_kb /
      teacher_profile_cancel_confirm_kb
    - bot.handlers.teacher_profile 4 个新 callback：
        tprofile:cancel_save / cancel_nosave / draft_restore / draft_discard
    - cb_profile_add_start 入口检查草稿
    - cb_profile_save 成功后清除草稿

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §6 痛点 3 + §11.3 第 3 项）：
    管理员代填老师档案 9 步流程长，途中误点取消 / 服务重启会丢失全部数据
    （含已上传 10 张照片 file_id）。本批让 cancel 弹出"是否保存草稿"，
    下次进入入口时检测到草稿提示"恢复 / 丢弃"。

约束：
    - 引入 1 个 schema 迁移（hard=soft，handler 端容错）
    - admin_id 作 PK（同一 admin 一次最多 1 个草稿）
    - 不动 teachers / teacher_edit_requests 主表
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


# ============ helpers ============


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(
        prefix=f"test_draft_{uuid.uuid4().hex}_", suffix=".db",
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
# 1. Migration 注册
# ============================================================


def test_teacher_draft_states_migration_registered():
    from bot.database import MIGRATIONS
    versions = [m.version for m in MIGRATIONS]
    assert "20260520_001_teacher_draft_states" in versions


def test_teacher_draft_states_migration_is_soft():
    """soft kind：表创建失败不阻断启动；handler 端容错保护。"""
    from bot.database import MIGRATIONS
    m = next(
        m for m in MIGRATIONS
        if m.version == "20260520_001_teacher_draft_states"
    )
    assert m.kind == "soft"


def test_teacher_draft_states_table_exists_after_init(temp_db):
    """init_db 后 teacher_draft_states 表应存在。"""
    from bot.database import get_db
    db = _run(get_db())
    cur = _run(db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='teacher_draft_states'",
    ))
    row = _run(cur.fetchone())
    _run(db.close())
    assert row is not None


# ============================================================
# 2. DB 函数：save / load / clear
# ============================================================


def test_save_load_roundtrip(temp_db):
    """save 后 load 应能拿到相同 data + fsm_state + step_label。"""
    from bot.database import save_teacher_draft, load_teacher_draft
    data = {
        "user_id": 100,
        "display_name": "测试",
        "photos": ["file_id_1", "file_id_2"],
    }
    ok = _run(save_teacher_draft(
        admin_id=999,
        fsm_state="TeacherProfileAddStates:waiting_display_name",
        data=data,
        step_label="Step 2 / 艺名",
    ))
    assert ok is True
    draft = _run(load_teacher_draft(999))
    assert draft is not None
    assert draft["fsm_state"] == "TeacherProfileAddStates:waiting_display_name"
    assert draft["step_label"] == "Step 2 / 艺名"
    assert draft["data"] == data


def test_save_upserts_same_admin(temp_db):
    """同 admin 二次 save 应 upsert，仅保留最新（admin_id PK）。"""
    from bot.database import save_teacher_draft, load_teacher_draft
    _run(save_teacher_draft(
        admin_id=999, fsm_state="state1", data={"a": 1}, step_label="L1",
    ))
    _run(save_teacher_draft(
        admin_id=999, fsm_state="state2", data={"b": 2}, step_label="L2",
    ))
    draft = _run(load_teacher_draft(999))
    assert draft["fsm_state"] == "state2"
    assert draft["data"] == {"b": 2}


def test_save_isolates_different_admins(temp_db):
    from bot.database import save_teacher_draft, load_teacher_draft
    _run(save_teacher_draft(1, "s1", {"a": 1}, step_label=None))
    _run(save_teacher_draft(2, "s2", {"b": 2}, step_label=None))
    assert _run(load_teacher_draft(1))["data"] == {"a": 1}
    assert _run(load_teacher_draft(2))["data"] == {"b": 2}


def test_load_returns_none_when_no_draft(temp_db):
    from bot.database import load_teacher_draft
    assert _run(load_teacher_draft(99999)) is None


def test_clear_existing_draft(temp_db):
    from bot.database import (
        save_teacher_draft, load_teacher_draft, clear_teacher_draft,
    )
    _run(save_teacher_draft(999, "s", {"a": 1}, step_label="L"))
    assert _run(clear_teacher_draft(999)) is True
    assert _run(load_teacher_draft(999)) is None


def test_clear_no_draft_returns_false(temp_db):
    from bot.database import clear_teacher_draft
    assert _run(clear_teacher_draft(99999)) is False


def test_save_handles_unicode_chinese(temp_db):
    """JSON 序列化应保留中文字符。"""
    from bot.database import save_teacher_draft, load_teacher_draft
    _run(save_teacher_draft(
        999, "s", {"display_name": "丁小夏", "tags": ["御姐", "高颜"]}, step_label="艺名",
    ))
    draft = _run(load_teacher_draft(999))
    assert draft["data"]["display_name"] == "丁小夏"
    assert "御姐" in draft["data"]["tags"]
    # step_label 也保留中文
    assert draft["step_label"] == "艺名"


def test_save_serializes_photos_file_ids(temp_db):
    """关键：photos file_id 列表能完整保存 + 加载（UX-9.3 痛点 2 核心场景）。"""
    from bot.database import save_teacher_draft, load_teacher_draft
    photos = [f"AgACAgIAxABBR_FAKE_{i:03d}" for i in range(10)]
    _run(save_teacher_draft(
        999, "TeacherProfileAddStates:waiting_photos",
        {"photos": photos}, step_label="Step 9",
    ))
    draft = _run(load_teacher_draft(999))
    assert draft["data"]["photos"] == photos


# ============================================================
# 3. keyboard 契约
# ============================================================


def test_draft_restore_kb_has_3_buttons():
    from bot.keyboards.admin_kb import teacher_profile_draft_restore_kb
    kb = teacher_profile_draft_restore_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "tprofile:draft_restore" in cbs
    assert "tprofile:draft_discard" in cbs
    assert "tprofile:cancel" in cbs  # 返回


def test_cancel_confirm_kb_save_and_nosave():
    from bot.keyboards.admin_kb import teacher_profile_cancel_confirm_kb
    kb = teacher_profile_cancel_confirm_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    assert "tprofile:cancel_save" in cbs
    assert "tprofile:cancel_nosave" in cbs
    # 不应有"继续录入"按钮（设计取舍 — 防止状态错乱）
    assert "tprofile:cancel_back" not in cbs


def test_cancel_confirm_kb_only_2_buttons():
    from bot.keyboards.admin_kb import teacher_profile_cancel_confirm_kb
    kb = teacher_profile_cancel_confirm_kb()
    assert len(_flat_buttons(kb)) == 2


# ============================================================
# 4. handler 静态契约
# ============================================================


def test_handler_imports_draft_db_functions():
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    assert "save_teacher_draft" in src
    assert "load_teacher_draft" in src
    assert "clear_teacher_draft" in src


def test_handler_imports_new_keyboards():
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    assert "teacher_profile_draft_restore_kb" in src
    assert "teacher_profile_cancel_confirm_kb" in src


def test_4_new_callbacks_registered():
    """4 个新 callback handler 必须注册。"""
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    for cb in (
        'F.data == "tprofile:cancel_save"',
        'F.data == "tprofile:cancel_nosave"',
        'F.data == "tprofile:draft_restore"',
        'F.data == "tprofile:draft_discard"',
    ):
        assert cb in src


def test_add_start_checks_draft_before_rendering_step1():
    """cb_profile_add_start 应先 load_teacher_draft，有草稿时返回不进 Step 1。"""
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    idx = src.find("async def cb_profile_add_start(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 4000]
    # load_teacher_draft 调用必须在 set_state 之前
    load_pos = body.find("load_teacher_draft")
    set_state_pos = body.find("set_state(TeacherProfileAddStates.waiting_forward)")
    assert 0 < load_pos < set_state_pos


def test_cancel_uses_confirm_when_has_progress():
    """cb_profile_cancel 检测 state 数据非空时应渲染二次确认页。"""
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    idx = src.find("async def cb_profile_cancel(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "teacher_profile_cancel_confirm_kb" in body
    # 应有判断 data 是否含真实进度
    assert "has_progress" in body or "data" in body


def test_save_clears_draft_on_success():
    """cb_profile_save 保存到 DB 成功后应清除草稿。"""
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    idx = src.find("async def cb_profile_save(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert "clear_teacher_draft" in body


def test_cancel_save_writes_draft():
    """cb_profile_cancel_save_draft 调用 save_teacher_draft。"""
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    idx = src.find("async def cb_profile_cancel_save_draft(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "save_teacher_draft" in body
    # 应排除 _last_active 等内部字段
    assert "_last_active" in body or "startswith('_')" in body


def test_cancel_nosave_does_not_save_draft():
    """cb_profile_cancel_nosave 不应调 save_teacher_draft。"""
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    idx = src.find("async def cb_profile_cancel_nosave(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 2000]
    assert "save_teacher_draft" not in body
    assert "state.clear" in body


def test_draft_restore_loads_then_sets_state():
    """cb_profile_draft_restore 应 load_teacher_draft → set_state → set_data。"""
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    idx = src.find("async def cb_profile_draft_restore(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    load_pos = body.find("load_teacher_draft")
    set_state_pos = body.find("set_state")
    set_data_pos = body.find("set_data")
    assert 0 < load_pos < set_state_pos
    assert 0 < load_pos < set_data_pos


def test_draft_discard_clears_then_enters_step1():
    """cb_profile_draft_discard 应 clear_teacher_draft + 设 waiting_forward state。"""
    import bot.handlers.teacher_profile as mod
    src = _src(mod)
    idx = src.find("async def cb_profile_draft_discard(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "clear_teacher_draft" in body
    assert "waiting_forward" in body


# ============================================================
# 5. step label mapping 完整性
# ============================================================


def test_step_label_mapping_covers_main_states():
    """_DRAFT_STEP_LABELS 应至少覆盖 main 路径的 9 个 step。"""
    import bot.handlers.teacher_profile as mod
    labels = mod._DRAFT_STEP_LABELS
    # 至少这些 state 名字必须有 mapping
    required = [
        "TeacherProfileAddStates:waiting_forward",
        "TeacherProfileAddStates:waiting_display_name",
        "TeacherProfileAddStates:waiting_basic_info",
        "TeacherProfileAddStates:waiting_region",
        "TeacherProfileAddStates:waiting_price",
        "TeacherProfileAddStates:waiting_service_content",
        "TeacherProfileAddStates:waiting_tags",
        "TeacherProfileAddStates:waiting_button_url",
        "TeacherProfileAddStates:waiting_photos",
        "TeacherProfileAddStates:waiting_confirm",
    ]
    for state in required:
        assert state in labels, f"missing label for {state}"


def test_format_draft_step_label_handles_unknown():
    """未知 state name 应返回原字符串（避免崩溃）。"""
    from bot.handlers.teacher_profile import _format_draft_step_label
    assert _format_draft_step_label("UnknownState:xxx") == "UnknownState:xxx"
    assert _format_draft_step_label(None) == "未知 step"


# ============================================================
# 6. 端到端：save → load → restore
# ============================================================


def test_e2e_draft_save_load_restore(temp_db):
    """完整 cycle：save 草稿 → load_teacher_draft → 还原 dict。"""
    from bot.database import save_teacher_draft, load_teacher_draft, clear_teacher_draft

    # 模拟 step 6 完成时保存
    data_step6 = {
        "user_id": 10001,
        "username": "test",
        "display_name": "丁小夏",
        "region": "北京",
        "price": "500 全套",
        "service_content": "OK",
        "photos": ["file1", "file2", "file3"],
    }
    _run(save_teacher_draft(
        999, "TeacherProfileAddStates:waiting_tags",
        data_step6, step_label="Step 7 / 标签",
    ))

    # 模拟下次进入：load
    draft = _run(load_teacher_draft(999))
    assert draft["fsm_state"] == "TeacherProfileAddStates:waiting_tags"
    assert draft["data"] == data_step6
    assert draft["data"]["photos"] == ["file1", "file2", "file3"]
    assert "丁小夏" in draft["data"]["display_name"]

    # 保存成功后 clear
    _run(clear_teacher_draft(999))
    assert _run(load_teacher_draft(999)) is None
