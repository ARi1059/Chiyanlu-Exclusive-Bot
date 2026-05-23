"""bot/main.py 静态检查（不实例化真实 Bot / Dispatcher）。

2026-05-18 拆分后 main.py 是组合入口：
    - 仍然支持 ``python3 -m bot.main`` 启动方式
    - 保留 ``asyncio.run(main())``
    - 通过 ``create_app() / register_routers() / register_lifecycle_handlers()``
      组合 polling

为什么不真实启动：本地 / CI 用 dummy token，aiogram 会校验 token 格式。
我们用纯文本读取确保入口契约成立。
"""

from __future__ import annotations

import ast
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN_PY = os.path.join(_PROJECT_ROOT, "bot", "main.py")


def _read() -> str:
    with open(_MAIN_PY, encoding="utf-8") as f:
        return f.read()


def _parse() -> ast.Module:
    return ast.parse(_read())


# ============ 模块级契约 ============


def test_main_module_exists():
    assert os.path.isfile(_MAIN_PY)


def test_main_function_defined():
    """必须有 async def main() 函数。"""
    tree = _parse()
    fns = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
    ]
    assert fns, "未在 bot/main.py 顶层找到 main 函数"
    assert isinstance(fns[0], ast.AsyncFunctionDef), "main 必须是 async 函数"


def test_asyncio_run_main_called_under_dunder_main_guard():
    """必须保留 ``if __name__ == '__main__': asyncio.run(main())`` 入口"""
    src = _read()
    assert "if __name__" in src
    assert 'asyncio.run(main())' in src or "asyncio.run( main() )" in src


def test_imports_required_components():
    """必须导入 create_app / register_routers / register_lifecycle_handlers"""
    src = _read()
    assert "from bot.app_factory import create_app" in src
    assert "from bot.routers import register_routers" in src
    assert "from bot.lifecycle import register_lifecycle_handlers" in src


def test_start_polling_invoked():
    """polling 启动入口不能丢"""
    src = _read()
    assert "start_polling" in src, "main.py 必须包含 start_polling 调用"


def test_logger_basic_config_present():
    """logging.basicConfig 仍由 main.py 配置（与拆分前一致）"""
    src = _read()
    assert "logging.basicConfig(" in src
    # 保持原 format（拆分前后必须一致）
    assert "%(asctime)s [%(levelname)s] %(name)s: %(message)s" in src


def test_main_calls_three_setup_steps_in_order():
    """main() 函数体内应顺序调用 create_app → register_routers → register_lifecycle_handlers。"""
    tree = _parse()
    main_fn = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"
    )
    call_names: list[str] = []
    for node in ast.walk(main_fn):
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in {"create_app", "register_routers", "register_lifecycle_handlers", "start_polling"}:
                call_names.append(name)

    # 验证顺序：create_app 必须在 register_routers / register_lifecycle_handlers 之前；
    # start_polling 必须在最后
    assert call_names.index("create_app") < call_names.index("register_routers")
    assert call_names.index("create_app") < call_names.index("register_lifecycle_handlers")
    assert call_names.index("start_polling") == len(call_names) - 1


def test_no_handler_imports_remain_in_main():
    """拆分后 main.py 不应再直接 import bot.handlers.* — 所有 router 已迁到 routers.py。"""
    src = _read()
    assert "from bot.handlers" not in src, (
        "main.py 仍残留 bot.handlers 的 import，应全部移到 bot/routers.py"
    )


def test_no_inline_router_registration():
    """拆分后 main.py 不应再有 dp.include_router 调用。"""
    src = _read()
    assert "include_router" not in src


def test_no_inline_startup_shutdown_callbacks():
    """startup / shutdown 应由 bot.lifecycle 管理；main.py 不应再定义这些回调。"""
    src = _read()
    assert "async def on_startup" not in src
    assert "async def on_shutdown" not in src
