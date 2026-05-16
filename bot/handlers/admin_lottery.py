"""超管「抽奖管理」工具（Phase L.1）

入口：主面板 [🎲 抽奖管理]（仅 is_super=True 可见）

callback 命名空间：admin:lottery:*
  - admin:lottery                    → 子菜单
  - admin:lottery:list               → 抽奖列表
  - admin:lottery:item:<id>          → 抽奖详情
  - admin:lottery:cancel:<id>        → 取消草稿二次确认
  - admin:lottery:cancel_ok:<id>     → 实际取消

  本 phase 仅 draft 状态可取消（active 取消留给 L.4）。
  创建 FSM 见 admin_lottery 创建模块（L.1.2）。
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext

from datetime import datetime, timezone as _tz
from pytz import timezone

from bot.config import config
from bot.database import (
    LOTTERY_STATUSES,
    cancel_lottery,
    count_lotteries_by_status,
    count_lottery_entries,
    create_lottery,
    find_lottery_by_entry_code,
    get_lottery,
    is_super_admin,
    list_lotteries_by_status,
    log_admin_audit,
)
from bot.keyboards.admin_kb import (
    admin_lottery_cancel_confirm_kb,
    admin_lottery_detail_kb,
    admin_lottery_list_kb,
    admin_lottery_menu_kb,
    admin_lottery_publish_confirm_kb,
    lottery_create_cancel_kb,
    lottery_create_confirm_kb,
    lottery_create_method_kb,
    lottery_create_prize_count_kb,
    lottery_create_publish_mode_kb,
    lottery_create_required_kb,
    lottery_create_skip_cancel_kb,
)
from bot.states.teacher_states import LotteryCreateStates
from bot.utils.required_channels import precheck_required_chat

logger = logging.getLogger(__name__)

router = Router(name="admin_lottery")


def _super_admin_required(func):
    """仅 super_admin 可访问；普通 admin / 用户 alert 拒绝"""
    async def wrapper(event, *args, **kwargs):
        if isinstance(event, types.CallbackQuery):
            uid = event.from_user.id
            denied = lambda: event.answer("此操作需超级管理员权限", show_alert=True)
        elif isinstance(event, types.Message):
            uid = event.from_user.id
            denied = lambda: event.reply("此操作需超级管理员权限")
        else:
            return
        if uid != config.super_admin_id and not await is_super_admin(uid):
            await denied()
            return
        return await func(event, *args, **kwargs)
    return wrapper


# ============ 子菜单 ============

@router.callback_query(F.data == "admin:lottery")
@_super_admin_required
async def cb_admin_lottery(callback: types.CallbackQuery, state: FSMContext):
    """[🎲 抽奖管理] 主菜单"""
    await state.clear()
    n = await count_lotteries_by_status()
    text = (
        "🎲 抽奖管理\n\n"
        "- ➕ 创建新抽奖：完整 10 步流程录入草稿\n"
        "- 📋 抽奖列表：按状态查看所有抽奖（草稿 / 已计划 / 进行中 / 已开奖 / 已取消）\n\n"
        f"当前共 {n} 条抽奖记录。"
    )
    try:
        await callback.message.edit_text(text, reply_markup=admin_lottery_menu_kb(n))
    except Exception:
        await callback.message.answer(text, reply_markup=admin_lottery_menu_kb(n))
    await callback.answer()


# ============ 列表 ============

@router.callback_query(F.data == "admin:lottery:list")
@_super_admin_required
async def cb_admin_lottery_list(callback: types.CallbackQuery, state: FSMContext):
    """[📋 抽奖列表] 展示最近 30 条 + 按状态分组统计"""
    await state.clear()
    items = await list_lotteries_by_status(status=None, limit=30)
    if not items:
        text = "📋 抽奖列表（共 0 条）\n\n暂无抽奖记录。点 [➕ 创建新抽奖] 开始。"
        try:
            await callback.message.edit_text(text, reply_markup=admin_lottery_menu_kb(0))
        except Exception:
            pass
        await callback.answer()
        return

    # 状态分组统计
    counts: dict[str, int] = {}
    for it in items:
        s = it.get("status", "?")
        counts[s] = counts.get(s, 0) + 1
    summary_parts: list[str] = []
    label_map = {s["key"]: s["label"] for s in LOTTERY_STATUSES}
    for s in LOTTERY_STATUSES:
        c = counts.get(s["key"], 0)
        if c:
            summary_parts.append(f"{label_map[s['key']]} {c}")
    summary = "  ".join(summary_parts) if summary_parts else "—"

    text = (
        f"📋 抽奖列表（共 {len(items)} 条）\n\n"
        f"{summary}\n\n"
        "点击下方按钮查看详情。"
    )
    await callback.message.edit_text(text, reply_markup=admin_lottery_list_kb(items))
    await callback.answer()


# ============ 详情 ============

@router.callback_query(F.data.startswith("admin:lottery:item:"))
@_super_admin_required
async def cb_admin_lottery_item(callback: types.CallbackQuery, state: FSMContext):
    """抽奖详情页（只读）"""
    await state.clear()
    try:
        lid = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    lottery = await get_lottery(lid)
    if not lottery:
        await callback.answer("该抽奖不存在", show_alert=True)
        return

    text = await _render_lottery_detail(lottery)
    try:
        await callback.message.edit_text(text, reply_markup=admin_lottery_detail_kb(lottery))
    except Exception:
        await callback.message.answer(text, reply_markup=admin_lottery_detail_kb(lottery))
    await callback.answer()


async def _render_lottery_detail(lottery: dict) -> str:
    """渲染抽奖详情文字（spec §3.3 风格，含状态 / 时间 / 参与人数）"""
    label_map = {s["key"]: s["label"] for s in LOTTERY_STATUSES}
    status_label = label_map.get(lottery.get("status", ""), lottery.get("status", "?"))

    entry_method = lottery.get("entry_method") or "?"
    method_label = "🎲 按键抽奖" if entry_method == "button" else "🔑 口令抽奖"

    n_entries = await count_lottery_entries(lottery["id"])

    lines = [
        f"🎲 抽奖 #{lottery['id']}",
        "━━━━━━━━━━━━━━━",
        f"📌 状态：{status_label}",
        f"🏷 名称：{lottery.get('name', '?')}",
        f"📋 规则：{lottery.get('description', '?')}",
        f"🎁 奖品：{lottery.get('prize_description', '?')}",
        f"🏆 中奖人数：{lottery.get('prize_count', '?')}",
        f"🎯 参与方式：{method_label}",
    ]
    if entry_method == "code" and lottery.get("entry_code"):
        lines.append(f"🔑 口令：{lottery['entry_code']}")
    chats = lottery.get("required_chat_ids") or []
    lines.append(f"📡 必关频道/群组：{len(chats)} 项")
    if chats:
        for cid in chats[:5]:
            lines.append(f"  · {cid}")
        if len(chats) > 5:
            lines.append(f"  · …（共 {len(chats)} 项）")
    lines.append(f"⏰ 发布时间：{lottery.get('publish_at', '?')}")
    lines.append(f"⏰ 开奖时间：{lottery.get('draw_at', '?')}")
    if lottery.get("published_at"):
        lines.append(f"✅ 已发布：{lottery['published_at']}")
    if lottery.get("drawn_at"):
        lines.append(f"🏆 已开奖：{lottery['drawn_at']}")
    if lottery.get("cover_file_id"):
        lines.append("🖼 已上传封面图")
    lines.append(f"👥 已参与：{n_entries} 人")
    lines.append(f"📝 创建者：uid {lottery.get('created_by', '?')}")
    lines.append(f"⏱ 创建时间：{lottery.get('created_at', '?')}")
    lines.append("━━━━━━━━━━━━━━━")
    return "\n".join(lines)


# ============ 取消草稿（仅 draft 状态）============

@router.callback_query(F.data.startswith("admin:lottery:cancel:"))
@_super_admin_required
async def cb_admin_lottery_cancel(callback: types.CallbackQuery, state: FSMContext):
    """[❌ 取消草稿] 二次确认"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        lid = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    lottery = await get_lottery(lid)
    if not lottery:
        await callback.answer("该抽奖不存在", show_alert=True)
        return
    if lottery.get("status") != "draft":
        await callback.answer(
            f"当前状态 {lottery.get('status')} 不可在本 phase 取消（active 取消见 L.4）",
            show_alert=True,
        )
        return
    await callback.message.edit_text(
        f"⚠️ 确认取消抽奖 #{lid}「{lottery.get('name', '')}」？\n\n"
        "取消后状态变为 cancelled，无法恢复（但记录保留）。",
        reply_markup=admin_lottery_cancel_confirm_kb(lid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:lottery:cancel_ok:"))
@_super_admin_required
async def cb_admin_lottery_cancel_ok(callback: types.CallbackQuery, state: FSMContext):
    """实际取消"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        lid = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    ok = await cancel_lottery(lid)
    if not ok:
        await callback.answer("⚠️ 取消失败（可能已是终态）", show_alert=True)
        return
    # Phase L.2.2：取消已注册的定时任务
    try:
        from bot.scheduler.lottery_tasks import unschedule_lottery
        from bot.main import scheduler as _scheduler
        unschedule_lottery(_scheduler, lid)
    except Exception as e:
        logger.warning("unschedule_lottery 失败 lid=%s: %s", lid, e)
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="lottery_cancel",
        target_type="lottery",
        target_id=str(lid),
        detail={},
    )
    await callback.answer(f"✅ 已取消 #{lid}")
    # 回到列表
    callback.data = "admin:lottery:list"
    await cb_admin_lottery_list(callback, state)


# ============ 立即发布（Phase L.2.1）============

@router.callback_query(F.data.startswith("admin:lottery:publish:"))
@_super_admin_required
async def cb_admin_lottery_publish(callback: types.CallbackQuery, state: FSMContext):
    """[📤 立即发布] 二次确认"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        lid = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    lottery = await get_lottery(lid)
    if not lottery:
        await callback.answer("该抽奖不存在", show_alert=True)
        return
    if lottery.get("status") != "draft":
        await callback.answer(
            f"仅 draft 状态可立即发布；当前 {lottery.get('status')}",
            show_alert=True,
        )
        return
    await callback.message.edit_text(
        f"📤 立即发布抽奖 #{lid}「{lottery.get('name', '')}」？\n\n"
        "发布后 status 变为 active，频道立即出现抽奖帖；用户可开始参与。\n"
        "⚠️ 频道必须已配置 publish_channel_id。",
        reply_markup=admin_lottery_publish_confirm_kb(lid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:lottery:publish_ok:"))
@_super_admin_required
async def cb_admin_lottery_publish_ok(callback: types.CallbackQuery, state: FSMContext):
    """实际发布"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        lid = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    from bot.utils.lottery_publish import (
        LotteryPublishError,
        publish_lottery_to_channel,
    )
    try:
        result = await publish_lottery_to_channel(callback.bot, lid)
    except LotteryPublishError as e:
        await callback.answer(f"❌ {e}", show_alert=True)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="lottery_publish",
        target_type="lottery",
        target_id=str(lid),
        detail={"chat_id": result["chat_id"], "msg_id": result["msg_id"]},
    )
    await callback.answer(f"✅ 已发布到频道（msg_id={result['msg_id']}）")
    # 回到详情页
    callback.data = f"admin:lottery:item:{lid}"
    await cb_admin_lottery_item(callback, state)


# ============ 创建 10 步 FSM (Phase L.1.2) ============

# 各步序号在 spec §3.3 中（含 Step 4.5 / 5 子分支）；UI 显示 Step N/10
_NAME_MAX = 30
_DESCRIPTION_MAX = 500
_ENTRY_CODE_MAX = 20
_PRIZE_DESCRIPTION_MAX = 100
_PRIZE_COUNT_MIN = 1
_PRIZE_COUNT_MAX = 1000


def _parse_datetime_input(text: str) -> Optional[datetime]:
    """解析用户输入 'YYYY-MM-DD HH:MM'；返回 aware datetime（按 config.timezone）

    不支持其它格式 / 含秒等。
    """
    if not text:
        return None
    s = text.strip()
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    tz = timezone(config.timezone)
    return tz.localize(dt)


def _format_datetime_store(dt: datetime) -> str:
    """统一存 'YYYY-MM-DD HH:MM:SS'（与 created_at / publish_at 格式一致）"""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _now_local() -> datetime:
    return datetime.now(timezone(config.timezone))


@router.callback_query(F.data == "admin:lottery:create")
@_super_admin_required
async def cb_admin_lottery_create(callback: types.CallbackQuery, state: FSMContext):
    """[➕ 创建新抽奖] 入口 → Step 1"""
    await state.set_state(LotteryCreateStates.waiting_name)
    await state.set_data({"required_chat_ids": []})
    await callback.message.edit_text(
        "🎲 创建新抽奖（Step 1/10）\n\n"
        "请输入抽奖名称（≤ 30 字）。\n"
        "/cancel 取消。",
        reply_markup=lottery_create_cancel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:lottery:c_cancel")
@_super_admin_required
async def cb_lottery_c_cancel(callback: types.CallbackQuery, state: FSMContext):
    """全程取消 → 回抽奖管理"""
    await state.clear()
    try:
        await callback.message.edit_text(
            "❌ 已取消创建。",
            reply_markup=admin_lottery_menu_kb(await count_lotteries_by_status()),
        )
    except Exception:
        await callback.message.answer(
            "❌ 已取消创建。",
            reply_markup=admin_lottery_menu_kb(await count_lotteries_by_status()),
        )
    await callback.answer("已取消")


@router.message(F.text == "/cancel", LotteryCreateStates())
@_super_admin_required
async def cmd_cancel_lottery_create(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ 已取消创建。",
        reply_markup=admin_lottery_menu_kb(await count_lotteries_by_status()),
    )


# ---- Step 1: name ----

@router.message(LotteryCreateStates.waiting_name, F.text)
@_super_admin_required
async def on_name(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_lottery_create(message, state)
    if not text or len(text) > _NAME_MAX:
        await message.reply(f"❌ 名称 1-{_NAME_MAX} 字，当前 {len(text)}。")
        return
    await state.update_data(name=text)
    await state.set_state(LotteryCreateStates.waiting_description)
    await message.answer(
        f"🎲 创建抽奖（Step 2/10）\n\n"
        f"请输入活动规则 / 备注（1-{_DESCRIPTION_MAX} 字）。",
        reply_markup=lottery_create_cancel_kb(),
    )


# ---- Step 2: description ----

@router.message(LotteryCreateStates.waiting_description, F.text)
@_super_admin_required
async def on_description(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_lottery_create(message, state)
    if not text or len(text) > _DESCRIPTION_MAX:
        await message.reply(f"❌ 规则 1-{_DESCRIPTION_MAX} 字，当前 {len(text)}。")
        return
    await state.update_data(description=text)
    await state.set_state(LotteryCreateStates.waiting_cover)
    await message.answer(
        "🎲 创建抽奖（Step 3/10）\n\n"
        "请发送一张封面图（可跳过）。",
        reply_markup=lottery_create_skip_cancel_kb(),
    )


# ---- Step 3: cover（可跳过）----

@router.message(LotteryCreateStates.waiting_cover, F.photo)
@_super_admin_required
async def on_cover_photo(message: types.Message, state: FSMContext):
    fid = message.photo[-1].file_id
    await state.update_data(cover_file_id=fid)
    await state.set_state(LotteryCreateStates.waiting_entry_method)
    await message.answer(
        "🎲 创建抽奖（Step 4/10）\n\n"
        "请选择参与方式：",
        reply_markup=lottery_create_method_kb(),
    )


@router.callback_query(F.data == "admin:lottery:c_skip_cover")
@_super_admin_required
async def cb_lottery_c_skip_cover(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(cover_file_id=None)
    await state.set_state(LotteryCreateStates.waiting_entry_method)
    await callback.message.edit_text(
        "🎲 创建抽奖（Step 4/10）\n\n"
        "请选择参与方式：",
        reply_markup=lottery_create_method_kb(),
    )
    await callback.answer()


@router.message(LotteryCreateStates.waiting_cover)
@_super_admin_required
async def on_cover_invalid(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_lottery_create(message, state)
    await message.reply(
        "❌ 请发送图片，或点 [⏭ 跳过封面]。",
        reply_markup=lottery_create_skip_cancel_kb(),
    )


# ---- Step 4: entry_method ----

@router.callback_query(F.data.startswith("admin:lottery:c_method:"))
@_super_admin_required
async def cb_lottery_c_method(callback: types.CallbackQuery, state: FSMContext):
    method = callback.data.split(":")[3]
    if method not in {"button", "code"}:
        await callback.answer("未知方式", show_alert=True)
        return
    await state.update_data(entry_method=method)
    if method == "code":
        await state.set_state(LotteryCreateStates.waiting_entry_code)
        await callback.message.edit_text(
            f"🎲 创建抽奖（Step 4.5/10）\n\n"
            f"请输入抽奖口令（1-{_ENTRY_CODE_MAX} 字，区分中英文，全局唯一）。\n"
            "用户在私聊里发该口令参与抽奖。",
            reply_markup=lottery_create_cancel_kb(),
        )
    else:
        await _enter_prize_count_step(callback, state, via_edit=True)
    await callback.answer()


# ---- Step 4.5: entry_code（仅 code 方式）----

@router.message(LotteryCreateStates.waiting_entry_code, F.text)
@_super_admin_required
async def on_entry_code(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_lottery_create(message, state)
    if not text or len(text) > _ENTRY_CODE_MAX:
        await message.reply(f"❌ 口令 1-{_ENTRY_CODE_MAX} 字，当前 {len(text)}。")
        return
    # 全局唯一校验：查 active 抽奖（其它状态不影响新建）
    existing = await find_lottery_by_entry_code(text)
    if existing:
        await message.reply(
            f"❌ 口令 「{text}」 已被使用中（抽奖 #{existing['id']}），请换一个。"
        )
        return
    await state.update_data(entry_code=text)
    await _enter_prize_count_step(message, state, via_edit=False)


# ---- Step 5: prize_count ----

async def _enter_prize_count_step(msg_or_cb, state: FSMContext, *, via_edit: bool):
    await state.set_state(LotteryCreateStates.waiting_prize_count)
    text = (
        f"🎲 创建抽奖（Step 5/10）\n\n"
        f"请选择中奖人数（1-{_PRIZE_COUNT_MAX}），点击下方按钮或自定义：")
    kb = lottery_create_prize_count_kb()
    if via_edit and isinstance(msg_or_cb, types.CallbackQuery):
        try:
            await msg_or_cb.message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            await msg_or_cb.message.answer(text, reply_markup=kb)
    elif isinstance(msg_or_cb, types.Message):
        await msg_or_cb.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("admin:lottery:c_count:"))
@_super_admin_required
async def cb_lottery_c_count(callback: types.CallbackQuery, state: FSMContext):
    try:
        n = int(callback.data.split(":")[3])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    if not (_PRIZE_COUNT_MIN <= n <= _PRIZE_COUNT_MAX):
        await callback.answer("超出范围", show_alert=True)
        return
    await state.update_data(prize_count=n)
    await _enter_prize_description_step(callback, state, via_edit=True)
    await callback.answer()


@router.callback_query(F.data == "admin:lottery:c_count_custom")
@_super_admin_required
async def cb_lottery_c_count_custom(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(LotteryCreateStates.waiting_prize_count_input)
    await callback.message.edit_text(
        f"🎲 创建抽奖（Step 5b/10）\n\n"
        f"请输入中奖人数（{_PRIZE_COUNT_MIN}-{_PRIZE_COUNT_MAX} 整数）。",
        reply_markup=lottery_create_cancel_kb(),
    )
    await callback.answer()


@router.message(LotteryCreateStates.waiting_prize_count_input, F.text)
@_super_admin_required
async def on_prize_count_input(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_lottery_create(message, state)
    try:
        n = int(text)
    except ValueError:
        await message.reply(f"❌ 请输入整数（{_PRIZE_COUNT_MIN}-{_PRIZE_COUNT_MAX}）。")
        return
    if not (_PRIZE_COUNT_MIN <= n <= _PRIZE_COUNT_MAX):
        await message.reply(f"❌ 范围 {_PRIZE_COUNT_MIN}-{_PRIZE_COUNT_MAX}，当前 {n}。")
        return
    await state.update_data(prize_count=n)
    await _enter_prize_description_step(message, state, via_edit=False)


# ---- Step 6: prize_description ----

async def _enter_prize_description_step(msg_or_cb, state: FSMContext, *, via_edit: bool):
    await state.set_state(LotteryCreateStates.waiting_prize_description)
    text = (
        f"🎲 创建抽奖（Step 6/10）\n\n"
        f"请描述奖品（1-{_PRIZE_DESCRIPTION_MAX} 字）。"
    )
    kb = lottery_create_cancel_kb()
    if via_edit and isinstance(msg_or_cb, types.CallbackQuery):
        try:
            await msg_or_cb.message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            await msg_or_cb.message.answer(text, reply_markup=kb)
    elif isinstance(msg_or_cb, types.Message):
        await msg_or_cb.answer(text, reply_markup=kb)


@router.message(LotteryCreateStates.waiting_prize_description, F.text)
@_super_admin_required
async def on_prize_description(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_lottery_create(message, state)
    if not text or len(text) > _PRIZE_DESCRIPTION_MAX:
        await message.reply(
            f"❌ 奖品描述 1-{_PRIZE_DESCRIPTION_MAX} 字，当前 {len(text)}。"
        )
        return
    await state.update_data(prize_description=text)
    await _enter_required_chats_step(message, state)


# ---- Step 7: required_chat_ids（子循环）----

async def _enter_required_chats_step(msg_or_cb, state: FSMContext):
    await state.set_state(LotteryCreateStates.waiting_required_chats)
    data = await state.get_data()
    n = len(data.get("required_chat_ids") or [])
    text = (
        f"🎲 创建抽奖（Step 7/10）\n\n"
        f"请添加本次抽奖要求用户必关的频道/群组（≥ 1 项）。\n"
        f"bot 必须已加入对应频道才能添加成功。\n\n"
        f"当前已添加：{n} 项"
    )
    kb = lottery_create_required_kb(n)
    if isinstance(msg_or_cb, types.CallbackQuery):
        try:
            await msg_or_cb.message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            await msg_or_cb.message.answer(text, reply_markup=kb)
    else:
        await msg_or_cb.answer(text, reply_markup=kb)


@router.callback_query(F.data == "admin:lottery:c_req_add")
@_super_admin_required
async def cb_lottery_c_req_add(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(LotteryCreateStates.waiting_required_chat_id)
    await callback.message.edit_text(
        "🎲 添加必关频道/群组\n\n"
        "请输入 chat_id（数字，通常为负数）。\n"
        "bot 自动校验是否已加入。",
        reply_markup=lottery_create_cancel_kb(),
    )
    await callback.answer()


@router.message(LotteryCreateStates.waiting_required_chat_id, F.text)
@_super_admin_required
async def on_required_chat_id(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_lottery_create(message, state)
    try:
        chat_id = int(text)
    except ValueError:
        await message.reply("❌ 请输入数字 chat_id（可负）。")
        return
    data = await state.get_data()
    chats: list[int] = list(data.get("required_chat_ids") or [])
    if chat_id in chats:
        await message.reply(f"⚠️ 该 chat_id 已添加过（共 {len(chats)} 项）。")
        return
    # precheck：bot 已加入该 chat
    await message.answer("⏳ 校验中...")
    ok, reason, info = await precheck_required_chat(message.bot, chat_id)
    if not ok:
        await message.reply(
            f"❌ 校验失败：{reason}\n"
            "请确认 chat_id 正确且 bot 已加入。"
        )
        return
    chats.append(chat_id)
    await state.update_data(required_chat_ids=chats)
    await message.answer(
        f"✅ 已添加：{info['type']} · {info['title']}（chat_id={chat_id}）"
    )
    await _enter_required_chats_step(message, state)


@router.callback_query(F.data == "admin:lottery:c_req_done")
@_super_admin_required
async def cb_lottery_c_req_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    chats = data.get("required_chat_ids") or []
    if not chats:
        await callback.answer("至少添加 1 个必关频道/群组", show_alert=True)
        return
    await state.set_state(LotteryCreateStates.waiting_publish_mode)
    await callback.message.edit_text(
        f"🎲 创建抽奖（Step 8/10）\n\n"
        f"已添加 {len(chats)} 个必关频道。\n\n"
        "请选择发布模式：",
        reply_markup=lottery_create_publish_mode_kb(),
    )
    await callback.answer()


# ---- Step 8: publish_mode ----

@router.callback_query(F.data.startswith("admin:lottery:c_pub:"))
@_super_admin_required
async def cb_lottery_c_pub(callback: types.CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[3]
    if mode not in {"immediate", "scheduled"}:
        await callback.answer("未知模式", show_alert=True)
        return
    await state.update_data(publish_mode=mode)
    if mode == "immediate":
        # publish_at = 现在
        publish_at = _format_datetime_store(_now_local())
        await state.update_data(publish_at=publish_at)
        await _enter_draw_at_step(callback, state)
    else:
        await state.set_state(LotteryCreateStates.waiting_publish_at)
        await callback.message.edit_text(
            "🎲 创建抽奖（Step 8b/10）\n\n"
            "请输入发布时间（YYYY-MM-DD HH:MM，例：2026-05-20 14:00）。\n"
            f"时区：{config.timezone}",
            reply_markup=lottery_create_cancel_kb(),
        )
    await callback.answer()


@router.message(LotteryCreateStates.waiting_publish_at, F.text)
@_super_admin_required
async def on_publish_at(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_lottery_create(message, state)
    dt = _parse_datetime_input(text)
    if dt is None:
        await message.reply(
            "❌ 格式错误，请用 YYYY-MM-DD HH:MM，例：2026-05-20 14:00"
        )
        return
    if dt < _now_local():
        await message.reply("❌ 发布时间不能早于当前时间。")
        return
    await state.update_data(publish_at=_format_datetime_store(dt))
    await _enter_draw_at_step(message, state)


# ---- Step 9: draw_at ----

async def _enter_draw_at_step(msg_or_cb, state: FSMContext):
    await state.set_state(LotteryCreateStates.waiting_draw_at)
    text = (
        f"🎲 创建抽奖（Step 9/10）\n\n"
        "请输入开奖时间（YYYY-MM-DD HH:MM，必须晚于发布时间）。\n"
        f"时区：{config.timezone}"
    )
    kb = lottery_create_cancel_kb()
    if isinstance(msg_or_cb, types.CallbackQuery):
        try:
            await msg_or_cb.message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            await msg_or_cb.message.answer(text, reply_markup=kb)
    else:
        await msg_or_cb.answer(text, reply_markup=kb)


@router.message(LotteryCreateStates.waiting_draw_at, F.text)
@_super_admin_required
async def on_draw_at(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_lottery_create(message, state)
    dt = _parse_datetime_input(text)
    if dt is None:
        await message.reply(
            "❌ 格式错误，请用 YYYY-MM-DD HH:MM。"
        )
        return
    # 必须晚于 publish_at
    data = await state.get_data()
    pub_at_str = data.get("publish_at") or ""
    try:
        pub_dt = datetime.strptime(pub_at_str, "%Y-%m-%d %H:%M:%S")
        pub_dt = timezone(config.timezone).localize(pub_dt)
    except ValueError:
        pub_dt = None
    if pub_dt and dt <= pub_dt:
        await message.reply(
            f"❌ 开奖时间必须晚于发布时间（{pub_at_str}）。"
        )
        return
    await state.update_data(draw_at=_format_datetime_store(dt))
    await _enter_confirm_step(message, state)


# ---- Step 10: confirm ----

async def _enter_confirm_step(msg_or_cb, state: FSMContext):
    await state.set_state(LotteryCreateStates.waiting_confirm)
    data = await state.get_data()
    method = data.get("entry_method", "?")
    method_label = "🎲 按键抽奖" if method == "button" else "🔑 口令抽奖"
    chats = data.get("required_chat_ids") or []
    pub_mode = data.get("publish_mode", "?")
    pub_label = "⚡ 立即发布" if pub_mode == "immediate" else "⏰ 定时发布"

    lines = [
        "🎲 创建抽奖（Step 10/10 确认）",
        "━━━━━━━━━━━━━━━",
        f"🏷 名称：{data.get('name', '?')}",
        f"📋 规则：{data.get('description', '?')[:100]}",
        f"🖼 封面：{'已上传' if data.get('cover_file_id') else '无'}",
        f"🎯 方式：{method_label}",
    ]
    if method == "code":
        lines.append(f"🔑 口令：{data.get('entry_code', '?')}")
    lines.extend([
        f"🎁 奖品：{data.get('prize_description', '?')}",
        f"🏆 中奖人数：{data.get('prize_count', '?')}",
        f"📡 必关频道：{len(chats)} 项",
        f"⏰ 发布方式：{pub_label}",
        f"⏰ 发布时间：{data.get('publish_at', '?')}",
        f"⏰ 开奖时间：{data.get('draw_at', '?')}",
        "━━━━━━━━━━━━━━━",
        "确认后保存为草稿（status=draft），L.2 实施后才会发到频道。",
    ])
    text = "\n".join(lines)
    kb = lottery_create_confirm_kb()
    if isinstance(msg_or_cb, types.CallbackQuery):
        try:
            await msg_or_cb.message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            await msg_or_cb.message.answer(text, reply_markup=kb)
    else:
        await msg_or_cb.answer(text, reply_markup=kb)


@router.callback_query(F.data == "admin:lottery:c_save")
@_super_admin_required
async def cb_lottery_c_save(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    # 必填校验（防御）
    required_keys = ["name", "description", "entry_method", "prize_count",
                     "prize_description", "required_chat_ids",
                     "publish_at", "draw_at"]
    missing = [k for k in required_keys if data.get(k) is None]
    if missing:
        await callback.answer(f"缺字段：{missing[0]}", show_alert=True)
        return
    if data.get("entry_method") == "code" and not data.get("entry_code"):
        await callback.answer("口令抽奖必须填口令", show_alert=True)
        return

    # 立即发布模式：保存为 draft 后立即调 publish_lottery_to_channel
    # 定时发布模式：保存为 scheduled + 注册 APScheduler publish job
    publish_mode = data.get("publish_mode") or "scheduled"
    init_status = "draft" if publish_mode == "immediate" else "scheduled"

    lid = await create_lottery({
        **data,
        "created_by": callback.from_user.id,
        "status": init_status,
    })
    if lid is None:
        await callback.answer("⚠️ 保存失败（可能口令冲突）", show_alert=True)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="lottery_create",
        target_type="lottery",
        target_id=str(lid),
        detail={
            "name": data.get("name"),
            "entry_method": data.get("entry_method"),
            "prize_count": data.get("prize_count"),
            "publish_at": data.get("publish_at"),
            "draw_at": data.get("draw_at"),
            "publish_mode": publish_mode,
        },
    )
    await state.clear()

    # Phase L.2.2：根据 publish_mode 触发立即发布 / 注册定时任务
    from bot.utils.lottery_publish import (
        LotteryPublishError,
        publish_lottery_to_channel,
    )
    from bot.scheduler.lottery_tasks import (
        schedule_lottery_draw,
        schedule_lottery_publish,
    )

    extra = ""
    if publish_mode == "immediate":
        try:
            result = await publish_lottery_to_channel(callback.bot, lid)
            extra = f"已立即发布到频道（msg_id={result['msg_id']}）。"
        except LotteryPublishError as e:
            extra = f"⚠️ 立即发布失败：{e}（已保存为 draft）"
            logger.warning("即时发布失败 lid=%s reason=%s: %s", lid, e.reason, e)
    else:
        # 定时发布：注册发布定时任务（开奖任务统一注册）
        from bot.database import get_lottery as _get_lottery
        lot = await _get_lottery(lid)
        from bot.main import scheduler as _scheduler
        if lot and schedule_lottery_publish(_scheduler, callback.bot, lot):
            extra = f"已注册定时发布任务（publish_at={lot['publish_at']}）。"
        else:
            extra = "⚠️ 定时任务注册失败（请检查 publish_at 格式）"

    # 开奖任务统一注册（L.3 实际执行；本 phase 占位 log）
    try:
        from bot.database import get_lottery as _get_lottery2
        lot2 = await _get_lottery2(lid)
        from bot.main import scheduler as _scheduler2
        if lot2:
            schedule_lottery_draw(_scheduler2, callback.bot, lot2)
    except Exception as e:
        logger.warning("schedule_lottery_draw 失败 lid=%s: %s", lid, e)

    await callback.message.edit_text(
        f"✅ 抽奖 #{lid}「{data.get('name')}」已保存。\n\n{extra}",
        reply_markup=admin_lottery_menu_kb(await count_lotteries_by_status()),
    )
    await callback.answer("✅ 保存成功")
