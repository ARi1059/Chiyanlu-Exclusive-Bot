import logging
from datetime import datetime, timedelta

from typing import Optional, Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pytz import timezone

from bot.config import config
from bot.database import (
    get_checked_in_teachers,
    get_unchecked_teachers,
    get_config,
    save_sent_message,
    get_sent_messages,
    delete_sent_messages,
)
from bot.utils.notifier import send_favorite_notifications
from bot.utils.url import normalize_url

logger = logging.getLogger(__name__)

_scheduler = None
_bot: Optional[Bot] = None

tz = timezone(config.timezone)


def parse_publish_chat_ids(raw: Optional[str]) -> list[int]:
    """解析发布目标 ID，兼容单个 ID 和逗号分隔的多个 ID"""
    if not raw:
        return []

    chat_ids = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        chat_ids.append(int(part))
    return chat_ids


async def get_publish_time() -> str:
    """获取当前发布时间配置"""
    return await get_config("publish_time") or config.publish_time


async def schedule_daily_publish(scheduler, bot: Bot) -> str:
    """配置或重载每日签到汇总定时任务，返回生效的发布时间"""
    global _scheduler, _bot
    _scheduler = scheduler
    _bot = bot

    publish_time = await get_publish_time()
    hour, minute = map(int, publish_time.split(":"))
    scheduler.add_job(
        publish_daily_checkin,
        "cron",
        hour=hour,
        minute=minute,
        args=[bot],
        id="daily_publish",
        replace_existing=True,
    )
    return publish_time


async def reload_daily_publish() -> Optional[str]:
    """重载已注册的每日签到汇总定时任务"""
    if _scheduler is None or _bot is None:
        return None
    return await schedule_daily_publish(_scheduler, _bot)


async def get_checkin_reminder_time() -> str:
    """获取签到提醒时间配置"""
    return await get_config("checkin_reminder_time") or "13:00"


async def is_checkin_reminder_enabled() -> bool:
    """判断签到提醒是否启用"""
    return (await get_config("checkin_reminder_enabled")) == "1"


async def schedule_checkin_reminder(scheduler, bot: Bot) -> str:
    """配置或重载老师签到提醒定时任务，返回生效的提醒时间"""
    global _scheduler, _bot
    _scheduler = scheduler
    _bot = bot

    reminder_time = await get_checkin_reminder_time()
    hour, minute = map(int, reminder_time.split(":"))
    scheduler.add_job(
        send_checkin_reminders,
        "cron",
        hour=hour,
        minute=minute,
        args=[bot],
        id="checkin_reminder",
        replace_existing=True,
    )
    return reminder_time


async def reload_checkin_reminder() -> Optional[str]:
    """重载已注册的老师签到提醒定时任务"""
    if _scheduler is None or _bot is None:
        return None
    return await schedule_checkin_reminder(_scheduler, _bot)


async def send_checkin_reminders(bot: Bot):
    """给当天未签到的启用老师发送私聊提醒"""
    if not await is_checkin_reminder_enabled():
        logger.info("签到提醒未启用，跳过")
        return

    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    publish_time = await get_publish_time()
    teachers = await get_unchecked_teachers(today_str)

    if not teachers:
        logger.info("[%s] 无未签到老师，跳过提醒", today_str)
        return

    success_count = 0
    failed_count = 0
    for teacher in teachers:
        text = (
            "签到提醒\n\n"
            f"老师：{teacher['display_name']}\n"
            f"日期：{today_str}\n"
            f"今日还未签到，请在 {publish_time} 前私聊发送“签到”完成签到。"
        )
        try:
            await bot.send_message(chat_id=teacher["user_id"], text=text)
            success_count += 1
            logger.info("已提醒老师签到: %s (%s)", teacher["display_name"], teacher["user_id"])
        except Exception as e:
            failed_count += 1
            logger.warning(
                "提醒老师签到失败: %s (%s): %s",
                teacher["display_name"],
                teacher["user_id"],
                e,
            )

    logger.info(
        "[%s] 签到提醒完成，成功 %s 位，失败 %s 位",
        today_str,
        success_count,
        failed_count,
    )


async def build_daily_checkin_payload(date_str: str) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
    """构建每日签到发布内容，返回文本和按钮"""
    teachers = await get_checked_in_teachers(date_str)
    if not teachers:
        return None

    buttons = []
    row = []
    for t in teachers:
        button_url = normalize_url(t["button_url"])
        if not button_url:
            logger.warning("跳过无效老师链接: %s (%s)", t["display_name"], t["button_url"])
            continue
        button_text = t["button_text"] or t["display_name"]
        row.append(InlineKeyboardButton(text=button_text, url=button_url))
        # 每行最多 3 个按钮
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    if not buttons:
        return None

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"📅 {date_str} 开课老师 {len(teachers)}位"
    return text, keyboard


async def send_daily_checkin(bot: Bot, chat_id: int, date_str: str):
    """发送指定日期签到汇总并保存发送记录"""
    payload = await build_daily_checkin_payload(date_str)
    if payload is None:
        logger.info(f"[{date_str}] 无老师签到，跳过发布")
        return None

    text, keyboard = payload
    msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
    )
    await save_sent_message(chat_id, msg.message_id, date_str)
    return msg


async def publish_daily_checkin(bot: Bot):
    """每日定时任务（14:00）：两阶段顺序执行，互不阻断（v2 §2.2.6）

    阶段 1：频道发布（v1 行为）—— 删旧消息 + 发当天签到汇总
    阶段 2：收藏者通知（F2，v2 §2.2）—— mention 聚合 + 限速推送

    两个阶段都包在 try/except 里，任一异常不影响另一个。
    """
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")

    # 阶段 1：频道发布
    try:
        await _publish_to_channels(bot, today_str)
    except Exception as e:
        logger.error("[%s] 频道发布阶段异常: %s", today_str, e)

    # 阶段 2：收藏者通知
    try:
        result = await send_favorite_notifications(bot, today_str)
        if result["total"] > 0:
            logger.info(
                "[%s] 收藏通知: %d/%d 成功，耗时 %.2fs",
                today_str,
                result["succeeded"],
                result["total"],
                result["duration_seconds"],
            )
    except Exception as e:
        logger.error("[%s] 收藏通知阶段异常: %s", today_str, e)


async def _publish_to_channels(bot: Bot, today_str: str):
    """阶段 1：频道发布逻辑（从原 publish_daily_checkin 提取）

    无目标 / 配置无效时 logger.warning 跳过，不影响阶段 2。
    """
    # 先删除前一天的消息
    await _delete_previous_messages(bot)

    # 获取发布目标（频道或群组）
    raw_chat_ids = await get_config("publish_channel_id")
    try:
        chat_ids = parse_publish_chat_ids(raw_chat_ids)
    except ValueError:
        logger.error("发布目标配置无效: %s", raw_chat_ids)
        return

    if not chat_ids:
        logger.warning("未设置发布目标，跳过频道发布")
        return

    for chat_id in chat_ids:
        try:
            msg = await send_daily_checkin(bot, chat_id, today_str)
            if msg:
                logger.info(f"[{today_str}] 已发布签到汇总到 {chat_id}")
        except Exception as e:
            logger.error(f"发布签到汇总失败 chat={chat_id}: {e}")


async def _delete_previous_messages(bot: Bot):
    """删除前一天发送的消息"""
    now = datetime.now(tz)
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    messages = await get_sent_messages(yesterday_str)
    if not messages:
        return

    for msg in messages:
        try:
            await bot.delete_message(
                chat_id=msg["chat_id"],
                message_id=msg["message_id"],
            )
        except Exception as e:
            # 消息可能已被手动删除，捕获异常跳过
            logger.warning(f"删除消息失败 (chat={msg['chat_id']}, msg={msg['message_id']}): {e}")

    # 清除记录
    await delete_sent_messages(yesterday_str)
    logger.info(f"已清理 {yesterday_str} 的 {len(messages)} 条消息记录")
