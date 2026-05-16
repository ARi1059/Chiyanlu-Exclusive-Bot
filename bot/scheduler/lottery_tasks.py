"""抽奖定时任务调度（Phase L.2.2）

spec §8 "抽奖期间 bot 重启 → 启动时扫所有 status='scheduled'/'active' 重新注册"
spec §10 L.2 实现：立即发布 / 定时发布两条路径都走 APScheduler 调度

job id 命名：
    lottery_pub_<lid>   发布定时任务
    lottery_draw_<lid>  开奖定时任务（L.3 实现实际开奖；本 phase 占位 log）

调用方：
- L.2.2 FSM 保存草稿后 → schedule_lottery_publish + schedule_lottery_draw
- 取消抽奖时 → unschedule_lottery
- bot on_startup → schedule_pending_lotteries（扫描重注册）
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone

from bot.config import config
from bot.database import list_active_or_scheduled_lotteries
from bot.utils.lottery_publish import (
    LotteryPublishError,
    publish_lottery_to_channel,
)

logger = logging.getLogger(__name__)


def _parse_db_datetime(s: Optional[str]) -> Optional[datetime]:
    """解析 DB 存储的 'YYYY-MM-DD HH:MM:SS' → aware datetime"""
    if not s:
        return None
    try:
        dt = datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(s.strip(), "%Y-%m-%d %H:%M")
        except ValueError:
            return None
    return timezone(config.timezone).localize(dt)


def _now_local() -> datetime:
    return datetime.now(timezone(config.timezone))


async def publish_job(bot: Bot, lottery_id: int) -> None:
    """定时任务回调：到 publish_at 时发布抽奖"""
    try:
        result = await publish_lottery_to_channel(bot, lottery_id)
        logger.info(
            "lottery publish 成功 lid=%s chat=%s msg=%s",
            lottery_id, result["chat_id"], result["msg_id"],
        )
    except LotteryPublishError as e:
        logger.warning(
            "lottery publish 失败 lid=%s reason=%s: %s",
            lottery_id, e.reason, e,
        )
    except Exception as e:
        logger.warning("lottery publish 异常 lid=%s: %s", lottery_id, e)


async def draw_job(bot: Bot, lottery_id: int) -> None:
    """定时任务回调：到 draw_at 时开奖（Phase L.3 实际执行）

    使用 secrets.SystemRandom 等概率抽 winners + 频道追发结果 + 私聊通知。
    drawn / cancelled / no_entries 状态自动跳过（防重复抽）。
    异常仅 log warning，不让定时任务循环异常。
    """
    try:
        from bot.utils.lottery_draw import run_lottery_draw, LotteryDrawError
        result = await run_lottery_draw(bot, lottery_id)
        if result.get("skipped"):
            logger.info(
                "draw_job skip lid=%s reason=%s",
                lottery_id, result.get("reason"),
            )
            return
        if result.get("no_entries"):
            logger.info("draw_job no_entries lid=%s", lottery_id)
            return
        logger.info(
            "draw_job done lid=%s winners=%d/%d notified=%d result_msg=%s",
            lottery_id,
            result.get("winners_count", 0),
            result.get("total_entries", 0),
            result.get("notified", 0),
            result.get("result_msg_id"),
        )
    except LotteryDrawError as e:
        logger.warning(
            "draw_job LotteryDrawError lid=%s reason=%s: %s",
            lottery_id, e.reason, e,
        )
    except Exception as e:
        logger.warning("draw_job 异常 lid=%s: %s", lottery_id, e)


def schedule_lottery_publish(
    scheduler: AsyncIOScheduler,
    bot: Bot,
    lottery: dict,
) -> bool:
    """注册抽奖发布定时任务（spec §10 L.2）

    publish_at 已过 → 立即触发（用 run_date=now+1s）
    返回 True 表示已注册（无论立即 or 未来）；False 表示参数错误。
    """
    lid = lottery.get("id")
    if not lid:
        return False
    pub_at = _parse_db_datetime(lottery.get("publish_at"))
    if pub_at is None:
        logger.warning("schedule_lottery_publish 无法解析 publish_at: %s", lottery.get("publish_at"))
        return False
    now = _now_local()
    run_date = pub_at if pub_at > now else now
    try:
        scheduler.add_job(
            publish_job,
            "date",
            run_date=run_date,
            args=[bot, int(lid)],
            id=f"lottery_pub_{lid}",
            replace_existing=True,
            misfire_grace_time=3600,  # 1 小时内补发
        )
        logger.info(
            "已注册 lottery_pub_%s @ %s（publish_at=%s）",
            lid, run_date.isoformat(), pub_at.isoformat(),
        )
        return True
    except Exception as e:
        logger.warning("schedule_lottery_publish 失败 lid=%s: %s", lid, e)
        return False


def schedule_lottery_draw(
    scheduler: AsyncIOScheduler,
    bot: Bot,
    lottery: dict,
) -> bool:
    """注册抽奖开奖定时任务（L.3 实现实际开奖；本 phase 占位）"""
    lid = lottery.get("id")
    if not lid:
        return False
    draw_at = _parse_db_datetime(lottery.get("draw_at"))
    if draw_at is None:
        logger.warning("schedule_lottery_draw 无法解析 draw_at: %s", lottery.get("draw_at"))
        return False
    now = _now_local()
    run_date = draw_at if draw_at > now else now
    try:
        scheduler.add_job(
            draw_job,
            "date",
            run_date=run_date,
            args=[bot, int(lid)],
            id=f"lottery_draw_{lid}",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info(
            "已注册 lottery_draw_%s @ %s（draw_at=%s）",
            lid, run_date.isoformat(), draw_at.isoformat(),
        )
        return True
    except Exception as e:
        logger.warning("schedule_lottery_draw 失败 lid=%s: %s", lid, e)
        return False


def unschedule_lottery(scheduler: AsyncIOScheduler, lottery_id: int) -> int:
    """取消抽奖的两个定时任务

    返回成功取消的数量（0-2）。
    """
    removed = 0
    for job_id in (f"lottery_pub_{lottery_id}", f"lottery_draw_{lottery_id}"):
        try:
            scheduler.remove_job(job_id)
            removed += 1
        except Exception as e:
            # JobLookupError 视为正常（job 已被触发 / 不存在）
            logger.debug("remove_job %s: %s", job_id, e)
    return removed


async def schedule_pending_lotteries(
    scheduler: AsyncIOScheduler,
    bot: Bot,
) -> dict:
    """bot 启动时扫所有 scheduled/active 抽奖重注册定时任务（spec §8）

    Returns: {"scheduled_publish": N, "scheduled_draw": M}
    """
    items = await list_active_or_scheduled_lotteries()
    n_pub = 0
    n_draw = 0
    for item in items:
        status = item.get("status")
        if status == "scheduled":
            if schedule_lottery_publish(scheduler, bot, item):
                n_pub += 1
        # 不管 scheduled 还是 active，开奖任务都要注册
        if schedule_lottery_draw(scheduler, bot, item):
            n_draw += 1
    logger.info(
        "schedule_pending_lotteries：注册 %d 个发布任务 + %d 个开奖任务",
        n_pub, n_draw,
    )
    return {"scheduled_publish": n_pub, "scheduled_draw": n_draw}
