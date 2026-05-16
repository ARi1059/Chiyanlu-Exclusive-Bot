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
    get_users_first_names,
    is_super_admin,
    list_lotteries_by_status,
    list_lottery_entries_paged,
    log_admin_audit,
    set_config,
    update_lottery_fields,
)
from bot.keyboards.admin_kb import (
    admin_lottery_cancel_confirm_kb,
    admin_lottery_detail_kb,
    admin_lottery_edit_field_kb,
    admin_lottery_entries_pagination_kb,
    admin_lottery_list_kb,
    admin_lottery_menu_kb,
    admin_lottery_publish_confirm_kb,
    admin_lottery_repost_confirm_kb,
    lottery_contact_cancel_kb,
    lottery_create_cancel_kb,
    lottery_create_confirm_kb,
    lottery_create_cost_cancel_kb,
    lottery_create_method_kb,
    lottery_create_prize_count_kb,
    lottery_create_publish_mode_kb,
    lottery_create_required_kb,
    lottery_create_skip_cancel_kb,
    lottery_edit_cancel_kb,
)
from bot.states.teacher_states import (
    LotteryContactUrlStates,
    LotteryCreateStates,
    LotteryEditStates,
)
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
        f"💰 参与消耗：{lottery.get('entry_cost_points', 0)} 积分",
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


# ============ 参与人员列表（Phase L.4.1）============

# 参与人员分页每页条数
_ENTRIES_PAGE_SIZE = 20


def _anon_uid_short(uid: int) -> str:
    """半匿名：****<uid 后 4>"""
    s = str(uid)
    if len(s) <= 4:
        return "****"
    return "*" * 4 + s[-4:]


@router.callback_query(F.data.startswith("admin:lottery:entries:"))
@_super_admin_required
async def cb_admin_lottery_entries(callback: types.CallbackQuery, state: FSMContext):
    """[👥 查看参与人员] 分页列表（半匿名 + 🏆 中奖标记）"""
    await state.clear()
    parts = callback.data.split(":")
    # admin:lottery:entries:<lid> or :<lid>:<page>
    if len(parts) < 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        lid = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    page = 0
    if len(parts) >= 5:
        try:
            page = max(0, int(parts[4]))
        except ValueError:
            page = 0

    lottery = await get_lottery(lid)
    if not lottery:
        await callback.answer("抽奖不存在", show_alert=True)
        return
    total = await count_lottery_entries(lid)
    if total == 0:
        text = (
            f"👥 抽奖 #{lid}「{lottery.get('name', '')}」参与人员\n\n"
            "ℹ️ 暂无参与者。"
        )
        try:
            await callback.message.edit_text(
                text, reply_markup=admin_lottery_detail_kb(lottery),
            )
        except Exception:
            pass
        await callback.answer()
        return

    total_pages = (total + _ENTRIES_PAGE_SIZE - 1) // _ENTRIES_PAGE_SIZE
    if page >= total_pages:
        page = total_pages - 1
    offset = page * _ENTRIES_PAGE_SIZE
    entries = await list_lottery_entries_paged(lid, _ENTRIES_PAGE_SIZE, offset)

    # 批量取 first_name 做半匿名
    uids = list({int(e["user_id"]) for e in entries})
    names = await get_users_first_names(uids)

    lines = [
        f"👥 抽奖 #{lid}「{lottery.get('name', '')}」参与人员",
        f"共 {total} 人 · 第 {page + 1}/{total_pages} 页",
        "─" * 20,
    ]
    for i, e in enumerate(entries, start=offset + 1):
        uid = int(e["user_id"])
        first = names.get(uid) or ""
        initial = first[0] if first else "匿"
        won_mark = "🏆" if e.get("won") == 1 else "  "
        entered = (e.get("entered_at") or "")[:16]
        notif = "✉" if e.get("notified_at") else "  "
        lines.append(
            f"{i}. {won_mark} {initial}* {_anon_uid_short(uid)}  {notif}  — {entered}"
        )
    lines.append("─" * 20)
    lines.append("说明：🏆=中奖  ✉=已私聊通知")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…(截断)"

    try:
        await callback.message.edit_text(
            text,
            reply_markup=admin_lottery_entries_pagination_kb(lid, page, total_pages),
        )
    except Exception:
        # 同样内容 BadRequest 静默
        pass
    await callback.answer()


# ============ 重发抽奖帖（Phase L.4.1）============

@router.callback_query(F.data.startswith("admin:lottery:repost:"))
@_super_admin_required
async def cb_admin_lottery_repost(callback: types.CallbackQuery, state: FSMContext):
    """[🔄 重发抽奖帖] 二次确认（仅 active 状态）"""
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
        await callback.answer("抽奖不存在", show_alert=True)
        return
    if lottery.get("status") != "active":
        await callback.answer("仅 active 状态可重发", show_alert=True)
        return
    await callback.message.edit_text(
        f"🔄 重发抽奖帖 #{lid}「{lottery.get('name', '')}」？\n\n"
        "原帖在频道里如果被删除（或 chat_id 改了），点确认将重新 send_message 一份；\n"
        "channel_msg_id 会更新为新消息 id，原帖（如仍在）保留不删。\n\n"
        "如果原帖还在频道，重发会让频道出现两条相同抽奖（旧的不删）。",
        reply_markup=admin_lottery_repost_confirm_kb(lid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:lottery:repost_ok:"))
@_super_admin_required
async def cb_admin_lottery_repost_ok(callback: types.CallbackQuery, state: FSMContext):
    """实际重发：临时改 status='draft' → publish_lottery_to_channel → 恢复 active"""
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
        await callback.answer("抽奖不存在", show_alert=True)
        return
    if lottery.get("status") != "active":
        await callback.answer("仅 active 状态可重发", show_alert=True)
        return

    # 临时降级到 draft 让 publish_lottery_to_channel 不报 not_publishable
    await update_lottery_fields(lid, status="draft")
    from bot.utils.lottery_publish import (
        LotteryPublishError, publish_lottery_to_channel,
    )
    try:
        result = await publish_lottery_to_channel(callback.bot, lid)
    except LotteryPublishError as e:
        # 失败时回滚 status
        await update_lottery_fields(lid, status="active")
        await callback.answer(f"❌ {e}", show_alert=True)
        return
    # publish 成功后内部已 mark_lottery_published → status=active；这里防御性再确认
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="lottery_repost",
        target_type="lottery",
        target_id=str(lid),
        detail={"chat_id": result["chat_id"], "msg_id": result["msg_id"]},
    )
    await callback.answer(f"✅ 重发成功（新 msg_id={result['msg_id']}）")
    callback.data = f"admin:lottery:item:{lid}"
    await cb_admin_lottery_item(callback, state)


# ============ 客服链接配置（Phase L.4.1）============

async def _enter_contact_url_fsm(
    target_message: types.Message, state: FSMContext, *, edit: bool = True,
):
    """统一进 FSM 文案（系统设置 + 抽奖管理双入口复用）"""
    from bot.database import get_config
    current = await get_config("lottery_contact_url")
    current_line = (
        f"当前值：{current}" if current else "当前值：（未配置）"
    )
    await state.set_state(LotteryContactUrlStates.waiting_url)
    text = (
        "👨‍💼 抽奖客服链接配置\n\n"
        f"{current_line}\n\n"
        "请输入 t.me 链接（如 https://t.me/admin）或 @username。\n"
        "回复 0 清空配置（中奖通知将不带按钮）。\n"
        "/cancel 取消。"
    )
    kb = lottery_contact_cancel_kb()
    if edit:
        try:
            await target_message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await target_message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "admin:lottery:contact")
@_super_admin_required
async def cb_admin_lottery_contact(callback: types.CallbackQuery, state: FSMContext):
    """[👨‍💼 抽奖客服链接] 入口（抽奖管理子菜单）"""
    await _enter_contact_url_fsm(callback.message, state, edit=True)
    await callback.answer()


@router.message(F.text == "/cancel", LotteryContactUrlStates())
@_super_admin_required
async def cmd_cancel_contact_url(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ 已取消。",
        reply_markup=admin_lottery_menu_kb(await count_lotteries_by_status()),
    )


@router.message(LotteryContactUrlStates.waiting_url, F.text)
@_super_admin_required
async def on_lottery_contact_url(message: types.Message, state: FSMContext):
    """接收客服链接 URL；存 config + audit"""
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_contact_url(message, state)
    # 清空
    if text == "0":
        await set_config("lottery_contact_url", "")
        await log_admin_audit(
            admin_id=message.from_user.id,
            action="lottery_contact_set",
            target_type="config",
            target_id="lottery_contact_url",
            detail={"value": ""},
        )
        await state.clear()
        await message.answer(
            "✅ 已清空客服链接。中奖通知将不附按钮，文字提示用户联系频道管理员。",
            reply_markup=admin_lottery_menu_kb(await count_lotteries_by_status()),
        )
        return
    # @username → t.me/xxx
    candidate = text
    if candidate.startswith("@"):
        name = candidate.lstrip("@")
        if name and name.replace("_", "").isalnum():
            candidate = f"https://t.me/{name}"
    # URL 校验
    from bot.utils.url import normalize_url
    url = normalize_url(candidate)
    if not url or not url.startswith("https://t.me/") and not url.startswith("http://t.me/"):
        await message.reply(
            "❌ 请输入 t.me 链接（如 https://t.me/admin 或 @admin），"
            "回复 0 清空，或 /cancel 取消。"
        )
        return
    await set_config("lottery_contact_url", url)
    await log_admin_audit(
        admin_id=message.from_user.id,
        action="lottery_contact_set",
        target_type="config",
        target_id="lottery_contact_url",
        detail={"value": url},
    )
    await state.clear()
    await message.answer(
        f"✅ 客服链接已设置：{url}\n"
        "中奖通知将附 [👨‍💼 联系管理员] 按钮跳转此链接。",
        reply_markup=admin_lottery_menu_kb(await count_lotteries_by_status()),
    )


# ============ active 编辑 FSM（Phase L.4.2）============

# 可编辑字段元数据：label / 类型 / 校验提示
_EDITABLE_FIELDS: dict[str, dict] = {
    "name":               {"label": "名称",       "type": "str",      "max": 30},
    "description":        {"label": "活动规则",   "type": "str",      "max": 500},
    "prize_description":  {"label": "奖品描述",   "type": "str",      "max": 100},
    "prize_count":        {"label": "中奖人数",   "type": "int_range", "min": 1, "max": 1000},
    "entry_cost_points":  {"label": "参与所需积分", "type": "int_range", "min": 0, "max": 1000000},
    "required_chat_ids":  {"label": "必关频道/群组", "type": "chat_ids"},
    "draw_at":            {"label": "开奖时间",   "type": "datetime"},
}


def _format_current_value(lottery: dict, field: str) -> str:
    v = lottery.get(field)
    if field == "required_chat_ids":
        if not v:
            return "（无门槛）"
        return ", ".join(str(x) for x in v)
    if v is None or v == "":
        return "（未设置）"
    return str(v)


@router.callback_query(F.data.startswith("admin:lottery:edit:"))
@_super_admin_required
async def cb_admin_lottery_edit(callback: types.CallbackQuery, state: FSMContext):
    """[✏️ 编辑] 入口（仅 active）"""
    await state.clear()
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
    if lottery.get("status") != "active":
        await callback.answer(
            f"仅 active 状态可编辑；当前 {lottery.get('status')}",
            show_alert=True,
        )
        return
    await state.set_state(LotteryEditStates.waiting_field_choice)
    await state.set_data({"lottery_id": lid})
    text = (
        f"✏️ 编辑抽奖 #{lid}「{lottery.get('name', '')}」\n\n"
        "请选择要修改的字段：\n"
        "（封面 / 参与方式 / 口令不可改；如需大改请新建抽奖）"
    )
    try:
        await callback.message.edit_text(text, reply_markup=admin_lottery_edit_field_kb(lid))
    except Exception:
        await callback.message.answer(text, reply_markup=admin_lottery_edit_field_kb(lid))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:lottery:edit_field:"))
@_super_admin_required
async def cb_admin_lottery_edit_field(callback: types.CallbackQuery, state: FSMContext):
    """选某字段 → 显示当前值 + 进 FSM 等输入"""
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        lid = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    field = parts[4]
    if field not in _EDITABLE_FIELDS:
        await callback.answer("不支持该字段", show_alert=True)
        return
    lottery = await get_lottery(lid)
    if not lottery:
        await callback.answer("该抽奖不存在", show_alert=True)
        return
    if lottery.get("status") != "active":
        await callback.answer(
            f"仅 active 状态可编辑；当前 {lottery.get('status')}",
            show_alert=True,
        )
        return
    meta = _EDITABLE_FIELDS[field]
    current = _format_current_value(lottery, field)
    hint_lines = [f"✏️ 编辑：{meta['label']}", "", f"当前值：{current}", ""]
    if meta["type"] == "str":
        hint_lines.append(f"请输入新值（≤ {meta['max']} 字）。")
    elif meta["type"] == "int_range":
        hint_lines.append(f"请输入新数值（{meta['min']}-{meta['max']} 整数）。")
    elif meta["type"] == "datetime":
        now = _now_local().strftime("%Y-%m-%d %H:%M")
        hint_lines.append(f"请输入新时间，格式 YYYY-MM-DD HH:MM（必须晚于现在 {now}）。")
    elif meta["type"] == "chat_ids":
        hint_lines.append(
            "请输入 chat_id 列表（逗号分隔，bot 必须已加入；回复 0 清空门槛）。\n"
            "示例：-1001234567890, -1009876543210"
        )
    hint_lines.append("/cancel 取消。")
    await state.set_state(LotteryEditStates.waiting_new_value)
    await state.set_data({"lottery_id": lid, "field_key": field})
    try:
        await callback.message.edit_text(
            "\n".join(hint_lines),
            reply_markup=lottery_edit_cancel_kb(lid),
        )
    except Exception:
        await callback.message.answer(
            "\n".join(hint_lines),
            reply_markup=lottery_edit_cancel_kb(lid),
        )
    await callback.answer()


@router.message(F.text == "/cancel", LotteryEditStates())
@_super_admin_required
async def cmd_cancel_lottery_edit(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lid = data.get("lottery_id")
    await state.clear()
    if lid:
        lottery = await get_lottery(int(lid))
        if lottery:
            text = await _render_lottery_detail(lottery)
            await message.answer(text, reply_markup=admin_lottery_detail_kb(lottery))
            return
    await message.answer("❌ 已取消。")


@router.message(LotteryEditStates.waiting_new_value, F.text)
@_super_admin_required
async def on_lottery_edit_value(message: types.Message, state: FSMContext):
    """接收编辑值；按字段类型校验 + DB 更新 + 频道刷新 + 必要时 reschedule"""
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_lottery_edit(message, state)
    data = await state.get_data()
    lid = data.get("lottery_id")
    field = data.get("field_key")
    if not lid or field not in _EDITABLE_FIELDS:
        await state.clear()
        await message.reply("⚠️ 会话失效，请重新进入 [✏️ 编辑]。")
        return
    lottery = await get_lottery(int(lid))
    if not lottery or lottery.get("status") != "active":
        await state.clear()
        await message.reply("⚠️ 抽奖状态变更，无法编辑。")
        return
    meta = _EDITABLE_FIELDS[field]
    old_value = lottery.get(field)

    # ---- 校验 + 解析 new_value ----
    new_value = None
    if meta["type"] == "str":
        if not text:
            await message.reply("❌ 不能为空。")
            return
        if len(text) > meta["max"]:
            await message.reply(f"❌ 超长（最多 {meta['max']} 字）。")
            return
        new_value = text
    elif meta["type"] == "int_range":
        if not text.lstrip("-").isdigit():
            await message.reply("❌ 请输入整数。")
            return
        n = int(text)
        if not (meta["min"] <= n <= meta["max"]):
            await message.reply(f"❌ 取值范围 {meta['min']}-{meta['max']}。")
            return
        new_value = n
    elif meta["type"] == "datetime":
        dt = _parse_datetime_input(text)
        if dt is None:
            await message.reply("❌ 格式错误（YYYY-MM-DD HH:MM）。")
            return
        if dt <= _now_local():
            await message.reply("❌ 开奖时间必须晚于当前时间。")
            return
        new_value = _format_datetime_store(dt)
    elif meta["type"] == "chat_ids":
        if text == "0":
            new_value = []
        else:
            raw_ids = [p.strip() for p in text.split(",") if p.strip()]
            parsed: list[int] = []
            for raw in raw_ids:
                try:
                    parsed.append(int(raw))
                except ValueError:
                    await message.reply(f"❌ '{raw}' 不是有效 chat_id。")
                    return
            if len(parsed) != len(set(parsed)):
                await message.reply("❌ chat_id 重复。")
                return
            # 逐个 precheck（bot 必须在场）
            failures: list[str] = []
            for cid in parsed:
                ok, reason, _ = await precheck_required_chat(message.bot, cid)
                if not ok:
                    failures.append(f"{cid}: {reason}")
            if failures:
                await message.reply(
                    "❌ 校验失败：\n" + "\n".join(failures[:5]) +
                    ("\n…" if len(failures) > 5 else "")
                )
                return
            new_value = parsed

    # ---- DB 更新 ----
    ok = await update_lottery_fields(int(lid), **{field: new_value})
    if not ok:
        await message.reply("⚠️ 更新失败（DB 未变化）。")
        return

    await log_admin_audit(
        admin_id=message.from_user.id,
        action="lottery_edit",
        target_type="lottery",
        target_id=str(lid),
        detail={"field": field, "old": old_value, "new": new_value},
    )

    # ---- 副作用：reschedule draw 或 刷新频道 caption ----
    side_effects: list[str] = []
    if field == "draw_at":
        try:
            from bot.scheduler.lottery_tasks import (
                schedule_lottery_draw, unschedule_lottery,
            )
            from bot.main import scheduler as _scheduler
            unschedule_lottery(_scheduler, int(lid))
            fresh = await get_lottery(int(lid))
            if fresh and schedule_lottery_draw(_scheduler, message.bot, fresh):
                side_effects.append("⏰ 开奖定时任务已重注册")
            else:
                side_effects.append("⚠️ reschedule 失败（请检查日志）")
        except Exception as e:
            logger.warning("reschedule draw 失败 lid=%s: %s", lid, e)
            side_effects.append("⚠️ reschedule 异常（不影响 DB）")

    # 文字 / 数量 / required → 频道 caption 刷新
    if field in {"name", "description", "prize_description", "prize_count", "required_chat_ids", "draw_at"}:
        try:
            from bot.utils.lottery_publish import refresh_lottery_channel_caption
            refreshed = await refresh_lottery_channel_caption(message.bot, int(lid))
            if refreshed:
                side_effects.append("📣 频道帖已刷新")
        except Exception as e:
            logger.warning("refresh caption 失败 lid=%s: %s", lid, e)
            side_effects.append("⚠️ 频道刷新异常")

    await state.clear()
    lines = [
        f"✅ {meta['label']} 已更新",
        f"旧值：{_format_current_value(lottery, field)}",
        f"新值：{_format_current_value({field: new_value}, field)}",
    ]
    lines.extend(side_effects)
    fresh = await get_lottery(int(lid))
    await message.answer(
        "\n".join(lines),
        reply_markup=admin_lottery_detail_kb(fresh or lottery),
    )


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
    cost = int(data.get("entry_cost_points") or 0)
    cost_text = f"{cost} 积分" if cost > 0 else "免费"
    lines.extend([
        f"🎁 奖品：{data.get('prize_description', '?')}",
        f"🏆 中奖人数：{data.get('prize_count', '?')}",
        f"💰 参与消耗：{cost_text}",
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


@router.callback_query(F.data == "admin:lottery:c_set_cost")
@_super_admin_required
async def cb_lottery_c_set_cost(callback: types.CallbackQuery, state: FSMContext):
    """Step 10 确认页 [💰 设置参与所需积分] → 进 waiting_entry_cost_input"""
    data = await state.get_data()
    current = int(data.get("entry_cost_points") or 0)
    await state.set_state(LotteryCreateStates.waiting_entry_cost_input)
    text = (
        "💰 设置参与所需积分\n\n"
        f"当前值：{current if current > 0 else '免费（0 积分）'}\n\n"
        "请输入整数（0-1000000；0 = 免费）。\n"
        "用户点击参与时会自动扣分，余额不足无法参与。"
    )
    try:
        await callback.message.edit_text(text, reply_markup=lottery_create_cost_cancel_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=lottery_create_cost_cancel_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:lottery:c_cost_back")
@_super_admin_required
async def cb_lottery_c_cost_back(callback: types.CallbackQuery, state: FSMContext):
    """设置参与积分子流程取消 → 回 Step 10 确认页"""
    await _enter_confirm_step(callback, state)
    await callback.answer()


@router.message(LotteryCreateStates.waiting_entry_cost_input, F.text)
@_super_admin_required
async def on_entry_cost_input(message: types.Message, state: FSMContext):
    """接收参与积分数值，回 Step 10"""
    text = (message.text or "").strip()
    if not text.lstrip("-").isdigit():
        await message.reply("❌ 请输入整数（0-1000000）。")
        return
    n = int(text)
    if not (0 <= n <= 1000000):
        await message.reply("❌ 取值范围 0-1000000。")
        return
    await state.update_data(entry_cost_points=n)
    label = f"{n} 积分" if n > 0 else "免费"
    await message.answer(f"✅ 参与所需积分已设为：{label}")
    await _enter_confirm_step(message, state)


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
