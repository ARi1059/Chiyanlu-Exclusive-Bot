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
from bot.config import config
from bot.lifecycle import register_lifecycle_handlers
from bot.routers import register_routers

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# 降噪：aiogram 每处理一条 update 都会记一行 INFO（"Update ... is handled"），
# 高频累积是日志膨胀的主因 —— 2026-06-20 journald 把 4G 盘撑满后 SQLite 报
# disk I/O error，bot 查不出数据、形同"数据被清空"。调到 WARNING 只保留异常；
# 业务/启动日志（bot.main、bot.scheduler 等）不受影响。
logging.getLogger("aiogram.event").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def main():
    """主入口"""
    app = create_app()
    register_routers(app.dp)
    register_lifecycle_handlers(app.dp, app.bot, app.scheduler)

    # 同进程并起 MiniApp web 服务（§二）。默认 WEB_ENABLED=false → 行为与接入前
    # 完全一致；显式开启后 web 在同一 loop 后台监听，与 polling 共存。
    # web 启动失败绝不拖垮 polling（仅告警，回退纯 bot 模式）。
    runner = None
    if config.web_enabled:
        try:
            from bot.web.server import start_web
            runner = await start_web(
                app.bot, host=config.web_host, port=config.web_port,
            )
        except Exception:
            logger.exception("Web 服务启动失败，回退仅 polling 模式")
            runner = None

    # 启动轮询
    logger.info("开始轮询...")
    try:
        await app.dp.start_polling(app.bot)
    finally:
        if runner is not None:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
