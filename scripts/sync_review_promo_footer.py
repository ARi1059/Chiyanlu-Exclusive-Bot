#!/usr/bin/env python3
"""一次性同步脚本：把"出击报销八折"超链接 footer 补到旧评价上（2026-05-20）。

背景：
    2026-05-20 给讨论群评价文案 footer 追加了一行 HTML 超链接「出击报销八折」；
    新评价自动带；旧评价（已 publish 到讨论群）需要本脚本回填。

用法：
    cd /opt/Chiyanlu-Exclusive-Bot   # 或你的项目根目录
    # 1) 先 dry-run 看影响面（默认行为）
    python3 scripts/sync_review_promo_footer.py
    # 2) 确认无误后真改 + 默认会 DM 通知对应老师
    python3 scripts/sync_review_promo_footer.py --execute
    # 3) 真改但不通知老师
    python3 scripts/sync_review_promo_footer.py --execute --no-notify
    # 4) 可选：先处理前 N 条试水
    python3 scripts/sync_review_promo_footer.py --execute --limit 20
    # 5) 可选：自定义 edit 节流（默认 1500ms / 次）
    python3 scripts/sync_review_promo_footer.py --execute --throttle-ms 2000
    # 6) 可选：自定义 notify 节流（默认 1500ms / 次老师）
    python3 scripts/sync_review_promo_footer.py --execute --notify-throttle-ms 2000

安全特性：
    - 默认 dry-run；--execute 才真改
    - edit / notify 节流默认 1.5 秒/次（远低于 Telegram bot flood 线）
    - RetryAfter 自动 sleep 后续跑
    - "message is not modified" → noop 计数（已是新格式，不计入老师通知）
    - "message to edit not found" → 标记跳过，继续下一条
    - 进度日志：每 10 条 / 每分钟打印一次累计
    - 失败明细写到 logs/sync_review_promo_footer_<ts>.log

老师 DM 通知（2026-05-20 新增）：
    - 仅 --execute 模式下，仅对真实发生 edit（status=ok）的评价发通知；
      noop / skip / fail 不通知，避免误扰
    - 按老师聚合：一位老师 N 条评价更新 = 1 条 DM（含总数 + 评价链接列表）
    - 推送对象：teachers.user_id（= 老师本人的 TG id，与项目其他模块一致）
    - 老师未启动过 bot → TelegramForbiddenError 仅 warning，不阻塞其他老师
    - 默认开启；用 --no-notify 关闭

不修改 DB：本脚本只 SELECT 评价 + 调 Telegram edit + 发 DM；不动任何字段。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# 允许 `python3 scripts/sync_review_promo_footer.py` 直接跑：把项目根加入 sys.path
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from bot.config import config
from bot.database import get_db, get_teacher, get_teacher_review
from bot.utils.review_comment import (
    REIMBURSE_PROMO_TEXT,
    REIMBURSE_PROMO_URL,
    render_review_comment,
)


# ============ 日志 ============


def _setup_logger(execute: bool) -> logging.Logger:
    logger = logging.getLogger("sync_review_promo_footer")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # 真改才落文件日志（dry-run 噪音不多，stdout 够看）
    if execute:
        logs_dir = _ROOT / "logs"
        logs_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = logs_dir / f"sync_review_promo_footer_{ts}.log"
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.info("详细日志：%s", path)
    return logger


# ============ DB ============


async def list_published_review_ids() -> list[int]:
    """所有已发布到讨论群的评价 id（按 published_at 升序）。"""
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT id FROM teacher_reviews
               WHERE discussion_msg_id IS NOT NULL
                 AND discussion_chat_id IS NOT NULL
               ORDER BY COALESCE(published_at, created_at) ASC""",
        )
        rows = await cur.fetchall()
        return [int(r[0]) for r in rows]
    finally:
        await db.close()


# ============ 单条编辑 ============


async def _build_new_text_and_kb(bot_username: str, review_id: int):
    """组装单条评价的新 text + keyboard；缺评价 / 缺老师返回 (None, reason)。

    返回值 tuple 形：(teacher_id, chat_id, msg_id, text, kb)。teacher_id
    供后续按老师聚合通知使用——必须随同 chat/msg 一并取出，避免通知阶段
    再回查 DB（teacher_reviews 是只读 SELECT，避免重复 IO）。
    """
    review = await get_teacher_review(review_id)
    if not review:
        return None, "no_review"
    teacher = await get_teacher(review["teacher_id"])
    if not teacher:
        return None, "no_teacher"
    chat_id = review.get("discussion_chat_id")
    msg_id = review.get("discussion_msg_id")
    if not chat_id or not msg_id:
        return None, "no_msg_ref"
    # 一次性同步脚本：使用 2026-05-20 的默认 footer 文案 / URL（与脚本目的
    # 一致，回填旧评价至引入 footer 时的格式）。如运营已 config 化 footer
    # 且想用最新值，可在脚本运行前先 sqlite3 SET 对应 config，再用此脚本回填。
    text, kb = render_review_comment(
        review, teacher, bot_username=bot_username,
        promo_text=REIMBURSE_PROMO_TEXT,
        promo_url=REIMBURSE_PROMO_URL,
    )
    return (int(review["teacher_id"]), chat_id, msg_id, text, kb), None


async def edit_one_review(
    bot: Bot,
    review_id: int,
    bot_username: str,
    *,
    dry_run: bool,
    logger: logging.Logger,
    on_edited: Optional[Callable[[int, int, int, int], None]] = None,
) -> str:
    """编辑单条评价；返回简短结果代码：
        ok / noop / skip:<reason> / fail:<reason>

    on_edited(teacher_id, chat_id, msg_id) 仅当真正发生 edit（status=ok 且
    非 dry-run）时调用，供主流程收集"需要通知老师"的评价；dry-run / noop /
    skip / fail 不调用，避免误推。
    """
    built, skip_reason = await _build_new_text_and_kb(bot_username, review_id)
    if not built:
        return f"skip:{skip_reason}"
    teacher_id, chat_id, msg_id, text, kb = built

    if dry_run:
        # 仅做 render 测试；不发请求
        return "ok"

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        if on_edited is not None:
            on_edited(review_id, teacher_id, chat_id, msg_id)
        return "ok"
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message is not modified" in msg:
            return "noop"
        if "message to edit not found" in msg or "message to be edited" in msg:
            logger.warning(
                "review=%s 消息已不存在 (chat=%s msg=%s): %s",
                review_id, chat_id, msg_id, e,
            )
            return "fail:msg_not_found"
        if "can't be edited" in msg or "message can't be edited" in msg:
            return "fail:msg_uneditable"
        logger.warning("review=%s BadRequest: %s", review_id, e)
        return f"fail:bad_request"
    except TelegramForbiddenError as e:
        logger.warning("review=%s forbidden (kicked/banned): %s", review_id, e)
        return "fail:forbidden"
    except TelegramRetryAfter:
        raise  # 主循环处理
    except TelegramNetworkError as e:
        logger.warning("review=%s 网络错误: %s", review_id, e)
        return "fail:network"
    except Exception as e:
        logger.exception("review=%s 未知错误: %s", review_id, e)
        return f"fail:{type(e).__name__}"


# ============ 老师 DM 通知（2026-05-20 新增） ============


def _build_review_link(chat_id: int, msg_id: int) -> Optional[str]:
    """构造讨论群消息 t.me 直链。

    讨论群 chat_id 形如 -100<rest>；t.me 私有链接形如
    https://t.me/c/<rest>/<msg_id>，对群成员可点击直达。

    非 -100 开头（理论上讨论群必带；防御性）→ 返回 None，调用方降级显示。
    """
    s = str(chat_id)
    if not s.startswith("-100"):
        return None
    trimmed = s[4:]
    if not trimmed:
        return None
    return f"https://t.me/c/{trimmed}/{int(msg_id)}"


def _build_teacher_notify_text(
    teacher_display_name: str,
    items: list[tuple[int, int, int]],
) -> str:
    """渲染单位老师的聚合 DM 文本（HTML）。

    items: [(review_id, chat_id, msg_id), ...]
    """
    n = len(items)
    lines: list[str] = []
    safe_name = teacher_display_name or "老师"
    # HTML escape 简化：老师 display_name 入库时多为纯中文 / 字母数字；
    # 这里仅替换 <、>、& 三个 HTML 关键字符，避免破坏外层 <b> 标签。
    for ch, rep in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;")):
        safe_name = safe_name.replace(ch, rep)
    lines.append(f"📢 <b>{safe_name}</b> 您好，您的讨论群评价 footer 已批量更新。")
    lines.append("")
    lines.append(f"本次同步 <b>{n}</b> 条评价：")
    # 最多列 20 条，多余的折叠成"还有 N 条..."避免单条 DM 超长
    MAX_LIST = 20
    shown = items[:MAX_LIST]
    for idx, (rid, ch_id, m_id) in enumerate(shown, 1):
        link = _build_review_link(ch_id, m_id)
        if link:
            lines.append(f"  {idx}. <a href=\"{link}\">评价 #{rid}</a>")
        else:
            lines.append(f"  {idx}. 评价 #{rid}")
    if n > MAX_LIST:
        lines.append(f"  …还有 {n - MAX_LIST} 条")
    lines.append("")
    lines.append("更新内容：评价底部追加了「出击报销八折」推广链接，无需您操作。")
    return "\n".join(lines)


async def _send_teacher_notification(
    bot: Bot,
    teacher_id: int,
    text: str,
    *,
    dry_run: bool,
    logger: logging.Logger,
) -> str:
    """给单位老师发 DM；返回结果代码：ok / fail:<reason>。

    dry-run 仅校验 text 长度（>4096 拒绝），不真发；RetryAfter 由上层重试。
    """
    if len(text) > 4096:
        logger.warning(
            "teacher=%s 通知文本超长 (%d > 4096)，将被裁剪", teacher_id, len(text),
        )
        text = text[:4090] + "\n…"

    if dry_run:
        return "ok"

    try:
        await bot.send_message(
            chat_id=teacher_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return "ok"
    except TelegramForbiddenError as e:
        # 老师没启动过 bot / 屏蔽了 bot —— 静默 warning，不阻塞其他老师
        logger.warning("teacher=%s DM forbidden (未启动 bot?): %s", teacher_id, e)
        return "fail:forbidden"
    except TelegramBadRequest as e:
        logger.warning("teacher=%s DM BadRequest: %s", teacher_id, e)
        return "fail:bad_request"
    except TelegramRetryAfter:
        raise
    except TelegramNetworkError as e:
        logger.warning("teacher=%s DM 网络错误: %s", teacher_id, e)
        return "fail:network"
    except Exception as e:
        logger.exception("teacher=%s DM 未知错误: %s", teacher_id, e)
        return f"fail:{type(e).__name__}"


async def notify_teachers_aggregated(
    bot: Bot,
    edits_by_teacher: dict[int, list[tuple[int, int, int]]],
    *,
    dry_run: bool,
    throttle_ms: int,
    logger: logging.Logger,
) -> dict[str, int]:
    """按老师聚合发 DM。

    edits_by_teacher: { teacher_id: [(review_id, chat_id, msg_id), ...] }
    返回各类结果计数（ok / fail:* / skip:no_teacher / skip:no_review_id 等）。
    """
    counts: dict[str, int] = {}
    if not edits_by_teacher:
        logger.info("无需通知（没有真实发生 edit 的评价）。")
        return counts

    throttle_s = max(0.0, throttle_ms / 1000.0)
    teachers_sorted = sorted(edits_by_teacher.items(), key=lambda kv: kv[0])
    total_teachers = len(teachers_sorted)
    logger.info("=" * 60)
    logger.info("准备 DM 通知：%d 位老师", total_teachers)

    for idx, (teacher_id, items) in enumerate(teachers_sorted, 1):
        teacher = await get_teacher(teacher_id)
        if not teacher:
            counts["skip:no_teacher"] = counts.get("skip:no_teacher", 0) + 1
            logger.warning("teacher=%s 已不存在，跳过通知（%d 条评价）",
                           teacher_id, len(items))
            continue
        display_name = teacher.get("display_name") or teacher.get("username") or "老师"
        text = _build_teacher_notify_text(display_name, items)

        while True:
            try:
                res = await _send_teacher_notification(
                    bot, teacher_id, text,
                    dry_run=dry_run, logger=logger,
                )
                break
            except TelegramRetryAfter as ra:
                wait = int(ra.retry_after) + 1
                logger.warning(
                    "Telegram RetryAfter %ds（notify teacher=%s），等待后继续",
                    wait, teacher_id,
                )
                await asyncio.sleep(wait)
                continue

        counts[res] = counts.get(res, 0) + 1
        logger.info(
            "[%d/%d] teacher=%s display=%s 评价数=%d → %s",
            idx, total_teachers, teacher_id, display_name, len(items), res,
        )

        if not dry_run and idx < total_teachers:
            await asyncio.sleep(throttle_s)

    logger.info("DM 通知完成：%s", counts)
    return counts


# ============ 主流程 ============


async def run(args: argparse.Namespace) -> int:
    logger = _setup_logger(args.execute)
    notify_enabled = args.execute and args.notify
    logger.info(
        "模式：%s  edit 节流：%dms  限量：%s  通知老师：%s（notify 节流：%dms）",
        "EXECUTE" if args.execute else "dry-run",
        args.throttle_ms,
        args.limit if args.limit else "无",
        "开" if notify_enabled else "关",
        args.notify_throttle_ms,
    )

    review_ids = await list_published_review_ids()
    total = len(review_ids)
    if total == 0:
        logger.info("没有已发布到讨论群的评价。退出。")
        return 0

    if args.limit and args.limit > 0:
        review_ids = review_ids[: args.limit]

    logger.info("候选 %d / %d 条已发布评价", len(review_ids), total)
    if not args.execute:
        logger.info("【dry-run】仅渲染验证；加 --execute 才真改")

    bot = Bot(token=config.bot_token)
    try:
        me = await bot.get_me()
        bot_username = me.username
        logger.info("Bot：@%s", bot_username)

        # 收集真实发生 edit 的评价，供后续按老师聚合通知。
        # 结构：{ teacher_id: [(review_id, chat_id, msg_id), ...] }
        edits_by_teacher: dict[int, list[tuple[int, int, int]]] = {}

        def _on_edited(review_id: int, teacher_id: int, chat_id: int, msg_id: int):
            edits_by_teacher.setdefault(teacher_id, []).append(
                (review_id, int(chat_id), int(msg_id))
            )

        counts: dict[str, int] = {}
        throttle_s = max(0.0, args.throttle_ms / 1000.0)
        start_ts = time.time()
        last_log_ts = start_ts

        for idx, rid in enumerate(review_ids, 1):
            # 自动重试 RetryAfter
            while True:
                try:
                    res = await edit_one_review(
                        bot, rid, bot_username,
                        dry_run=not args.execute, logger=logger,
                        on_edited=_on_edited,
                    )
                    break
                except TelegramRetryAfter as ra:
                    wait = int(ra.retry_after) + 1
                    logger.warning(
                        "Telegram RetryAfter %ds（review=%s），等待后继续",
                        wait, rid,
                    )
                    await asyncio.sleep(wait)
                    continue

            counts[res] = counts.get(res, 0) + 1

            # 节流
            if args.execute and idx < len(review_ids):
                await asyncio.sleep(throttle_s)

            # 进度：每 10 条 或 每 60 秒
            now = time.time()
            if idx % 10 == 0 or (now - last_log_ts) >= 60 or idx == len(review_ids):
                last_log_ts = now
                elapsed = now - start_ts
                rate = idx / elapsed if elapsed > 0 else 0.0
                logger.info(
                    "进度 %d/%d  耗时 %.0fs  速率 %.2f/s  统计 %s",
                    idx, len(review_ids), elapsed, rate, counts,
                )

        # 汇总（edit 阶段）
        logger.info("=" * 60)
        logger.info("Edit 阶段完成。模式=%s", "EXECUTE" if args.execute else "dry-run")
        logger.info("候选总数：%d", len(review_ids))
        for k in sorted(counts.keys()):
            logger.info("  %-20s %d", k, counts[k])
        if not args.execute and counts.get("ok", 0) > 0:
            logger.info("【dry-run】通过；可加 --execute 真改")

        # 通知阶段
        if notify_enabled:
            affected_teachers = len(edits_by_teacher)
            affected_reviews = sum(len(v) for v in edits_by_teacher.values())
            logger.info(
                "收集到 %d 位老师的 %d 条真实编辑评价，准备发 DM 通知",
                affected_teachers, affected_reviews,
            )
            notify_counts = await notify_teachers_aggregated(
                bot, edits_by_teacher,
                dry_run=False,
                throttle_ms=args.notify_throttle_ms,
                logger=logger,
            )
            logger.info("=" * 60)
            logger.info("Notify 阶段完成。覆盖老师：%d，评价：%d",
                        affected_teachers, affected_reviews)
            for k in sorted(notify_counts.keys()):
                logger.info("  %-20s %d", k, notify_counts[k])
        elif args.execute and not args.notify:
            logger.info("已关闭老师通知（--no-notify）；如需补发可单独再跑通知逻辑。")
        elif not args.execute and args.notify:
            logger.info("【dry-run】跳过通知发送（需 --execute）。")

        return 0
    finally:
        # aiogram 3.x：Bot session 需显式 close
        try:
            await bot.session.close()
        except Exception:
            pass


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="同步讨论群旧评价 footer，补加「出击报销八折」超链接；"
                    "可选按老师聚合 DM 通知。",
    )
    p.add_argument(
        "--execute", action="store_true",
        help="真改 Telegram 消息（不加默认 dry-run）",
    )
    p.add_argument(
        "--limit", type=int, default=0,
        help="只处理前 N 条（0=全部）",
    )
    p.add_argument(
        "--throttle-ms", dest="throttle_ms", type=int, default=1500,
        help="每次 edit 之间的节流毫秒数（默认 1500，约 40 次/分钟）",
    )
    # --notify / --no-notify：默认开启（仅在 --execute 下生效）
    notify_group = p.add_mutually_exclusive_group()
    notify_group.add_argument(
        "--notify", dest="notify", action="store_true", default=True,
        help="同步完成后按老师聚合 DM 通知（默认开启；仅 --execute 下生效）",
    )
    notify_group.add_argument(
        "--no-notify", dest="notify", action="store_false",
        help="禁用老师 DM 通知（即使 --execute 也不发）",
    )
    p.add_argument(
        "--notify-throttle-ms", dest="notify_throttle_ms", type=int, default=1500,
        help="DM 通知每位老师之间的节流毫秒数（默认 1500）",
    )
    return p.parse_args()


def main():
    args = _parse_args()
    try:
        rc = asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n用户中断，已停止。", file=sys.stderr)
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
