#!/usr/bin/env python3
"""一次性同步脚本：把"出击报销八折"超链接 footer 补到旧评价上（2026-05-20）。

背景：
    2026-05-20 给讨论群评价文案 footer 追加了一行 HTML 超链接「出击报销八折」；
    新评价自动带；旧评价（已 publish 到讨论群）需要本脚本回填。

用法：
    cd /opt/Chiyanlu-Exclusive-Bot   # 或你的项目根目录
    # 1) 先 dry-run 看影响面（默认行为）
    python3 scripts/sync_review_promo_footer.py
    # 2) 确认无误后真改
    python3 scripts/sync_review_promo_footer.py --execute
    # 3) 可选：先处理前 N 条试水
    python3 scripts/sync_review_promo_footer.py --execute --limit 20
    # 4) 可选：自定义节流（默认 1500ms / 次）
    python3 scripts/sync_review_promo_footer.py --execute --throttle-ms 2000

安全特性：
    - 默认 dry-run；--execute 才真改
    - 节流默认 1.5 秒/次（远低于 Telegram bot edit flood 线）
    - RetryAfter 自动 sleep 后续跑
    - "message is not modified" → noop 计数（已是新格式）
    - "message to edit not found" → 标记跳过，继续下一条
    - 进度日志：每 10 条 / 每分钟打印一次累计
    - 失败明细写到 logs/sync_review_promo_footer_<ts>.log

不修改 DB：本脚本只 SELECT 评价 + 调 Telegram edit；不动 teacher_reviews 任何字段。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

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
    """组装单条评价的新 text + keyboard；缺评价 / 缺老师返回 (None, reason)。"""
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
    return (chat_id, msg_id, text, kb), None


async def edit_one_review(
    bot: Bot,
    review_id: int,
    bot_username: str,
    *,
    dry_run: bool,
    logger: logging.Logger,
) -> str:
    """编辑单条评价；返回简短结果代码：
        ok / noop / skip:<reason> / fail:<reason>
    """
    built, skip_reason = await _build_new_text_and_kb(bot_username, review_id)
    if not built:
        return f"skip:{skip_reason}"
    chat_id, msg_id, text, kb = built

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


# ============ 主流程 ============


async def run(args: argparse.Namespace) -> int:
    logger = _setup_logger(args.execute)
    logger.info(
        "模式：%s  节流：%dms  限量：%s",
        "EXECUTE" if args.execute else "dry-run",
        args.throttle_ms,
        args.limit if args.limit else "无",
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

        # 汇总
        logger.info("=" * 60)
        logger.info("完成。模式=%s", "EXECUTE" if args.execute else "dry-run")
        logger.info("候选总数：%d", len(review_ids))
        for k in sorted(counts.keys()):
            logger.info("  %-20s %d", k, counts[k])
        if not args.execute and counts.get("ok", 0) > 0:
            logger.info("【dry-run】通过；可加 --execute 真改")
        return 0
    finally:
        # aiogram 3.x：Bot session 需显式 close
        try:
            await bot.session.close()
        except Exception:
            pass


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="同步讨论群旧评价 footer，补加「出击报销八折」超链接。",
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
