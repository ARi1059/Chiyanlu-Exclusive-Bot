"""Telegram file_id → 字节流代理 + 进程内 LRU 缓存（共享）。

老师相册（photo.py）与评价审核媒体（review_media.py）都需要把 Telegram file_id
拉成字节流代发并缓存，逻辑一致。抽到此处共用，避免两份缓存实现漂移。

缓存键是 file_id（全局唯一），故老师照片与评价媒体可共享同一 LRU，互不冲突。
"""
from __future__ import annotations

import logging
from collections import OrderedDict

logger = logging.getLogger(__name__)

# file_id → (content_type, bytes)。OrderedDict 当简易 LRU，超额淘汰最旧。
_CACHE: "OrderedDict[str, tuple[str, bytes]]" = OrderedDict()
_CACHE_MAX = 128

# 单日强缓存：图片更新极少，浏览器/反代各自缓存一天。
CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}


def content_type_for(file_path: str | None) -> str:
    p = (file_path or "").lower()
    if p.endswith(".png"):
        return "image/png"
    if p.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


async def proxy_telegram_file(bot, file_id: str) -> tuple[str, bytes]:
    """拉取 Telegram file_id 的字节流（带进程内 LRU 缓存）。

    返回 (content_type, body)。命中缓存直接回；未命中经 bot.get_file +
    download_file 拉取后写缓存。bot 为 None / 拉取失败 → 抛异常，调用方据此回 404。
    """
    cached = _CACHE.get(file_id)
    if cached is not None:
        _CACHE.move_to_end(file_id)
        return cached

    if bot is None:
        raise RuntimeError("bot unavailable")

    tg_file = await bot.get_file(file_id)
    buf = await bot.download_file(tg_file.file_path)
    body = buf.getvalue() if hasattr(buf, "getvalue") else buf.read()
    ctype = content_type_for(tg_file.file_path)

    _CACHE[file_id] = (ctype, body)
    _CACHE.move_to_end(file_id)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return ctype, body
