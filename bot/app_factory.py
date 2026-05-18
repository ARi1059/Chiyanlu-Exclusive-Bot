"""应用工厂：负责创建 Bot / Dispatcher / MemoryStorage / AsyncIOScheduler。

本模块只做"构造"，不注册任何 router、不挂任何 startup/shutdown 钩子，
不调用任何业务初始化（如 init_db）。这样可以让 main.py 保持极薄入口。

构造方式与 2026-05-18 拆分前的 bot/main.py 模块顶部完全一致，等价于：

    bot = Bot(token=config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    scheduler = AsyncIOScheduler(timezone=timezone(config.timezone))
"""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone

from bot.config import config


@dataclass
class BotApp:
    """运行时容器：仅承载三个核心组件，便于在 main / routers / lifecycle 之间传递。"""
    bot: Bot
    dp: Dispatcher
    scheduler: AsyncIOScheduler


def create_app() -> BotApp:
    """创建 Bot / Dispatcher / Scheduler，行为与拆分前的模块顶部代码完全等价。"""
    bot = Bot(token=config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    scheduler = AsyncIOScheduler(timezone=timezone(config.timezone))
    return BotApp(bot=bot, dp=dp, scheduler=scheduler)
