"""Sprint UX-6 第三项（UX-6.3）：老师资料字段面板高频字段置顶契约测试。

范围：bot.keyboards.teacher_self_kb.teacher_profile_kb 布局调整。

UX 目标（参见 docs/UX-EFFICIENCY-PLAN.md §3.3.C + UX-FEATURE-ITERATION §6 痛点 4 + §11.1 决策 2）：
    把高频变更字段（价格 / 地区 / 标签 / 图片）排在第一、二行，
    让老师从"我的资料"进入后**第一眼**就能点到常用字段，少 1-2 行视觉跳转。

设计决策（与 §11.3 范围里"price_detail 加入 EDITABLE_FIELDS"差异，commit 内说明）：
    本批仅做 keyboard 布局重排，**不开放 price_detail 自助编辑** ——price_detail
    需同步 3 处白名单（EDITABLE_FIELDS / TEACHER_EDITABLE_FIELDS / update_teacher.allowed_fields），
    跨越业务策略评估，超出 UX-6.3 范围。留待后续 sprint 单独评估。

约束：
    - 不改任何 callback_data（仅按钮位置重排）
    - 旧 inline button（历史快照）依然能命中各字段 edit FSM
    - 不动 EDITABLE_FIELDS / TEACHER_EDITABLE_FIELDS / update_teacher
    - 不引入 schema 迁移
"""
from __future__ import annotations

import pytest  # noqa: F401


# ============ helpers ============


def _flat_buttons(kb) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            out.append(btn)
    return out


def _row_callbacks(kb, row_idx: int) -> list:
    return [b.callback_data for b in kb.inline_keyboard[row_idx]]


# ============================================================
# 1. 行序契约：高频字段在前两行
# ============================================================


def test_first_row_contains_price_and_region():
    """第一行：💰 价格 + 📍 地区。"""
    from bot.keyboards.teacher_self_kb import teacher_profile_kb
    kb = teacher_profile_kb()
    cbs = _row_callbacks(kb, 0)
    assert "teacher_self:edit:price" in cbs
    assert "teacher_self:edit:region" in cbs


def test_second_row_contains_tags_and_photo():
    """第二行：🏷️ 标签 + 🖼️ 图片。"""
    from bot.keyboards.teacher_self_kb import teacher_profile_kb
    kb = teacher_profile_kb()
    cbs = _row_callbacks(kb, 1)
    assert "teacher_self:edit:tags" in cbs
    assert "teacher_self:edit:photo_file_id" in cbs


def test_third_row_contains_display_name_and_button_text():
    """第三行（低频）：📝 艺名 + 🔠 按钮文本。"""
    from bot.keyboards.teacher_self_kb import teacher_profile_kb
    kb = teacher_profile_kb()
    cbs = _row_callbacks(kb, 2)
    assert "teacher_self:edit:display_name" in cbs
    assert "teacher_self:edit:button_text" in cbs


def test_fourth_row_is_locked_link():
    """第四行：锁定的链接提示。"""
    from bot.keyboards.teacher_self_kb import teacher_profile_kb
    kb = teacher_profile_kb()
    cbs = _row_callbacks(kb, 3)
    assert cbs == ["teacher_self:locked:button_url"]


def test_last_row_is_back_to_main_menu():
    """最后一行：返回主菜单。"""
    from bot.keyboards.teacher_self_kb import teacher_profile_kb
    kb = teacher_profile_kb()
    cbs = _row_callbacks(kb, -1)
    assert cbs == ["teacher_self:menu"]


# ============================================================
# 2. callback_data 全集与 UX-6.3 前完全一致（旧 inline button 兼容）
# ============================================================


def test_all_callbacks_unchanged_set():
    """callback_data 全集与改前完全一致——仅按钮位置变动，不引入/删除任何 callback。"""
    from bot.keyboards.teacher_self_kb import teacher_profile_kb
    cbs = sorted(b.callback_data for b in _flat_buttons(teacher_profile_kb()))
    expected = sorted([
        "teacher_self:edit:display_name",
        "teacher_self:edit:region",
        "teacher_self:edit:price",
        "teacher_self:edit:tags",
        "teacher_self:edit:photo_file_id",
        "teacher_self:edit:button_text",
        "teacher_self:locked:button_url",
        "teacher_self:menu",
    ])
    assert cbs == expected


def test_total_button_count_unchanged():
    """按钮总数仍是 8（6 个 edit + 1 locked + 1 返回）。"""
    from bot.keyboards.teacher_self_kb import teacher_profile_kb
    assert len(_flat_buttons(teacher_profile_kb())) == 8


def test_total_row_count_unchanged():
    """行数仍是 5（避免视觉跳跃）。"""
    from bot.keyboards.teacher_self_kb import teacher_profile_kb
    assert len(teacher_profile_kb().inline_keyboard) == 5


# ============================================================
# 3. 高频字段位置优先级断言
# ============================================================


def test_high_frequency_fields_before_low_frequency():
    """4 个高频字段（price/region/tags/photo）应在 2 个低频字段（display_name/button_text）之前。"""
    from bot.keyboards.teacher_self_kb import teacher_profile_kb
    kb = teacher_profile_kb()
    cbs = [b.callback_data for b in _flat_buttons(kb)]
    high_freq = [
        "teacher_self:edit:price",
        "teacher_self:edit:region",
        "teacher_self:edit:tags",
        "teacher_self:edit:photo_file_id",
    ]
    low_freq = [
        "teacher_self:edit:display_name",
        "teacher_self:edit:button_text",
    ]
    max_high = max(cbs.index(c) for c in high_freq)
    min_low = min(cbs.index(c) for c in low_freq)
    assert max_high < min_low, (
        "所有高频字段位置应在低频字段之前"
    )


# ============================================================
# 4. 不动 EDITABLE_FIELDS 白名单（决策：不开放 price_detail）
# ============================================================


def test_editable_fields_handler_whitelist_unchanged():
    """teacher_self.EDITABLE_FIELDS 仍是 6 个老字段，未引入 price_detail。"""
    from bot.handlers.teacher_self import EDITABLE_FIELDS
    assert EDITABLE_FIELDS == {
        "display_name", "region", "price",
        "tags", "photo_file_id", "button_text",
    }


def test_editable_fields_db_whitelist_unchanged():
    """bot.database.TEACHER_EDITABLE_FIELDS 仍是 6 个老字段。"""
    from bot.database import TEACHER_EDITABLE_FIELDS
    assert TEACHER_EDITABLE_FIELDS == {
        "display_name", "region", "price",
        "tags", "photo_file_id", "button_text",
    }


# ============================================================
# 5. 渲染辅助 _format_teacher_profile_text 仍能用
# ============================================================


def test_format_teacher_profile_text_still_renders():
    """业务保护：UX-6.3 不破坏 _format_teacher_profile_text 渲染。"""
    from bot.handlers.teacher_self import _format_teacher_profile_text
    teacher = {
        "user_id": 1001,
        "username": "u",
        "display_name": "艺名",
        "region": "地区",
        "price": "500",
        "tags": '["御姐"]',
        "photo_file_id": "abc",
        "button_url": "https://t.me/u",
        "button_text": "查看",
        "is_active": 1,
    }
    text = _format_teacher_profile_text(teacher)
    assert "艺名" in text
    assert "地区" in text
    assert "500" in text


# ============================================================
# 6. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states"}
