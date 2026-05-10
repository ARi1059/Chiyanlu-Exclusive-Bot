from typing import Optional
from urllib.parse import urlsplit


def normalize_url(value: str) -> Optional[str]:
    """清理并校验 Telegram 按钮 URL"""
    if not value:
        return None

    url = "".join(str(value).strip().split())
    parsed = urlsplit(url)

    if parsed.scheme in ("http", "https") and parsed.netloc:
        return url
    if parsed.scheme == "tg" and parsed.path:
        return url
    return None


def is_valid_url(value: str) -> bool:
    """判断 URL 是否可用于 Telegram 按钮"""
    return normalize_url(value) is not None
