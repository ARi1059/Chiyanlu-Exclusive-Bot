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


# ---- 占位实现（L.3.2 替换为完整逻辑） ----

async def _try_publish_no_entries(bot: Bot, lottery: dict) -> Optional[int]:
    """L.3.2：无人参与时频道追发提示（本 commit 占位 → None）"""
    logger.debug("_try_publish_no_entries 占位 lid=%s（L.3.2 实现）", lottery.get("id"))
    return None


async def _try_publish_result(
    bot: Bot, lottery: dict, winners: list[dict],
) -> Optional[int]:
    """L.3.2：开奖结果在频道追发（本 commit 占位 → None）"""
    logger.debug("_try_publish_result 占位 lid=%s winners=%d", lottery.get("id"), len(winners))
    return None


async def _try_notify_winners(
    bot: Bot, winners: list[dict], lottery: dict,
) -> int:
    """L.3.2：私聊通知中奖者（本 commit 占位 → 0）"""
    logger.debug(
        "_try_notify_winners 占位 lid=%s winners=%d",
        lottery.get("id"), len(winners),
    )
    return 0
