"""用户画像看板 handler（Phase 6.1）

Callbacks:
    admin:user_tags              用户画像看板主页（TOP 20 标签）
    admin:user_tags:query        进入"查询标签用户"FSM

FSM (UserTagsQueryStates.waiting_tag):
    管理员输入标签名，查询拥有该标签的用户（最多 50 位）

降级兼容：log_admin_audit 不存在 / 调用失败时静默跳过。
"""

import logging

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.database import (
    get_top_user_tags,
    get_users_by_tag,
)
from bot.keyboards.admin_kb import (
    user_tags_menu_kb,
    user_tags_query_cancel_kb,
    user_tags_query_result_kb,
)
from bot.states.teacher_states import UserTagsQueryStates
from bot.utils.permissions import admin_required

logger = logging.getLogger(__name__)

router = Router(name="user_tags")


async def _safe_log_admin_audit(
    admin_id: int,
    action: str,
    **kwargs,
) -> None:
    """log_admin_audit 不存在或失败时静默跳过（Phase 1 兼容降级）"""
    try:
        from bot.database import log_admin_audit  # type: ignore
    except ImportError:
        return
    try:
        await log_admin_audit(admin_id=admin_id, action=action, **kwargs)
    except Exception as e:
        logger.debug("log_admin_audit 失败 (action=%s): %s", action, e)


# ============ 主页：TOP 20 标签 ============


@router.callback_query(F.data == "admin:user_tags")
@admin_required
async def cb_user_tags(callback: types.CallbackQuery, state: FSMContext):
    """🏷 用户画像看板"""
    await state.clear()
    rows = await get_top_user_tags(limit=20)

    lines = ["🏷 用户画像看板", ""]
    if not rows:
        lines.append("（暂无画像数据）")
    else:
        lines.append(f"热门画像标签 TOP {len(rows)}：")
        lines.append("")
        for idx, r in enumerate(rows, 1):
            tag = r["tag"]
            user_count = r.get("user_count") or 0
            total_score = r.get("total_score") or 0
            lines.append(f"{idx}. {tag}｜用户 {user_count}｜总分 {total_score}")

    await _safe_log_admin_audit(
        admin_id=callback.from_user.id,
        action="admin_view_user_tags",
        target_type="user_tags",
        target_id=None,
    )

    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=user_tags_menu_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=user_tags_menu_kb())
    await callback.answer()


# ============ 查询标签用户 FSM ============


@router.callback_query(F.data == "admin:user_tags:query")
@admin_required
async def cb_user_tags_query_enter(callback: types.CallbackQuery, state: FSMContext):
    """🔍 查询标签用户 - 进入 FSM 等待输入标签"""
    await state.set_state(UserTagsQueryStates.waiting_tag)
    text = (
        "🔍 查询标签用户\n\n"
        "请输入要查询的标签名（区分大小写，与画像看板上的展示一致）：\n"
        "例如：御姐 / 高颜值 / 天府一街 / 1000P / 收藏型用户\n\n"
        "/cancel 退出"
    )
    try:
        await callback.message.edit_text(text, reply_markup=user_tags_query_cancel_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=user_tags_query_cancel_kb())
    await callback.answer()


@router.message(UserTagsQueryStates.waiting_tag, Command("cancel"))
@admin_required
async def cmd_cancel_tag_query(message: types.Message, state: FSMContext):
    """FSM 内 /cancel 退出"""
    await state.clear()
    await message.answer(
        "已取消查询",
        reply_markup=user_tags_query_result_kb(),
    )


@router.message(UserTagsQueryStates.waiting_tag)
@admin_required
async def on_tag_query(message: types.Message, state: FSMContext):
    """接收标签名，渲染拥有该标签的用户列表"""
    tag = (message.text or "").strip()
    if not tag:
        await message.reply(
            "请输入有效的标签名，或 /cancel 退出",
            reply_markup=user_tags_query_cancel_kb(),
        )
        return

    rows = await get_users_by_tag(tag, limit=50)
    await state.clear()

    if not rows:
        text = f"🏷 标签：{tag}\n\n（没有用户拥有该标签）"
        await message.answer(text, reply_markup=user_tags_query_result_kb())
        return

    lines = [f"🏷 标签：{tag}", "", f"用户数：{len(rows)}", ""]
    for idx, r in enumerate(rows, 1):
        uid = r.get("user_id")
        score = r.get("score") or 0
        username = (r.get("username") or "").strip()
        first_name = (r.get("first_name") or "").strip()

        parts = [f"ID {uid}"]
        if username:
            parts.append(f"@{username}")
        elif first_name:
            parts.append(first_name)
        parts.append(f"score {score}")
        lines.append(f"{idx}. " + "｜".join(parts))

    # Telegram 单条消息上限 4096 字符；50 条用户行通常远小于此但兜底截断
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…（已截断）"

    await message.answer(text, reply_markup=user_tags_query_result_kb())
