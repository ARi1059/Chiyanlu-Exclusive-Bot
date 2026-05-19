"""报销流程通知与文案 helper（2026-05 报销审核 + 支付宝口令发放）。

提供：
    - POWERED_BY_FOOTER 常量：所有报销相关通知页脚
    - notify_supers_reimburse_pending：报告审核通过后提醒所有超管去审核报销
    - format_user_payout_message：给用户的口令红包消息文案
    - mask_token：把口令脱敏（仅审计用），不保存完整口令到 audit log
    - safe_notify_user_reimburse_reject（UX-4.1）：驳回通知 + CTA 按钮

设计：
    - 所有通知都在 try/except 内执行；任何通知失败不应影响主流程，仅 logger.warning
    - 通知对象包含所有 super admin（list_super_admins 已含主超管 + DB is_super=1）
    - 文案统一在本文件，便于改动 / 测试静态扫描
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database import get_config, list_super_admins

logger = logging.getLogger(__name__)


# 所有报销相关通知统一带的页脚（前缀 ✳ 符号便于视觉识别）
POWERED_BY_FOOTER = "✳ Powered by @CDCChiYanLog"


def mask_token(token: str) -> str:
    """口令脱敏：前 2 后 2 字符 + 中间 ***（不保存完整口令到 audit log）。

    例如 "ABCDEFGH" → "AB***GH"；长度 ≤ 4 时返回 "***"。
    """
    if not token:
        return ""
    n = len(token)
    if n <= 4:
        return "***"
    return f"{token[:2]}***{token[-2:]}"


def format_supers_pending_text(
    *,
    reimb_id: int,
    user_id: int,
    user_label: str,
    teacher_label: str,
    review_id: int,
    amount: int,
    status: str,
) -> str:
    """生成"超管收到新报销待审核"通知文案。"""
    status_zh = {
        "pending": "待审核",
        "queued": "已 queued，待激活",
    }.get(status, status)
    return (
        "💰 有新的报销申请待审核\n\n"
        f"用户：{user_label} ({user_id})\n"
        f"老师：{teacher_label}\n"
        f"报告：#{review_id}\n"
        f"报销 ID：#{reimb_id}\n"
        f"报销金额：{amount} 元\n"
        f"状态：{status_zh}\n\n"
        "请及时进入报销审核处理。\n\n"
        f"{POWERED_BY_FOOTER}"
    )


def format_payout_waiting_token_text() -> str:
    """超管点击"同意报销"后，提示输入支付宝口令的文案。"""
    return (
        "💰 请输入支付宝口令红包口令\n\n"
        "请发送你为该用户准备的支付宝口令红包口令。\n"
        "发送后 Bot 会展示确认页，确认后才会发给用户。\n\n"
        f"{POWERED_BY_FOOTER}"
    )


def format_payout_confirm_text(
    *,
    user_id: int,
    user_label: str,
    amount: int,
    token: str,
) -> str:
    """超管输入口令后的确认页文案（含完整口令，仅在 FSM 临时持有期间展示）。"""
    return (
        "💰 确认发送支付宝口令红包\n\n"
        f"用户：{user_label} ({user_id})\n"
        f"报销金额：{amount} 元\n"
        "口令：\n"
        f"{token}\n\n"
        "确认发送给用户并完成本次报销？\n\n"
        f"{POWERED_BY_FOOTER}"
    )


def format_user_payout_message(*, token: str, amount: int) -> str:
    """给用户的"口令红包已发放"消息文案。"""
    return (
        "💰 报销已通过\n\n"
        "你的报销申请已通过，请使用以下支付宝口令红包领取：\n\n"
        f"{token}\n\n"
        f"金额：{amount} 元\n\n"
        "如有问题请联系管理员。\n\n"
        f"{POWERED_BY_FOOTER}"
    )


def format_payout_done_text(
    *,
    user_label: str,
    user_id: int,
    amount: int,
) -> str:
    """口令发送成功后给超管的总结文案。"""
    return (
        "✅ 报销口令已发送，流程完成\n\n"
        f"用户：{user_label} ({user_id})\n"
        f"金额：{amount} 元\n\n"
        f"{POWERED_BY_FOOTER}"
    )


async def notify_supers_reimburse_pending(
    bot: Bot,
    *,
    reimb_id: int,
    user_id: int,
    user_label: str,
    teacher_label: str,
    review_id: int,
    amount: int,
    status: str,
) -> None:
    """通知所有超管：有新的报销申请待审核。

    - 通知对象：list_super_admins()（含主超管 + DB is_super=1，已去重）
    - 任何超管发送失败：logger.warning，继续通知其他超管
    - 通知失败永不影响调用方主流程（report approve）
    """
    from bot.keyboards.admin_kb import reimburse_pending_super_notice_kb
    try:
        supers = await list_super_admins()
    except Exception as e:
        logger.warning(
            "notify_supers_reimburse_pending: list_super_admins 失败: %s", e,
        )
        return
    if not supers:
        return
    text = format_supers_pending_text(
        reimb_id=reimb_id,
        user_id=user_id,
        user_label=user_label,
        teacher_label=teacher_label,
        review_id=review_id,
        amount=amount,
        status=status,
    )
    kb = reimburse_pending_super_notice_kb()
    for super_id in supers:
        try:
            await bot.send_message(chat_id=super_id, text=text, reply_markup=kb)
        except Exception as e:
            logger.warning(
                "notify_supers_reimburse_pending 发送失败 super=%s reimb=%s: %s",
                super_id, reimb_id, e,
            )


def format_user_reimburse_reject_text(
    *,
    reimb_id: int,
    amount: int,
    reason: str,
) -> str:
    """给用户的"报销驳回"通知文案（UX-4.1）。"""
    return (
        f"❌ 你的报销申请 #{reimb_id} 未通过\n\n"
        f"金额：{amount} 元\n"
        f"原因：{reason}\n\n"
        f"{POWERED_BY_FOOTER}"
    )


async def build_user_reimburse_reject_kb() -> InlineKeyboardMarkup:
    """构造驳回通知 CTA keyboard（UX-4.1）。

    布局：
        - [📩 联系客服申诉]   url=<contact_url>     仅当 config 中存在客服链接时显示
        - [📋 我的报销]       callback=user:reimburse   始终显示

    客服链接读取优先级：reimburse_contact_url → lottery_contact_url；
    两者均空时只显示「我的报销」一个按钮。
    """
    contact_url = (await get_config("reimburse_contact_url") or "").strip()
    if not contact_url:
        contact_url = (await get_config("lottery_contact_url") or "").strip()
    rows: list[list[InlineKeyboardButton]] = []
    if contact_url:
        rows.append([
            InlineKeyboardButton(text="📩 联系客服申诉", url=contact_url),
        ])
    rows.append([
        InlineKeyboardButton(text="📋 我的报销", callback_data="user:reimburse"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def safe_notify_user_reimburse_reject(
    bot: Bot,
    *,
    user_id: int,
    reimb_id: int,
    amount: int,
    reason: str,
) -> bool:
    """给用户发送报销驳回通知（含 CTA 按钮），失败容错（UX-4.1）。

    返回值：True 表示发送成功，False 表示失败。
    任何异常都被捕获并 logger.info，不向上抛——驳回审批主流程不应因通知失败而回滚。
    """
    text = format_user_reimburse_reject_text(
        reimb_id=reimb_id, amount=amount, reason=reason,
    )
    try:
        kb = await build_user_reimburse_reject_kb()
        await bot.send_message(chat_id=user_id, text=text, reply_markup=kb)
        return True
    except Exception as e:
        logger.info(
            "safe_notify_user_reimburse_reject 失败 user=%s reimb=%s: %s",
            user_id, reimb_id, e,
        )
        return False


async def safe_send_user_payout(
    bot: Bot,
    *,
    user_id: int,
    token: str,
    amount: int,
) -> tuple[bool, Optional[str]]:
    """给用户发送口令红包消息，返回 (ok, error_text)。

    必须在调用方根据 ok 判断后才能更新报销状态（spec 要求"发送成功后才标记完成"）。
    """
    text = format_user_payout_message(token=token, amount=amount)
    try:
        await bot.send_message(chat_id=user_id, text=text)
        return True, None
    except Exception as e:
        logger.warning(
            "safe_send_user_payout 发送失败 user=%s amount=%s: %s",
            user_id, amount, e,
        )
        return False, f"{type(e).__name__}: {e}"
