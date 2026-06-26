"""MiniApp web 服务包（P0 地基）。

在现有单进程内挂一层 aiohttp web 服务，对外提供 MiniApp 的 REST API +
媒体代理 + Telegram initData 鉴权。与 aiogram polling 共用同一 asyncio loop，
复用同一 Bot 对象做通知回流（详见 docs/MINIAPP-MIGRATION.md §二）。

本包按"可拆分"边界设计：API/鉴权/服务解耦，便于后续在 QPS 上来时迁独立进程。
当前阶段（P0）只包含：
    - auth.py    initData 验签 + session 签发/校验 + 角色解析
    - server.py  aiohttp 挂载 + 健康检查 + /api/me（后续 commit 补全）
"""
