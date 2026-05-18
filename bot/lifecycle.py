"""启动 / 关闭生命周期钩子。

⚠️ 本模块在 2026-05-18 main.py 拆分时建立。**on_startup / on_shutdown 的
代码块逐行等价于拆分前的 bot/main.py L67-102**，业务行为完全不变。

为什么 logger 用固定名 ``bot.main`` 而不是 ``__name__``：
    拆分前 ``logger.info(...)`` 输出的 ``%(name)s`` 字段是 ``bot.main``。
    若改用 ``__name__`` 会变成 ``bot.lifecycle``，对日志解析 / 报警规则
    可能造成隐式破坏。这里显式保持原日志行不变。
"""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import config
from bot.database import init_db
from bot.scheduler.lottery_tasks import schedule_pending_lotteries
from bot.scheduler.tasks import (
    schedule_checkin_reminder,
    schedule_daily_publish,
    schedule_daily_report,
    schedule_weekly_report,
)

# 保持拆分前的 logger 名，避免影响日志中 %(name)s 字段的值
logger = logging.getLogger("bot.main")


def register_lifecycle_handlers(
    dp: Dispatcher,
    bot: Bot,
    scheduler: AsyncIOScheduler,
) -> None:
    """把 startup / shutdown 钩子注册到 dispatcher。

    内部定义的 on_startup / on_shutdown 通过闭包捕获 bot / scheduler，
    与拆分前模块级 ``bot`` / ``scheduler`` 变量的访问语义等价。
    """

    async def on_startup():
        """启动时执行"""
        await init_db()
        logger.info("数据库初始化完成")

        # 配置定时任务
        publish_time = await schedule_daily_publish(scheduler, bot)
        reminder_time = await schedule_checkin_reminder(scheduler, bot)
        daily_report_time = await schedule_daily_report(scheduler, bot)
        weekly_report_time = await schedule_weekly_report(scheduler, bot)
        scheduler.start()
        logger.info(
            f"定时任务已启动，发布时间: {publish_time}，签到提醒时间: {reminder_time}，"
            f"日报: {daily_report_time}，周报: {weekly_report_time} ({config.timezone})"
        )

        # Phase L.2：bot 重启时扫所有 scheduled/active 抽奖重注册定时任务（spec §8）
        try:
            lottery_summary = await schedule_pending_lotteries(scheduler, bot)
            logger.info(
                "抽奖任务扫描完成：发布 %d / 开奖 %d",
                lottery_summary["scheduled_publish"],
                lottery_summary["scheduled_draw"],
            )
        except Exception as e:
            logger.warning("schedule_pending_lotteries 失败（不阻断启动）: %s", e)

        me = await bot.get_me()
        logger.info(f"Bot 启动成功: @{me.username} (ID: {me.id})")

    async def on_shutdown():
        """关闭时执行"""
        scheduler.shutdown(wait=False)
        await bot.session.close()
        logger.info("Bot 已关闭")

    # 注册生命周期钩子
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
