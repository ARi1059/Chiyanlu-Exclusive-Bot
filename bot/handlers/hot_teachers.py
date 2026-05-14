"""热门老师 / 热门推荐管理（Phase 3）

用户侧 callback:
    user:hot                  → 私聊主菜单"🔥 热门老师"列表（按统一排序）

管理员侧 callback:
    admin:hot_manage          → 热门推荐管理主页
    admin:hot:add             → 进入"添加推荐"FSM
    admin:hot:weight          → 进入"修改权重"FSM
    admin:hot:remove          → 进入"取消推荐"FSM
    admin:hot:recalc          → 立即重算所有老师 hot_score

FSM (HotManageStates):
    waiting_feature_id     → 添加推荐：输入老师 ID
    waiting_weight_id      → 修改权重：输入老师 ID（保存到 state.data）
    waiting_weight_value   → 修改权重：输入权重值
    waiting_remove_id      → 取消推荐：输入老师 ID

不调用 button_url 直跳；所有老师按钮 → teacher:view:<id>。
"""

import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from pytz import timezone

from bot.config import config
from bot.database import (
    get_hot_teachers,
    get_teacher,
    is_effective_featured,
    list_featured_teachers,
    recalculate_hot_scores,
    update_teacher_ranking,
)
from bot.keyboards.admin_kb import (
    hot_manage_cancel_kb,
    hot_manage_menu_kb,
    main_menu_kb,
)
from bot.keyboards.user_kb import (
    back_to_user_main_kb,
    teacher_detail_list_kb,
)
from bot.states.teacher_states import HotManageStates
from bot.utils.permissions import admin_required

logger = logging.getLogger(__name__)

router = Router(name="hot_teachers")

_tz = timezone(config.timezone)


def _today_str() -> str:
    return datetime.now(_tz).strftime("%Y-%m-%d")


# 兼容降级：log_admin_audit 在 Phase 1 后才存在。若调用方未装载，吞掉异常。
async def _safe_log_admin_audit(
    admin_id: int,
    action: str,
    **kwargs,
) -> None:
    try:
        from bot.database import log_admin_audit  # type: ignore
    except ImportError:
        return
    try:
        await log_admin_audit(admin_id=admin_id, action=action, **kwargs)
    except Exception as e:
        logger.debug("log_admin_audit 调用失败 (action=%s): %s", action, e)


# ============ 用户侧：🔥 热门老师 ============


@router.callback_query(F.data == "user:hot")
async def cb_user_hot(callback: types.CallbackQuery):
    """普通用户主菜单的"🔥 热门老师"入口"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    teachers = await get_hot_teachers(limit=10)
    if not teachers:
        await callback.message.edit_text(
            "🔥 热门老师\n\n暂无热门老师数据，可以先去 🔍 搜索老师 看看。",
            reply_markup=back_to_user_main_kb(),
        )
        await callback.answer()
        return

    today = _today_str()

    def _label(t: dict) -> str:
        prefix = "🔥 " if is_effective_featured(t, today) else ""
        return f"{prefix}{t['display_name']} · {t['region']} · {t['price']}"

    text = (
        f"🔥 热门老师（TOP {len(teachers)}）\n\n"
        "以下是近期热度较高的老师，点击查看详情。"
    )
    kb = teacher_detail_list_kb(
        teachers,
        per_row=1,
        label_fn=_label,
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# ============ 管理员侧：🔥 热门推荐管理 ============


def _format_featured_until(fu) -> str:
    if fu is None:
        return "长期"
    s = str(fu).strip()
    if not s:
        return "长期"
    return f"截止 {s[:10]}"


def _render_hot_manage_text(featured: list[dict], today: str) -> str:
    lines = ["🔥 热门推荐管理", ""]
    if not featured:
        lines.append("当前推荐老师：(无)")
    else:
        active_list = [t for t in featured if is_effective_featured(t, today)]
        expired_list = [t for t in featured if not is_effective_featured(t, today)]

        lines.append(f"当前推荐老师（{len(active_list)} 位有效 / {len(featured)} 位标记）：")
        idx = 1
        for t in active_list:
            weight = t.get("sort_weight") or 0
            lines.append(
                f"{idx}. {t['display_name']}｜权重 {weight}｜{_format_featured_until(t.get('featured_until'))}"
            )
            idx += 1
        if expired_list:
            lines.append("")
            lines.append("已过期标记（仍是 is_featured=1，但 featured_until 已过）：")
            for t in expired_list:
                weight = t.get("sort_weight") or 0
                lines.append(
                    f"• {t['display_name']}｜权重 {weight}｜{_format_featured_until(t.get('featured_until'))}"
                )
    return "\n".join(lines)


async def _show_hot_manage(
    target: types.Message | types.CallbackQuery,
) -> None:
    """渲染热门推荐管理主页（可由 callback / FSM message 调用）"""
    featured = await list_featured_teachers()
    text = _render_hot_manage_text(featured, _today_str())
    kb = hot_manage_menu_kb()
    if isinstance(target, types.CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb)
        except Exception:
            await target.message.answer(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "admin:hot_manage")
@admin_required
async def cb_admin_hot_manage(callback: types.CallbackQuery, state: FSMContext):
    """进入 / 返回热门推荐管理主页"""
    await state.clear()
    await _show_hot_manage(callback)
    await callback.answer()


# ----- 添加推荐 -----


@router.callback_query(F.data == "admin:hot:add")
@admin_required
async def cb_hot_add(callback: types.CallbackQuery, state: FSMContext):
    """➕ 添加推荐"""
    await state.set_state(HotManageStates.waiting_feature_id)
    await callback.message.edit_text(
        "➕ 添加推荐\n\n"
        "请输入要推荐的老师 Telegram 数字 ID：\n"
        "（默认权重 100，长期推荐；如需修改权重再用「修改权重」）",
        reply_markup=hot_manage_cancel_kb(),
    )
    await callback.answer()


@router.message(HotManageStates.waiting_feature_id)
@admin_required
async def on_feature_id(message: types.Message, state: FSMContext):
    """接收老师 ID，设置 is_featured=1 + sort_weight=100"""
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.reply("❌ 请输入纯数字 ID")
        return

    teacher_id = int(text)
    teacher = await get_teacher(teacher_id)
    if not teacher:
        await message.reply("❌ 没有找到这位老师")
        return

    await update_teacher_ranking(
        teacher_id,
        sort_weight=100,
        is_featured=1,
        featured_until=None,
    )
    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="teacher_feature_add",
        target_type="teacher",
        target_id=teacher_id,
        detail={"display_name": teacher["display_name"], "sort_weight": 100},
    )
    await state.clear()
    await message.answer(
        f"✅ 已添加推荐: {teacher['display_name']} (权重 100，长期)"
    )
    await _show_hot_manage(message)


# ----- 修改权重 -----


@router.callback_query(F.data == "admin:hot:weight")
@admin_required
async def cb_hot_weight(callback: types.CallbackQuery, state: FSMContext):
    """✏️ 修改权重 - 步骤 1：输入老师 ID"""
    await state.set_state(HotManageStates.waiting_weight_id)
    await callback.message.edit_text(
        "✏️ 修改权重\n\n请输入要修改权重的老师 Telegram 数字 ID：",
        reply_markup=hot_manage_cancel_kb(),
    )
    await callback.answer()


@router.message(HotManageStates.waiting_weight_id)
@admin_required
async def on_weight_id(message: types.Message, state: FSMContext):
    """修改权重 - 步骤 2：收到 ID，进入下一状态等待权重值"""
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.reply("❌ 请输入纯数字 ID")
        return

    teacher_id = int(text)
    teacher = await get_teacher(teacher_id)
    if not teacher:
        await message.reply("❌ 没有找到这位老师")
        return

    await state.set_state(HotManageStates.waiting_weight_value)
    await state.update_data(
        teacher_id=teacher_id,
        display_name=teacher["display_name"],
    )
    current_weight = teacher.get("sort_weight") or 0
    await message.answer(
        f"老师：{teacher['display_name']}\n"
        f"当前权重：{current_weight}\n\n"
        "请输入新的 sort_weight（整数，可以为负数，数值越大越靠前）：",
        reply_markup=hot_manage_cancel_kb(),
    )


@router.message(HotManageStates.waiting_weight_value)
@admin_required
async def on_weight_value(message: types.Message, state: FSMContext):
    """修改权重 - 步骤 3：接收权重值并更新"""
    text = (message.text or "").strip()
    try:
        weight = int(text)
    except ValueError:
        await message.reply("❌ 请输入整数")
        return

    data = await state.get_data()
    teacher_id = data.get("teacher_id")
    display_name = data.get("display_name", str(teacher_id))
    if not teacher_id:
        await state.clear()
        await message.answer("⚠️ 会话状态丢失，请重新开始")
        await _show_hot_manage(message)
        return

    ok = await update_teacher_ranking(teacher_id, sort_weight=weight)
    if not ok:
        await message.answer("⚠️ 更新失败（老师可能已删除）")
        await state.clear()
        await _show_hot_manage(message)
        return

    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="teacher_sort_weight_update",
        target_type="teacher",
        target_id=teacher_id,
        detail={"display_name": display_name, "sort_weight": weight},
    )
    await state.clear()
    await message.answer(f"✅ {display_name} 的权重已更新为 {weight}")
    await _show_hot_manage(message)


# ----- 取消推荐 -----


@router.callback_query(F.data == "admin:hot:remove")
@admin_required
async def cb_hot_remove(callback: types.CallbackQuery, state: FSMContext):
    """❌ 取消推荐"""
    await state.set_state(HotManageStates.waiting_remove_id)
    await callback.message.edit_text(
        "❌ 取消推荐\n\n请输入要取消推荐的老师 Telegram 数字 ID：\n"
        "（仅修改 is_featured=0，sort_weight 保留不动）",
        reply_markup=hot_manage_cancel_kb(),
    )
    await callback.answer()


@router.message(HotManageStates.waiting_remove_id)
@admin_required
async def on_remove_id(message: types.Message, state: FSMContext):
    """接收老师 ID，设置 is_featured=0"""
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.reply("❌ 请输入纯数字 ID")
        return

    teacher_id = int(text)
    teacher = await get_teacher(teacher_id)
    if not teacher:
        await message.reply("❌ 没有找到这位老师")
        return

    await update_teacher_ranking(teacher_id, is_featured=0)
    await _safe_log_admin_audit(
        admin_id=message.from_user.id,
        action="teacher_feature_remove",
        target_type="teacher",
        target_id=teacher_id,
        detail={"display_name": teacher["display_name"]},
    )
    await state.clear()
    await message.answer(f"✅ 已取消推荐: {teacher['display_name']}")
    await _show_hot_manage(message)


# ----- 重算热度 -----


@router.callback_query(F.data == "admin:hot:recalc")
@admin_required
async def cb_hot_recalc(callback: types.CallbackQuery):
    """🔄 重算热度"""
    count = await recalculate_hot_scores()
    await _safe_log_admin_audit(
        admin_id=callback.from_user.id,
        action="teacher_hot_score_recalculate",
        target_type="teacher",
        target_id=None,
        detail={"count": count},
    )
    await callback.answer(f"✅ 已重算 {count} 位老师热度", show_alert=True)
    await _show_hot_manage(callback)
