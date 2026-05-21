"""Sprint UX-9 第五项（UX-9.5）：抽奖创建 entry_cost_points 升为主线 Step 8 契约测试。

范围：
    - bot.states.teacher_states.LotteryCreateStates.waiting_entry_cost 新 state
    - bot.handlers.admin_lottery._enter_entry_cost_step 主线 Step 8 渲染
    - bot.handlers.admin_lottery.on_entry_cost_mainline Step 8 输入处理
    - bot.handlers.admin_lottery.cb_lottery_c_req_done 改为进 entry_cost step
    - 全部 Step X/N 标签从 /10 升为 /11；后 3 步序号 +1（8→9 / 9→10 / 10→11）

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §3.2 痛点 6 + §11.3 第 5 项）：
    entry_cost_points 原本在确认页通过额外按钮设置，超管"漏点"会保存为 0（免费）→
    意外免费抽奖。本批升为主线必填步骤；保留确认页 [💰 设置参与所需积分] 按钮
    作为返修入口（保持旧 callback admin:lottery:c_set_cost 兼容）。

约束：
    - 不改任何 callback_data（admin:lottery:c_set_cost / c_cost_back / c_save 不变）
    - 旧 waiting_entry_cost_input state 保留（返修入口路径）
    - 新增 waiting_entry_cost state（主线路径）
    - 不引入 schema 迁移（entry_cost_points 字段早已存在 + KV）
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
# 1. state 定义 + 旧 state 兼容
# ============================================================


def test_waiting_entry_cost_state_exists():
    """新增主线 Step 8 state。"""
    from bot.states.teacher_states import LotteryCreateStates
    assert hasattr(LotteryCreateStates, "waiting_entry_cost")


def test_legacy_waiting_entry_cost_input_state_still_exists():
    """旧 state 保留作返修入口（确认页 [💰 设置参与所需积分]）。"""
    from bot.states.teacher_states import LotteryCreateStates
    assert hasattr(LotteryCreateStates, "waiting_entry_cost_input")


def test_two_states_are_distinct():
    """主线 state 与返修 state 必须是不同 State 对象。"""
    from bot.states.teacher_states import LotteryCreateStates
    assert (
        LotteryCreateStates.waiting_entry_cost is not
        LotteryCreateStates.waiting_entry_cost_input
    )


# ============================================================
# 2. cb_lottery_c_req_done 改为进入 entry_cost step
# ============================================================


def test_c_req_done_enters_entry_cost_step():
    """必关频道完成后应进 entry_cost step（不再直接进 publish_mode）。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    idx = src.find("async def cb_lottery_c_req_done(")
    end = src.find("\n\n\n", idx) if src.find("\n\n\n", idx) > 0 else idx + 2000
    body = src[idx:end]
    # 应调 _enter_entry_cost_step
    assert "_enter_entry_cost_step" in body
    # 不应再直接 set_state(...waiting_publish_mode...)
    assert "waiting_publish_mode" not in body


# ============================================================
# 3. _enter_entry_cost_step 渲染契约
# ============================================================


def test_enter_entry_cost_renders_step_8_label():
    """主线 Step 8 文案应是"Step 8/11"。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    idx = src.find("async def _enter_entry_cost_step(")
    assert idx > 0
    end = src.find("\n\n\n", idx) if src.find("\n\n\n", idx) > 0 else idx + 3000
    body = src[idx:end]
    assert "Step 8/11" in body
    # 应进 waiting_entry_cost state
    assert "waiting_entry_cost" in body
    # 应显示 0-1000000 取值范围引导
    assert "0-1000000" in body or "1000000" in body


# ============================================================
# 4. on_entry_cost_mainline 输入处理
# ============================================================


def test_mainline_handler_validates_integer_range():
    """主线 handler 应做整数 + 范围 0-1000000 校验。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    idx = src.find("async def on_entry_cost_mainline(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    # 范围校验
    assert "0 <= n <= 1000000" in body
    # 写入 entry_cost_points 字段
    assert "entry_cost_points=n" in body


def test_mainline_handler_sets_publish_mode_state_after_success():
    """主线 handler 成功后应进入 Step 9（waiting_publish_mode）。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    idx = src.find("async def on_entry_cost_mainline(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "waiting_publish_mode" in body
    # 文案应是 Step 9
    assert "Step 9/11" in body


def test_mainline_handler_supports_cancel():
    """/cancel 应触发 cmd_cancel_lottery_create（业务保护）。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    idx = src.find("async def on_entry_cost_mainline(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 3000]
    assert "/cancel" in body
    assert "cmd_cancel_lottery_create" in body


# ============================================================
# 5. 旧返修入口 cb_lottery_c_set_cost 完整保留
# ============================================================


def test_legacy_set_cost_callback_handler_still_registered():
    """admin:lottery:c_set_cost callback 应仍注册（确认页 [💰 设置参与所需积分]）。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    assert 'F.data == "admin:lottery:c_set_cost"' in src


def test_legacy_set_cost_uses_legacy_state():
    """旧返修入口仍进 waiting_entry_cost_input（与主线 waiting_entry_cost 区分）。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    idx = src.find("async def cb_lottery_c_set_cost(")
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 2000]
    assert "waiting_entry_cost_input" in body


def test_legacy_input_handler_still_returns_to_confirm():
    """旧返修 handler on_entry_cost_input 仍回 _enter_confirm_step。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    idx = src.find("async def on_entry_cost_input(")
    assert idx > 0
    end = src.find("\n@router", idx + 1)
    body = src[idx:end if end > 0 else idx + 2000]
    assert "_enter_confirm_step" in body


# ============================================================
# 6. Step 标签全部 /10 → /11；后 3 步序号 +1
# ============================================================


def test_no_legacy_step_10_labels_remain():
    """所有 "Step X/10" 应已被替换为 "Step X/11"（含 Step 10/10 → 11/11）。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    # 创建流程的 Step 标签：不应有 "/10）" 或 "/10\\n" 等残留
    # （/10 数字本身在评论里可能有，但 Step X/10 模式应已替换）
    import re
    # 匹配 "Step N/10" 或 "Step N.5/10" 或 "Step Nb/10" 模式
    pattern = re.compile(r"Step \d+(\.\d+)?b?/10[^\d]")
    matches = pattern.findall(src)
    assert not matches, f"还有 /10 标签未替换: {matches}"


def test_publish_mode_step_renamed_to_9_11():
    """原 Step 8/10（publish_mode）→ Step 9/11。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    # "Step 9/11" 字面量必须存在
    assert "Step 9/11" in src
    # 不应残留 "Step 8/10" / "Step 8/11"（pub_mode 已升 step 9）
    # Step 8 现在归 entry_cost（出现在 _enter_entry_cost_step 注释 / 文案中）
    # 而非 publish_mode；publish_mode 文案应是 9/11
    # 验证：发布模式 keyboard 调用旁的文案
    pub_kb_idx = src.find("lottery_create_publish_mode_kb()")
    assert pub_kb_idx > 0
    window = src[max(0, pub_kb_idx - 600):pub_kb_idx]
    assert "Step 9/11" in window


def test_draw_at_step_renamed_to_10_11():
    """原 Step 9/10（draw_at）→ Step 10/11。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    assert "Step 10/11" in src


def test_confirm_step_renamed_to_11_11():
    """原 Step 10/10（confirm）→ Step 11/11。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    assert "Step 11/11" in src


def test_step_4_5_label_preserved_with_11():
    """子步骤 Step 4.5（entry_code）保留命名规则；分母改为 11。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    assert "Step 4.5/11" in src


# ============================================================
# 7. 业务保护：c_save 仍校验 + 旧 callback 全部存在
# ============================================================


def test_c_save_handler_still_registered():
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    assert 'F.data == "admin:lottery:c_save"' in src


def test_publish_mode_callback_unchanged():
    """admin:lottery:c_pub:* callback 命名空间不变。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    assert 'F.data.startswith("admin:lottery:c_pub:")' in src


def test_required_done_callback_unchanged():
    """admin:lottery:c_req_done 仍是必关频道完成入口。"""
    import bot.handlers.admin_lottery as mod
    src = _src(mod)
    assert 'F.data == "admin:lottery:c_req_done"' in src


# ============================================================
# 8. 不引入 schema 迁移
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable"}
