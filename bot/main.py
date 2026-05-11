import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone

from bot.config import config
from bot.database import init_db
from bot.handlers.admin_panel import router as admin_panel_router
from bot.handlers.favorite import router as favorite_router
from bot.handlers.start_router import router as start_router
from bot.handlers.teacher_flow import router as teacher_flow_router
from bot.handlers.teacher_checkin import router as checkin_router
from bot.handlers.user_panel import router as user_panel_router
from bot.handlers.user_search import router as user_search_router
from bot.handlers.keyword import router as keyword_router
from bot.scheduler.tasks import schedule_daily_publish, schedule_checkin_reminder

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 创建 Bot 和 Dispatcher
bot = Bot(token=config.bot_token)
dp = Dispatcher(storage=MemoryStorage())

# 创建调度器
scheduler = AsyncIOScheduler(timezone=timezone(config.timezone))


async def on_startup():
    """启动时执行"""
    await init_db()
    logger.info("数据库初始化完成")

    # 配置定时任务
    publish_time = await schedule_daily_publish(scheduler, bot)
    reminder_time = await schedule_checkin_reminder(scheduler, bot)
    scheduler.start()
    logger.info(
        f"定时任务已启动，发布时间: {publish_time}，签到提醒时间: {reminder_time} ({config.timezone})"
    )

    me = await bot.get_me()
    logger.info(f"Bot 启动成功: @{me.username} (ID: {me.id})")


async def on_shutdown():
    """关闭时执行"""
    scheduler.shutdown(wait=False)
    await bot.session.close()
    logger.info("Bot 已关闭")


async def main():
    """主入口"""
    # 注册路由
    # start_router 必须最先：/start 角色分流入口（v2 §2.5）
    dp.include_router(start_router)
    # favorite_router：fav:* callback（卡片场景 + "我的收藏"列表），
    # 放在 admin_panel 之前不影响管理员，但能在 keyword 之前接住群组卡片的 callback
    dp.include_router(favorite_router)
    dp.include_router(admin_panel_router)
    dp.include_router(teacher_flow_router)
    dp.include_router(checkin_router)
    # user_panel / user_search 在 keyword 之前：
    #   - user_panel 的 callback (user:*) 不会和 keyword 冲突
    #   - user_search 的 SearchStates filter 保证只在搜索 FSM 状态下匹配
    dp.include_router(user_panel_router)
    dp.include_router(user_search_router)
    dp.include_router(keyword_router)  # keyword 放最后，避免拦截其他消息

    # 注册生命周期钩子
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # 启动轮询
    logger.info("开始轮询...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
