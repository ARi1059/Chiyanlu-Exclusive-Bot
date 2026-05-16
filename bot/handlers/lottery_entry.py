"""用户抽奖参与流程（Phase L.2.3）

两个入口：
1. `/start lottery_<id>` deep link（在 start_router 处理）
2. 私聊文字命中 entry_code 口令（本文件 message handler）

流程（spec §2 / §8）：
1. 校验抽奖 active 状态
2. 时间窗：publish_at <= now < draw_at
3. 重复参与：UNIQUE(lottery_id, user_id) 已在 DB 层防（create_lottery_entry 冲突返 None）
4. 关注校验：必关频道全部 member/admin/creator → 通过
5. 创建 entry → 异步 update_lottery_entry_count
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from aiogram import Bot, Router, types, F
from pytz import timezone

from bot.config import config
from bot.database import (
    create_lottery_entry,
    find_lottery_by_entry_code,
    get_lottery,
    get_lottery_entry,
    log_admin_audit,
)
from bot.utils.lottery_subscribe_check import (
    check_user_subscribed_to_chats,
    render_lottery_subscribe_links_kb,
)

logger = logging.getLogger(__name__)

router = Router(name="lottery_entry")


def _now_local() -> datetime:
    return datetime.now(timezone(config.timezone))


def _parse_db_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return timezone(config.timezone).localize(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None


async def try_enter_lottery(
    bot: Bot,
    user_id: int,
    lottery: dict,
    *,
    source: str,
) -> tuple[str, dict]:
    """尝试参与抽奖（统一入口；deep link / 口令命中共用）

    Returns: (status, extra)
        ok                 → entry 创建成功
        not_active         → 抽奖非 active
        time_window        → 未到 publish_at 或已过 draw_at
        already_entered    → 已参与
        need_subscribe     → 未关注必关频道（extra={'missing': list}）

    source：deep_link / code（写 audit detail）
    """
    lid = int(lottery["id"])
    status = lottery.get("status")
    if status != "active":
        return "not_active", {"status": status}

    # 时间窗校验
    now = _now_local()
    pub_at = _parse_db_dt(lottery.get("publish_at"))
    draw_at = _parse_db_dt(lottery.get("draw_at"))
    if pub_at and now < pub_at:
        return "time_window", {"reason": "未到发布时间"}
    if draw_at and now >= draw_at:
        return "time_window", {"reason": "抽奖已结束"}

    # 重复参与（防御性，DB 也有 UNIQUE）
    existing = await get_lottery_entry(lid, user_id)
    if existing:
        return "already_entered", {}

    # 关注校验
    chat_ids = lottery.get("required_chat_ids") or []
    if chat_ids:
        ok, missing = await check_user_subscribed_to_chats(bot, user_id, chat_ids)
        if not ok:
            return "need_subscribe", {"missing": missing}

    # 创建 entry
    entry_id = await create_lottery_entry(lid, user_id)
    if entry_id is None:
        # UNIQUE 冲突（并发场景）
        return "already_entered", {}

    # audit
    try:
        await log_admin_audit(
            admin_id=user_id,
            action="lottery_entry",
            target_type="lottery",
            target_id=str(lid),
            detail={"source": source, "entry_id": entry_id},
        )
    except Exception:
        pass

    # 异步刷新频道帖计数（不阻塞用户响应）
    try:
        from bot.utils.lottery_publish import update_lottery_entry_count
        asyncio.create_task(update_lottery_entry_count(bot, lid))
    except Exception as e:
        logger.warning("update_lottery_entry_count schedule 失败 lid=%s: %s", lid, e)

    return "ok", {"entry_id": entry_id, "lottery_id": lid}


async def _render_entry_result(
    bot: Bot,
    user_id: int,
    chat_id: int,
    lottery: dict,
    status: str,
    extra: dict,
) -> None:
    """统一渲染参与结果到私聊"""
    lid = lottery.get("id")
    name = lottery.get("name", "?")
    if status == "ok":
        text = (
            f"✅ 你已参与「{name}」抽奖\n\n"
            f"开奖时间：{lottery.get('draw_at')}\n"
            "请耐心等待，中奖会私聊通知。"
        )
        await bot.send_message(chat_id=chat_id, text=text)
        return
    if status == "not_active":
        s = extra.get("status", "?")
        text = (
            f"⚠️ 抽奖「{name}」当前状态为 {s}，无法参与。\n"
            "（已结束 / 已取消 / 还未发布）"
        )
        await bot.send_message(chat_id=chat_id, text=text)
        return
    if status == "time_window":
        reason = extra.get("reason", "时间窗外")
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ 「{name}」{reason}，无法参与。",
        )
        return
    if status == "already_entered":
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ 你已参与「{name}」，每人仅可参与 1 次。",
        )
        return
    if status == "need_subscribe":
        missing = extra.get("missing") or []
        text, kb = render_lottery_subscribe_links_kb(missing)
        text = f"参与「{name}」抽奖前\n\n" + text
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb,
                               disable_web_page_preview=True)
        return
    # 未知 status
    await bot.send_message(chat_id=chat_id, text=f"⚠️ 处理失败：{status}")


async def start_lottery_from_deep_link(
    bot: Bot,
    user_id: int,
    chat_id: int,
    lottery_id: int,
) -> None:
    """由 start_router 在 /start lottery_<id> 时调用"""
    lottery = await get_lottery(lottery_id)
    if lottery is None:
        await bot.send_message(chat_id=chat_id, text="⚠️ 该抽奖不存在或已删除。")
        return
    status, extra = await try_enter_lottery(
        bot, user_id, lottery, source="deep_link",
    )
    await _render_entry_result(bot, user_id, chat_id, lottery, status, extra)


# ============ 私聊口令命中 ============

# 口令长度限制（spec §3.3 step 4.5 ≤ 20 字）
_CODE_MAX_LEN = 20


@router.message(F.chat.type == "private", F.text)
async def on_private_text_maybe_code(message: types.Message):
    """私聊文字 → 尝试匹配抽奖口令（find_lottery_by_entry_code 仅 active）

    注意：本 handler 在 keyword 之前注册；F.text 排除 photo/sticker；
    `F.chat.type == "private"` 排除群组消息。
    若文字不匹配任何 active 抽奖 → silent skip（不响应，留给后续 router）。
    """
    text = (message.text or "").strip()
    if not text or len(text) > _CODE_MAX_LEN:
        return
    # 跳过 / 开头的命令（不当作口令）
    if text.startswith("/"):
        return
    lottery = await find_lottery_by_entry_code(text)
    if lottery is None:
        return
    if lottery.get("entry_method") != "code":
        return  # 防御：理论上 find_by_entry_code 已限制
    user_id = message.from_user.id if message.from_user else 0
    status, extra = await try_enter_lottery(
        message.bot, user_id, lottery, source="code",
    )
    await _render_entry_result(
        message.bot, user_id, message.chat.id, lottery, status, extra,
    )
