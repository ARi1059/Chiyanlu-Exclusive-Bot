import logging
from datetime import datetime, timedelta

from typing import Optional, Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pytz import timezone

from bot.config import config
from bot.database import (
    get_checked_in_teachers,
    get_default_publish_template,
    get_display_time_group,
    get_sorted_teachers,
    get_unchecked_teachers,
    get_config,
    render_publish_template,
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


# ============ 日报 / 周报定时任务 (Phase 6.3) ============


async def get_daily_report_time() -> str:
    """读取日报时间配置（HH:MM），缺失则 23:30"""
    return await get_config("daily_report_time") or "23:30"


async def get_weekly_report_time() -> str:
    """读取周报时间配置（HH:MM），缺失则 23:00"""
    return await get_config("weekly_report_time") or "23:00"


async def get_weekly_report_day() -> int:
    """读取周报星期配置 1-7（1=周一,7=周日），缺失或非法则 7"""
    raw = await get_config("weekly_report_day")
    if raw:
        try:
            v = int(raw)
            if 1 <= v <= 7:
                return v
        except (TypeError, ValueError):
            pass
    return 7


async def _resolve_report_chat_id() -> int:
    """report_chat_id 解析：config.report_chat_id → super_admin_id 兜底"""
    raw = await get_config("report_chat_id")
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return int(config.super_admin_id)


async def schedule_daily_report(scheduler, bot: Bot) -> str:
    """注册（或重载）日报 cron 任务（Phase 6.3 §五）

    返回生效的发送时间字符串。
    """
    global _scheduler, _bot
    _scheduler = scheduler
    _bot = bot

    time_str = await get_daily_report_time()
    try:
        hour, minute = map(int, time_str.split(":"))
    except (ValueError, TypeError):
        hour, minute = 23, 30
        time_str = "23:30"

    scheduler.add_job(
        send_daily_report,
        "cron",
        hour=hour,
        minute=minute,
        args=[bot],
        id="daily_report",
        replace_existing=True,
    )
    return time_str


async def reload_daily_report() -> Optional[str]:
    """重载已注册的日报任务"""
    if _scheduler is None or _bot is None:
        return None
    return await schedule_daily_report(_scheduler, _bot)


async def schedule_weekly_report(scheduler, bot: Bot) -> str:
    """注册（或重载）周报 cron 任务（Phase 6.3 §五）

    周报日期约定：1=Mon..7=Sun（spec），APScheduler 内部 0=Mon..6=Sun → 转换 -1。
    返回生效的发送时间字符串（不含星期）。
    """
    global _scheduler, _bot
    _scheduler = scheduler
    _bot = bot

    time_str = await get_weekly_report_time()
    try:
        hour, minute = map(int, time_str.split(":"))
    except (ValueError, TypeError):
        hour, minute = 23, 0
        time_str = "23:00"

    day_1to7 = await get_weekly_report_day()
    aps_day = (day_1to7 - 1) % 7  # APScheduler: 0=Mon..6=Sun

    scheduler.add_job(
        send_weekly_report,
        "cron",
        day_of_week=aps_day,
        hour=hour,
        minute=minute,
        args=[bot],
        id="weekly_report",
        replace_existing=True,
    )
    return time_str


async def reload_weekly_report() -> Optional[str]:
    """重载已注册的周报任务"""
    if _scheduler is None or _bot is None:
        return None
    return await schedule_weekly_report(_scheduler, _bot)


async def send_daily_report(bot: Bot, force: bool = False) -> bool:
    """生成并发送日报（Phase 6.3 §五）

    Args:
        force=True 时绕过 daily_report_enabled 检查（用于管理员立即测试）

    定时执行路径：force=False；
    管理员"立即测试"路径：force=True。

    返回 True 表示已发送；False 表示跳过 / 失败。
    """
    if not force:
        enabled = (await get_config("daily_report_enabled")) == "1"
        if not enabled:
            logger.info("日报未启用，跳过本次执行")
            return False

    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")

    try:
        from bot.utils.reports import build_daily_report_text
        text = await build_daily_report_text(today_str)
    except Exception as e:
        logger.warning("构建日报文本失败: %s", e)
        return False

    chat_id = await _resolve_report_chat_id()
    try:
        await bot.send_message(chat_id=chat_id, text=text)
        logger.info("[%s] 日报已发送到 %s", today_str, chat_id)
        return True
    except Exception as e:
        logger.warning("发送日报失败 chat=%s: %s", chat_id, e)
        return False


async def send_weekly_report(bot: Bot, force: bool = False) -> bool:
    """生成并发送周报（Phase 6.3 §五）

    覆盖时间窗口：最近 7 天（含今天），start = today-6, end = today。
    """
    if not force:
        enabled = (await get_config("weekly_report_enabled")) == "1"
        if not enabled:
            logger.info("周报未启用，跳过本次执行")
            return False

    now = datetime.now(tz)
    end_str = now.strftime("%Y-%m-%d")
    start_str = (now - timedelta(days=6)).strftime("%Y-%m-%d")

    try:
        from bot.utils.reports import build_weekly_report_text
        text = await build_weekly_report_text(start_str, end_str)
    except Exception as e:
        logger.warning("构建周报文本失败: %s", e)
        return False

    chat_id = await _resolve_report_chat_id()
    try:
        await bot.send_message(chat_id=chat_id, text=text)
        logger.info("[%s ~ %s] 周报已发送到 %s", start_str, end_str, chat_id)
        return True
    except Exception as e:
        logger.warning("发送周报失败 chat=%s: %s", chat_id, e)
        return False


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


_CHANNEL_GROUP_ORDER: list[tuple[str, str]] = [
    ("all", "🌞 全天可约"),
    ("afternoon", "🌤 下午可约"),
    ("evening", "🌙 晚上可约"),
    ("other", "📝 其他时间"),
    ("full", "🈵 今日已满"),
]


_WEEKDAY_CN: tuple[str, ...] = (
    "周一", "周二", "周三", "周四", "周五", "周六", "周日",
)


def _weekday_cn(date_str: str) -> str:
    """把 YYYY-MM-DD 转中文星期；解析失败返回空字符串"""
    try:
        return _WEEKDAY_CN[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    except Exception:
        return ""


async def build_daily_checkin_payload(date_str: str) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
    """构建每日签到发布内容（Phase 3 排序 + Phase 5 分组 + Phase 6.2 模板）

    范围：当天已签到 + 启用 + daily_status != 'unavailable'
    顺序：先按统一排序规则取出，再按 5 个时间段分组，每组保留组内排序。
    频道按钮仍跳转 button_url，分组标题用 callback='noop:section' 占位按钮。

    文本：Phase 6.2 接入发布模板。流程：
        1. 计算 valid_count / weekday / city / grouped_teachers
        2. 取默认模板；若存在则 render；若无 / 渲染失败 → 回退硬编码原文案
    模板渲染失败仅 logger.warning，不影响发布。

    兼容降级：若 get_sorted_teachers 异常（旧 schema 未迁移）→ 回退原始顺序，
    不分组（保持 v1 行为），grouped_teachers 用简单列表格式。
    """
    try:
        teachers = await get_sorted_teachers(
            active_only=True,
            signed_in_date=date_str,
            exclude_unavailable=True,
        )
        groupable = True
    except Exception as e:
        logger.warning("get_sorted_teachers 失败，回退到原始顺序: %s", e)
        teachers = await get_checked_in_teachers(date_str)
        groupable = False

    if not teachers:
        return None

    # 按时间段分桶（仅在 get_sorted_teachers 成功时启用分组）
    grouped: dict[str, list[dict]] = {key: [] for key, _ in _CHANNEL_GROUP_ORDER}
    if groupable:
        for t in teachers:
            key = get_display_time_group(t)
            # unavailable 已经在 SQL 层 exclude 了，这里只可能命中其余 5 个键
            if key not in grouped:
                key = "other"
            grouped[key].append(t)

    buttons: list[list[InlineKeyboardButton]] = []
    grouped_lines: list[str] = []
    valid_count = 0

    def _flush_group(group_teachers: list[dict], header: Optional[str]) -> None:
        """按 3 个一行渲染老师 URL 按钮；header 非空时先放一个占位行。

        同时把"有效老师"的展示文本写入 grouped_lines（用于模板 {grouped_teachers}）。
        """
        nonlocal valid_count
        valid: list[dict] = []
        valid_buttons: list[InlineKeyboardButton] = []
        for t in group_teachers:
            url = normalize_url(t["button_url"])
            if not url:
                logger.warning("跳过无效老师链接: %s (%s)", t["display_name"], t["button_url"])
                continue
            label = t["button_text"] or t["display_name"]
            valid.append(t)
            valid_buttons.append(InlineKeyboardButton(text=label, url=url))
        if not valid:
            return

        # —— Keyboard 部分 ——
        if header is not None:
            buttons.append([InlineKeyboardButton(text=header, callback_data="noop:section")])
        row: list[InlineKeyboardButton] = []
        for btn in valid_buttons:
            row.append(btn)
            valid_count += 1
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        # —— 文本部分（供模板 {grouped_teachers} 使用） ——
        if header is not None:
            grouped_lines.append(header)
            for t in valid:
                grouped_lines.append(f"- {t['display_name']}")
            grouped_lines.append("")  # 段间空行
        else:
            # 无分组（回退分支）：展示更详细的一行
            for t in valid:
                grouped_lines.append(
                    f"- {t['display_name']}"
                    f"｜{t.get('region', '')}"
                    f"｜{t.get('price', '')}"
                )

    if groupable:
        # 分组渲染：标题行 + 按钮行 + 文本段
        for key, header in _CHANNEL_GROUP_ORDER:
            bucket = grouped[key]
            if not bucket:
                continue
            _flush_group(bucket, header)
    else:
        # 不分组，原始顺序：文本带"今日老师："开头
        grouped_lines.append("今日老师：")
        _flush_group(teachers, header=None)

    if not buttons or valid_count == 0:
        return None

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    grouped_text = "\n".join(grouped_lines).rstrip()

    # —— Phase 6.2：发布模板渲染 ——
    fallback_text = f"📅 {date_str} 今日开课老师 {valid_count} 位"
    text = fallback_text
    try:
        weekday = _weekday_cn(date_str)
        try:
            city = await get_config("city") or ""
        except Exception:
            city = ""

        tpl = await get_default_publish_template()
        if tpl and tpl.get("template_text"):
            rendered = render_publish_template(
                tpl["template_text"],
                {
                    "date": date_str,
                    "count": valid_count,
                    "grouped_teachers": grouped_text,
                    "city": city,
                    "weekday": weekday,
                },
            )
            if rendered and rendered.strip():
                text = rendered
    except Exception as e:
        logger.warning("发布模板渲染失败，回退默认文案: %s", e)
        text = fallback_text

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
