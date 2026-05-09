import os
from dataclasses import dataclass
from dotenv import load_dotenv
from pytz import timezone as pytz_timezone, UnknownTimeZoneError

load_dotenv()


def _parse_int_env(name: str, default: str | None = None, min_value: int | None = None) -> int:
    """读取并校验整数环境变量"""
    raw = os.getenv(name, default)
    if raw is None or raw == "":
        raise ValueError(f"{name} is required in .env")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got: {raw}") from exc
    if min_value is not None and value < min_value:
        raise ValueError(f"{name} must be >= {min_value}, got: {value}")
    return value


def _validate_publish_time(value: str) -> str:
    """校验发布时间格式 HH:MM"""
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"PUBLISH_TIME must use HH:MM format, got: {value}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"PUBLISH_TIME must be a valid time, got: {value}")
    return value


def _validate_timezone(value: str) -> str:
    """校验时区名称"""
    try:
        pytz_timezone(value)
    except UnknownTimeZoneError as exc:
        raise ValueError(f"TIMEZONE must be a valid timezone name, got: {value}") from exc
    return value


@dataclass
class Config:
    bot_token: str
    super_admin_id: int
    database_path: str
    timezone: str
    publish_time: str
    cooldown_seconds: int

    @classmethod
    def from_env(cls) -> "Config":
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            raise ValueError("BOT_TOKEN is required in .env")

        return cls(
            bot_token=bot_token,
            super_admin_id=_parse_int_env("SUPER_ADMIN_ID"),
            database_path=os.getenv("DATABASE_PATH", "./data/bot.db"),
            timezone=_validate_timezone(os.getenv("TIMEZONE", "Asia/Shanghai")),
            publish_time=_validate_publish_time(os.getenv("PUBLISH_TIME", "14:00")),
            cooldown_seconds=_parse_int_env("COOLDOWN_SECONDS", "30", min_value=0),
        )


config = Config.from_env()
