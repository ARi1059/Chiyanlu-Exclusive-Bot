"""抽奖开奖逻辑（Phase L.3）

到 draw_at 时 APScheduler 调 draw_job → run_lottery_draw
用 secrets.SystemRandom（CSPRNG，/dev/urandom）等概率抽取 winners。

防重：仅 status='active' 才能开奖；drawn / cancelled / no_entries 跳过。

L.3.1：DB 抽签 + 状态变更
L.3.2：频道结果发布 + 私聊中奖者
"""
from __future__ import annotations

import logging
import random
import secrets
from typing import Optional

from aiogram import Bot

from bot.database import (
    get_lottery,
    list_lottery_entries_for_draw,
    mark_lottery_drawn,
    mark_lottery_entries_won,
    mark_lottery_no_entries,
)

logger = logging.getLogger(__name__)


class LotteryDrawError(Exception):
    """开奖错误

    reason ∈ {not_found / not_drawable / api_error}
    """
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _pick_winners(entries: list[dict], k: int) -> list[dict]:
    """从 entries 用 CSPRNG 等概率抽 k 个 winner（无重复）

    spec §5.1 / §8 容错：
      - 优先 secrets.SystemRandom().sample
      - 失败回退 random.SystemRandom().sample + log warning
      - k > len(entries) → 全选
    """
    if not entries:
        return []
    n = min(int(k), len(entries))
    if n <= 0:
        return []
    try:
        rng = secrets.SystemRandom()
        return rng.sample(list(entries), n)
    except Exception as e:
        logger.warning("secrets.SystemRandom 失败，回退 random.SystemRandom: %s", e)
        try:
            rng2 = random.SystemRandom()
            return rng2.sample(list(entries), n)
        except Exception as e2:
            logger.warning("random.SystemRandom 也失败: %s", e2)
            # 极端情况：返回前 n 个（不应发生；保证流程能继续 + 标记）
            return list(entries)[:n]


async def run_lottery_draw(bot: Bot, lottery_id: int) -> dict:
    """开奖主入口（被 draw_job 调）

    spec §5.1：
        1. get_lottery + 校验 status='active'（其它跳过）
        2. list_lottery_entries_for_draw
        3. 0 条 → mark_lottery_no_entries
        4. ≥ 1 条 → _pick_winners → mark_lottery_entries_won
        5. mark_lottery_drawn
        6. publish_lottery_result（频道追发，L.3.2）
        7. notify_winners（私聊中奖者，L.3.2）

    Returns: {winners_count, total_entries, result_msg_id, no_entries}

    幂等：drawn / cancelled / no_entries → silent skip 返回空字典。
    """
    lottery = await get_lottery(lottery_id)
    if lottery is None:
        raise LotteryDrawError("not_found", f"抽奖 {lottery_id} 不存在")

    status = lottery.get("status")
    if status != "active":
        logger.info(
            "run_lottery_draw 跳过 lid=%s（状态 %s 非 active）",
            lottery_id, status,
        )
        return {
            "winners_count": 0,
            "total_entries": 0,
            "result_msg_id": None,
            "no_entries": False,
            "skipped": True,
            "reason": f"status={status}",
        }

    entries = await list_lottery_entries_for_draw(lottery_id)
    total = len(entries)

    # 0 条 → no_entries 终态
    if total == 0:
        await mark_lottery_no_entries(lottery_id)
        result_msg_id = await _try_publish_no_entries(bot, lottery)
        logger.info(
            "run_lottery_draw lid=%s 无人参与 → no_entries (result_msg_id=%s)",
            lottery_id, result_msg_id,
        )
        return {
            "winners_count": 0,
            "total_entries": 0,
            "result_msg_id": result_msg_id,
            "no_entries": True,
            "skipped": False,
        }

    # 抽签
    prize_count = int(lottery.get("prize_count") or 1)
    winners = _pick_winners(entries, prize_count)
    winner_ids = [int(w["id"]) for w in winners]
    if winner_ids:
        await mark_lottery_entries_won(winner_ids)

    # 标记 drawn（注意：result_msg_id 在 publish 之后才有；先 mark 防止并发重抽，
    # 之后用 update_lottery_result_msg 补回 msg_id）
    drawn_ok = await mark_lottery_drawn(lottery_id, result_msg_id=None)
    if not drawn_ok:
        # 并发场景：另一进程已 drawn → 撤销刚才的 won 标记不现实；
        # 已写的 entries.won=1 保留作历史；仅 log 警告
        logger.warning(
            "mark_lottery_drawn lid=%s 失败（可能并发已开奖）",
            lottery_id,
        )

    # 频道结果发布（L.3.2 实现）
    result_msg_id = await _try_publish_result(bot, lottery, winners)

    # 私聊通知中奖者（L.3.2 实现）
    notified = await _try_notify_winners(bot, winners, lottery)

    logger.info(
        "run_lottery_draw lid=%s 完成：winners=%d/total=%d, "
        "result_msg=%s, notified=%d",
        lottery_id, len(winners), total, result_msg_id, notified,
    )
    return {
        "winners_count": len(winners),
        "total_entries": total,
        "result_msg_id": result_msg_id,
        "no_entries": False,
        "skipped": False,
        "notified": notified,
    }


# ---- 半匿名 / 渲染 ----

def _anonymize_winner(user_id: int, first_name: Optional[str]) -> str:
    """半匿名签名（spec §5.3）：first_name 首字* + (****uid 后 4)

    边界：
        first_name 空 / None → "匿"
        uid < 10000 → "(****)"
    """
    name = (first_name or "").strip()
    initial = name[0] if name else "匿"
    sid = str(user_id)
    if len(sid) <= 4:
        tail = "(****)"
    else:
        tail = f"(****{sid[-4:]})"
    return f"{initial}* {tail}"


async def _build_winner_names_map(winners: list[dict]) -> dict[int, str]:
    """批量取 winners 的 first_name → {user_id: first_name}"""
    if not winners:
        return {}
    from bot.database import get_users_first_names
    uids = list({int(w["user_id"]) for w in winners})
    return await get_users_first_names(uids)


def render_lottery_result_text(
    lottery: dict,
    winners: list[dict],
    name_map: dict[int, Optional[str]],
    bot_username: str,
) -> str:
    """开奖结果文本（spec §5.3）"""
    name = lottery.get("name", "?")
    prize = lottery.get("prize_description") or "?"
    lines = [
        f"🏆 {name} 开奖结果",
        "",
        f"恭喜以下 {len(winners)} 位中奖者：",
        "",
    ]
    for i, w in enumerate(winners, start=1):
        uid = int(w["user_id"])
        anon = _anonymize_winner(uid, name_map.get(uid))
        lines.append(f"{i}. {anon}")
    lines.append("")
    lines.append(f"📦 奖品：{prize}")
    lines.append("请中奖者于 7 日内在私聊联系管理员领取。")
    lines.append("")
    lines.append(f"✳ Powered by @{bot_username}")
    return "\n".join(lines)


def render_no_entries_text(lottery: dict, bot_username: str) -> str:
    """0 参与时频道追发"""
    name = lottery.get("name", "?")
    return (
        f"⚠️ 「{name}」本次抽奖无人参与，已自动结束。\n\n"
        f"✳ Powered by @{bot_username}"
    )


def _build_winner_keyboard(contact_url: Optional[str]):
    """中奖通知按钮（有 URL → 客服按钮；无 → 无按钮，文字提示）"""
    if not contact_url:
        return None
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍💼 联系管理员", url=contact_url)],
    ])


# ---- 频道追发 + 私聊通知 ----

async def _try_publish_no_entries(bot: Bot, lottery: dict) -> Optional[int]:
    """无人参与时频道追发提示（spec §5.3 / §8）"""
    chat_id = lottery.get("channel_chat_id")
    channel_msg_id = lottery.get("channel_msg_id")
    if not chat_id:
        logger.debug("no_entries 频道缺失 lid=%s", lottery.get("id"))
        return None
    try:
        me = await bot.get_me()
    except Exception:
        me = None
    text = render_no_entries_text(lottery, getattr(me, "username", "ChiYanBookBot"))
    try:
        sent = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=channel_msg_id,
        )
        msg_id = sent.message_id
        from bot.database import update_lottery_result_msg
        await update_lottery_result_msg(int(lottery["id"]), msg_id)
        return msg_id
    except Exception as e:
        logger.warning(
            "no_entries 频道追发失败 lid=%s: %s", lottery.get("id"), e,
        )
        return None


async def _try_publish_result(
    bot: Bot, lottery: dict, winners: list[dict],
) -> Optional[int]:
    """开奖结果在频道追发（reply 到原抽奖帖）"""
    chat_id = lottery.get("channel_chat_id")
    channel_msg_id = lottery.get("channel_msg_id")
    if not chat_id:
        logger.warning(
            "publish_lottery_result 缺 channel_chat_id lid=%s", lottery.get("id"),
        )
        return None
    try:
        me = await bot.get_me()
    except Exception:
        me = None
    name_map = await _build_winner_names_map(winners)
    text = render_lottery_result_text(
        lottery, winners, name_map, getattr(me, "username", "ChiYanBookBot"),
    )
    try:
        sent = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=channel_msg_id,
        )
        msg_id = sent.message_id
        from bot.database import update_lottery_result_msg
        await update_lottery_result_msg(int(lottery["id"]), msg_id)
        return msg_id
    except Exception as e:
        logger.warning(
            "publish_lottery_result 失败 lid=%s: %s",
            lottery.get("id"), e,
        )
        return None


async def _notify_one_winner(
    bot: Bot, winner: dict, lottery: dict, contact_url: Optional[str],
) -> bool:
    """私聊中奖者；返回 True 表示发送成功"""
    from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
    user_id = int(winner["user_id"])
    name = lottery.get("name", "?")
    prize = lottery.get("prize_description") or "?"
    lines = [
        "🎉 恭喜你中奖了！",
        "",
        f"活动：{name}",
        f"奖品：{prize}",
        "",
    ]
    if contact_url:
        lines.append("请于 7 日内点击下方按钮联系管理员领取奖品。")
    else:
        lines.append("请于 7 日内联系频道管理员领取奖品。")
    text = "\n".join(lines)
    kb = _build_winner_keyboard(contact_url)
    try:
        await bot.send_message(
            chat_id=user_id, text=text, reply_markup=kb,
        )
    except TelegramForbiddenError as e:
        logger.info(
            "notify_winner skip uid=%s lid=%s (Forbidden): %s",
            user_id, lottery.get("id"), e,
        )
        return False
    except TelegramBadRequest as e:
        logger.warning(
            "notify_winner BadRequest uid=%s lid=%s: %s",
            user_id, lottery.get("id"), e,
        )
        return False
    except Exception as e:
        logger.warning(
            "notify_winner 失败 uid=%s lid=%s: %s",
            user_id, lottery.get("id"), e,
        )
        return False
    # 成功 → 标记 notified_at
    try:
        from bot.database import mark_lottery_entry_notified
        await mark_lottery_entry_notified(int(winner["id"]))
    except Exception as e:
        logger.warning("mark_lottery_entry_notified 失败 entry=%s: %s", winner.get("id"), e)
    return True


async def _try_notify_winners(
    bot: Bot, winners: list[dict], lottery: dict,
) -> int:
    """批量私聊通知中奖者；返回成功数"""
    if not winners:
        return 0
    from bot.database import get_config
    contact_url = await get_config("lottery_contact_url")
    contact_url = (contact_url or "").strip() or None
    n = 0
    for w in winners:
        ok = await _notify_one_winner(bot, w, lottery, contact_url)
        if ok:
            n += 1
    return n
