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


async def get_reimburse_contact_url() -> Optional[str]:
    """读取报销申诉客服 URL（UX-4.1 + UX-6.4 共用）。

    读取优先级：
        - config["reimburse_contact_url"]   报销专用客服（未来可独立配置）
        - config["lottery_contact_url"]     抽奖客服（fallback，运营通常共用一个群）

    两者均空 / 仅空白时返回 None，调用方应按"不显示申诉按钮"处理。
    """
    contact_url = (await get_config("reimburse_contact_url") or "").strip()
    if not contact_url:
        contact_url = (await get_config("lottery_contact_url") or "").strip()
    return contact_url or None


async def build_user_reimburse_reject_kb() -> InlineKeyboardMarkup:
    """构造驳回通知 CTA keyboard（UX-4.1）。

    布局：
        - [📩 联系客服申诉]   url=<contact_url>     仅当 config 中存在客服链接时显示
        - [📋 我的报销]       callback=user:reimburse   始终显示

    客服链接通过 get_reimburse_contact_url() 解析（与 UX-6.4 用户侧申诉按钮共用）。
    """
    contact_url = await get_reimburse_contact_url()
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


def format_reimburse_ineligibility_hint(
    *,
    amount: int,
    points: int,
    min_pts: int,
    reason: Optional[str] = None,
    pool_remaining: Optional[int] = None,
) -> str:
    """返回"为什么没看到报销选项"的温和提示文案（UX-5.4）。

    2026-05-21 扩展：新增 feature_off / pool_exhausted 两个 reason 分支，
    对齐评价前置的 [is_user_reimburse_eligible_for_review] 预判结果。

    `reason` 显式传入时按其分支渲染（推荐：调用方直接把预判结果传进来）；
    若未传，回退到「按 amount / points 反推」的旧行为，保持向后兼容。

    所有分支：
        - "feature_off"      → 报销功能当前暂关闭
        - "amount_zero" /
          amount <= 0        → 老师价位档不在报销范围
        - "pool_exhausted"   → 本月报销池已用完
        - "below_threshold" /
          points < min_pts   → 距离报销门槛还差 X 分

    调用方应**仅在 feature_enabled=True**或想显式告知功能关闭时调用；
    feature OFF 时旧行为保持静默；本批新增 feature_off 分支供需要显式
    告知的场景使用（如提交成功页尾注）。
    """
    if reason == "feature_off":
        return "💡 报销功能当前暂关闭，敬请期待。"
    if reason == "pool_exhausted":
        remaining = pool_remaining if pool_remaining is not None else 0
        return (
            f"💡 本月报销池已用完（剩余 {max(0, remaining)} 元），"
            "下月再来。"
        )
    # 价位档不符 —— 显式 reason 或 amount<=0 反推
    if reason == "amount_zero" or amount <= 0:
        return (
            "💡 老师价位档不在报销范围"
            "（仅 ≦800 元 / 900 元 / ≧1000 元三档可申请）"
        )
    # 默认走积分不足分支（含旧调用方的兼容路径）
    diff = max(0, min_pts - points)
    return (
        f"💡 当前积分 {points}（报销门槛 {min_pts}），距离还差 {diff} 分。\n"
        "可通过提交评价等方式获得积分。"
    )


def format_user_reimburse_activated_text(
    *,
    reimb_id: int,
    amount: int,
) -> str:
    """给用户的"queued 激活进入审核队列"通知文案（UX-4.4）。"""
    return (
        f"📋 你的报销申请 #{reimb_id} 已激活进入审核队列\n\n"
        f"金额：{amount} 元\n"
        "管理员将在审核完成后通过本 bot 通知你。\n\n"
        f"{POWERED_BY_FOOTER}"
    )


def build_user_reimburse_activated_kb() -> InlineKeyboardMarkup:
    """构造"queued 激活"通知 CTA keyboard（UX-4.4）。

    布局：
        - [📋 我的报销]   callback=user:reimburse  含当前状态
        - [🏠 返回主菜单] callback=user:main       兜底

    与 build_user_reimburse_approved_kb 同布局；语义不同——这里是
    "进入审核队列"中间状态通知，不是"已通过"终态。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 我的报销", callback_data="user:reimburse")],
        [InlineKeyboardButton(text="🏠 返回主菜单", callback_data="user:main")],
    ])


async def safe_notify_user_reimburse_activated(
    bot: Bot,
    *,
    user_id: int,
    reimb_id: int,
    amount: int,
) -> bool:
    """给用户发送"queued 激活进入审核队列"通知（含 CTA 按钮），失败容错（UX-4.4）。

    返回值：True 表示发送成功，False 表示失败。
    异常被捕获并 logger.warning 后吞；queued 激活主流程不应因通知失败而 break。

    注意：本函数刻意**不**写 mark_reimbursement_notified —— POLICY.md Part II
    §12.7 标注该字段语义为"已通过/驳回 终态通知"，激活只是中间状态切换。
    """
    text = format_user_reimburse_activated_text(reimb_id=reimb_id, amount=amount)
    try:
        kb = build_user_reimburse_activated_kb()
        await bot.send_message(chat_id=user_id, text=text, reply_markup=kb)
        return True
    except Exception as e:
        logger.warning(
            "safe_notify_user_reimburse_activated 失败 user=%s reimb=%s: %s",
            user_id, reimb_id, e,
        )
        return False


def build_user_reimburse_approved_kb() -> InlineKeyboardMarkup:
    """构造"报销通过 / 口令已发放"通知 CTA keyboard（UX-4.2）。

    布局：
        - [📋 我的报销]   callback=user:reimburse   含本月统计、池剩余、最近 5 笔
        - [🏠 返回主菜单] callback=user:main        兜底

    "报销池剩余"未做独立按钮——总额信息已在 user:reimburse 总览页呈现，
    单独入口会与「我的报销」语义重叠。
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 我的报销", callback_data="user:reimburse")],
        [InlineKeyboardButton(text="🏠 返回主菜单", callback_data="user:main")],
    ])


async def safe_send_user_payout(
    bot: Bot,
    *,
    user_id: int,
    token: str,
    amount: int,
) -> tuple[bool, Optional[str]]:
    """给用户发送口令红包消息，返回 (ok, error_text)。

    必须在调用方根据 ok 判断后才能更新报销状态（spec 要求"发送成功后才标记完成"）。
    UX-4.2：随消息附 CTA keyboard（我的报销 / 主菜单），让用户兑换完口令后
    能 1 次点击回查本月统计或回主菜单，而不是面对纯文本死胡同。
    """
    text = format_user_payout_message(token=token, amount=amount)
    kb = build_user_reimburse_approved_kb()
    try:
        await bot.send_message(chat_id=user_id, text=text, reply_markup=kb)
        return True, None
    except Exception as e:
        logger.warning(
            "safe_send_user_payout 发送失败 user=%s amount=%s: %s",
            user_id, amount, e,
        )
        return False, f"{type(e).__name__}: {e}"
