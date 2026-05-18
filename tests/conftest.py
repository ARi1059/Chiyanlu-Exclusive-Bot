"""pytest 全局配置：测试环境隔离。

为什么必须在 module level（而不是 fixture）设置环境变量：
    bot/config.py 在被 import 时立即执行 ``config = Config.from_env()``，
    一旦 bot.config 被 import，env 就已经被读取。pytest 的 monkeypatch
    fixture 只在测试函数调用时生效，时机太晚。

为什么 stub dotenv.load_dotenv：
    生产服务器上可能存在真实 .env，包含真实的 BOT_TOKEN / SUPER_ADMIN_ID。
    我们必须保证测试在任何环境都用上面这套虚拟值，且绝不让真实 token / 真实
    DATABASE_PATH 出现在测试进程内。
"""

from __future__ import annotations

import os
import sys


# 1. 强制覆盖测试需要的环境变量（在任何 bot.* 模块 import 之前）
_TEST_ENV: dict[str, str] = {
    "BOT_TOKEN": "dummy:token",
    "SUPER_ADMIN_ID": "123456789",
    "DATABASE_PATH": ":memory:",
    "TIMEZONE": "Asia/Shanghai",
    "PUBLISH_TIME": "14:00",
    "COOLDOWN_SECONDS": "30",
}
for _k, _v in _TEST_ENV.items():
    os.environ[_k] = _v


# 2. 把 dotenv.load_dotenv 替换为 no-op，杜绝读取真实 .env
try:
    import dotenv  # python-dotenv 已是项目依赖
    dotenv.load_dotenv = lambda *args, **kwargs: False  # type: ignore[assignment]
except ImportError:
    pass


# 3. 确保项目根在 sys.path（让 `from bot.xxx import ...` 工作）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
