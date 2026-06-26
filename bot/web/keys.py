"""aiohttp Application 共享键（P0·T4）。

集中定义 web.AppKey，消除 NotAppKeyWarning，并避免 server / middleware / api
之间为取键而循环 import。
"""
from __future__ import annotations

from aiogram import Bot
from aiohttp import web

# 值可能为 None（集成测试不传 bot）；AppKey 不做运行时类型校验。
APP_BOT = web.AppKey("bot", Bot)
APP_BOT_TOKEN = web.AppKey("bot_token", str)
