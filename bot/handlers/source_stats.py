"""渠道统计看板 + 用户来源查询（Phase 4 §五 + §七）

Callbacks:
    admin:source_stats                       渠道统计主页（TOP 20 混合）
    admin:source_stats:channel               频道来源 TOP 10
    admin:source_stats:group                 群组来源 TOP 10
    admin:source_stats:teacher               老师来源 TOP 10
    admin:source_stats:campaign              活动来源 TOP 10
    admin:source_stats:invite                邀请来源 TOP 10
    admin:user_source                        进入用户来源查询 FSM

FSM (UserSourceLookupStates.waiting_user_id):
    管理员输入 user_id，展示该用户的首次/最近/全量来源。
"""

import logging

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

from bot.database import (
    count_total_source_users,
    get_source_stats,
    get_teacher,
    get_top_sources_by_type,
    get_user_source_summary,
)
from bot.keyboards.admin_kb import (
    source_lookup_cancel_kb,
    source_stats_back_kb,
    source_stats_menu_kb,
)
from bot.states.teacher_states import UserSourceLookupStates
from bot.utils.permissions import admin_required

logger = logging.getLogger(__name__)

router = Router(name="source_stats")


_TYPE_LABELS: dict[str, str] = {
    "channel": "频道",
    "group": "群组",
    "teacher": "老师",
    "campaign": "活动",
    "invite": "邀请",
    "unknown": "未知",
}


def _fmt_ts(ts: str | None) -> str:
    """日期时间字符串截断到秒级显示"""
    if not ts:
        return "-"
    return str(ts).replace("T", " ")[:19]


async def _resolve_display_id(source_type: str, source_id: str) -> str:
    """source_id 渲染：老师类型补 display_name；其余原样返回"""
    if source_type != "teacher":
        return source_id or "-"
    sid = (source_id or "").strip()
    if not sid:
        return "-"
    try:
        tid = int(sid)
    except ValueError:
        return sid
    teacher = await get_teacher(tid)
    if teacher and teacher.get("display_name"):
        return f"{sid} {teacher['display_name']}"
    return sid


# ============ 主页：TOP 20 混合 ============


@router.callback_query(F.data == "admin:source_stats")
@admin_required
async def cb_source_stats(callback: types.CallbackQuery, state: FSMContext):
    """📈 渠道统计主面板"""
    await state.clear()
    total = await count_total_source_users()
    rows = await get_source_stats(limit=20)

    lines = [
        "📈 渠道统计",
        "",
        f"总来源用户：{total}",
        "",
    ]
    if not rows:
        lines.append("（暂无来源数据）")
    else:
        lines.append(f"TOP 来源（共 {len(rows)} 项）：")
        for idx, r in enumerate(rows, 1):
            stype = r["source_type"]
            label = _TYPE_LABELS.get(stype, stype)
            display = await _resolve_display_id(stype, r.get("source_id") or "")
            lines.append(
                f"{idx}. {label}:{display}｜用户 {r['user_count']}"
                f"｜最近 {_fmt_ts(r.get('last_seen_at'))}"
            )
    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=source_stats_menu_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=source_stats_menu_kb())
    await callback.answer()


# ============ 分类页：按 source_type 看 TOP 10 ============


@router.callback_query(F.data.startswith("admin:source_stats:"))
@admin_required
async def cb_source_stats_by_type(callback: types.CallbackQuery, state: FSMContext):
    """admin:source_stats:<type> 的分类页"""
    await state.clear()
    stype = callback.data[len("admin:source_stats:"):]
    if stype not in _TYPE_LABELS:
        await callback.answer("⚠️ 未知类型", show_alert=True)
        return

    rows = await get_top_sources_by_type(stype, limit=10)
    label = _TYPE_LABELS.get(stype, stype)

    lines = [
        f"📈 渠道统计 · {label}（TOP 10）",
        "",
    ]
    if not rows:
        lines.append("（暂无该类型的来源数据）")
    else:
        for idx, r in enumerate(rows, 1):
            display = await _resolve_display_id(stype, r.get("source_id") or "")
            lines.append(
                f"{idx}. {display}｜用户 {r['user_count']}"
                f"｜最近 {_fmt_ts(r.get('last_seen_at'))}"
            )
    text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=source_stats_back_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=source_stats_back_kb())
    await callback.answer()


# ============ 用户来源查询 FSM ============


@router.callback_query(F.data == "admin:user_source")
@admin_required
async def cb_user_source_enter(callback: types.CallbackQuery, state: FSMContext):
    """🔍 查用户来源 - 进入 FSM 等待输入 user_id"""
    await state.set_state(UserSourceLookupStates.waiting_user_id)
    await callback.message.edit_text(
        "🔍 用户来源查询\n\n请输入要查询的用户 Telegram 数字 ID：",
        reply_markup=source_lookup_cancel_kb(),
    )
    await callback.answer()


@router.message(UserSourceLookupStates.waiting_user_id)
@admin_required
async def on_user_source_id(message: types.Message, state: FSMContext):
    """接收 user_id，展示来源摘要"""
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.reply(
            "❌ 请输入纯数字 ID",
            reply_markup=source_lookup_cancel_kb(),
        )
        return

    user_id = int(text)
    summary = await get_user_source_summary(user_id)
    await state.clear()

    if summary is None:
        await message.answer(
            f"⚠️ 没有找到 user_id={user_id} 的用户记录",
        )
        # 回到渠道统计主页
        await message.answer(
            "📈 渠道统计 · 已退出查询",
            reply_markup=source_stats_menu_kb(),
        )
        return

    lines = [
        f"🔍 用户来源 · user_id = {user_id}",
        "",
    ]
    first_t = summary.get("first_source_type")
    first_i = summary.get("first_source_id")
    last_t = summary.get("last_source_type")
    last_i = summary.get("last_source_id")
    if first_t:
        first_display = await _resolve_display_id(first_t, first_i or "")
        lines.append(f"首次来源：{_TYPE_LABELS.get(first_t, first_t)} / {first_display}")
    else:
        lines.append("首次来源：(无)")
    if last_t:
        last_display = await _resolve_display_id(last_t, last_i or "")
        lines.append(f"最近来源：{_TYPE_LABELS.get(last_t, last_t)} / {last_display}")
    else:
        lines.append("最近来源：(无)")

    sources = summary.get("sources") or []
    if sources:
        lines.append("")
        lines.append(f"来源记录（{len(sources)} 条，按 first_seen_at）：")
        for idx, s in enumerate(sources, 1):
            stype = s.get("source_type", "")
            sid = s.get("source_id") or ""
            display = await _resolve_display_id(stype, sid)
            lines.append(
                f"{idx}. {_TYPE_LABELS.get(stype, stype)}:{display}"
                f" first={_fmt_ts(s.get('first_seen_at'))}"
                f" last={_fmt_ts(s.get('last_seen_at'))}"
            )
    else:
        lines.append("")
        lines.append("来源记录：(无)")

    await message.answer("\n".join(lines))
    await message.answer(
        "📈 渠道统计",
        reply_markup=source_stats_menu_kb(),
    )
