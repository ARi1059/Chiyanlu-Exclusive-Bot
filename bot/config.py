import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


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

        super_admin_id = os.getenv("SUPER_ADMIN_ID")
        if not super_admin_id:
            raise ValueError("SUPER_ADMIN_ID is required in .env")

        return cls(
            bot_token=bot_token,
            super_admin_id=int(super_admin_id),
            database_path=os.getenv("DATABASE_PATH", "./data/bot.db"),
            timezone=os.getenv("TIMEZONE", "Asia/Shanghai"),
            publish_time=os.getenv("PUBLISH_TIME", "14:00"),
            cooldown_seconds=int(os.getenv("COOLDOWN_SECONDS", "30")),
        )


config = Config.from_env()
