"""主入口。

2026-05-18 拆分：
    - bot/app_factory.py 负责 Bot / Dispatcher / Scheduler 构造
    - bot/routers.py     负责 33 个 router 的注册（顺序与拆分前等价）
    - bot/lifecycle.py   负责 startup / shutdown 钩子
本文件只组合上述三块并启动 polling。

运行方式（与拆分前一致）：

    python3 -m bot.main
"""

import asyncio
import logging

from bot.app_factory import create_app
from bot.lifecycle import register_lifecycle_handlers
from bot.routers import register_routers

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """主入口"""
    app = create_app()
    register_routers(app.dp)
    register_lifecycle_handlers(app.dp, app.bot, app.scheduler)

    # 启动轮询
    logger.info("开始轮询...")
    await app.dp.start_polling(app.bot)


if __name__ == "__main__":
    asyncio.run(main())
