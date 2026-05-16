"""老师详情页 handlers（Phase 2）

Callbacks:
    teacher:view:<teacher_id>         展示老师详情（私聊场景）
    teacher:toggle_fav:<teacher_id>   切换该老师的收藏状态并刷新详情页

详情页入口（Phase 2 后所有这些位置都会进入此页）：
    - 搜索结果（艺名精确命中 / 单人命中 / 多人列表）
    - 我的收藏列表
    - 收藏开课列表
    - 最近看过列表
    - 今日开课老师（私聊菜单）

频道 14:00 自动发布 / 群组关键词响应 不走详情页，行为不变。
"""

import json
import logging
from datetime import datetime

from aiogram import Router, F, types
from pytz import timezone

from bot.config import config
from bot.database import (
    add_favorite,
    count_teacher_favoriters,
    get_similar_teachers,
    get_teacher,
    get_teacher_daily_status,
    get_user,
    is_checked_in,
    is_effective_featured,
    is_favorited,
    list_recent_teacher_views,
    record_teacher_view,
    set_user_notify_enabled,
    toggle_favorite,
    update_user_tags_from_teacher_action,
    upsert_user,
)
from bot.keyboards.user_kb import (
    back_to_user_main_kb,
    recent_views_kb,
    teacher_detail_kb,
    teacher_detail_list_kb,
)

logger = logging.getLogger(__name__)

router = Router(name="teacher_detail")

_tz = timezone(config.timezone)


def _today_str() -> str:
    return datetime.now(_tz).strftime("%Y-%m-%d")


def _parse_tags(teacher: dict) -> list:
    """从 teacher.tags JSON 安全解析为列表"""
    try:
        raw = teacher.get("tags") if isinstance(teacher, dict) else None
        if not raw:
            return []
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return []
        return [str(t) for t in parsed if t]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def _derive_hot_text(teacher: dict, fav_count: int, today_str: str) -> str:
    """Phase 7.1：热度展示规则

    优先级：
        1. 有效推荐 → "近期推荐"
        2. hot_score >= 100 → "近期热门"
        3. fav_count >= 5 → "多人收藏"
        4. 否则 → "普通展示"

    任何字段缺失 / 异常 → 安全退回到 "普通展示"。
    """
    try:
        if is_effective_featured(teacher, today_str):
            return "近期推荐"
    except Exception:
        pass
    try:
        if int(teacher.get("hot_score") or 0) >= 100:
            return "近期热门"
    except (ValueError, TypeError):
        pass
    if fav_count >= 5:
        return "多人收藏"
    return "普通展示"


def _derive_fit_text(teacher: dict, tags: list) -> str:
    """Phase 7.1：适合人群模板（无 AI，纯规则拼装）

    输入：
        teacher: dict（含 region / price）
        tags:    list[str]（已解析）

    规则：
        - 标签含"御姐" → 喜欢成熟气质
        - 标签含"甜妹" → 喜欢甜美亲和风格
        - 标签含"高颜值" 或 "颜值" → 看重颜值表现
        - 有 price → 预算在 {price} 左右
        - 有 region → 想找 {region} 附近
        - 全部缺失 → 兜底文案
    """
    parts: list[str] = []
    tag_set = {str(t).strip() for t in tags if t and str(t).strip()}

    if "御姐" in tag_set:
        parts.append("喜欢成熟气质")
    if "甜妹" in tag_set:
        parts.append("喜欢甜美亲和风格")
    if "高颜值" in tag_set or "颜值" in tag_set:
        parts.append("看重颜值表现")

    price = (teacher.get("price") or "").strip() if isinstance(teacher, dict) else ""
    if price:
        parts.append(f"预算在 {price} 左右")

    region = (teacher.get("region") or "").strip() if isinstance(teacher, dict) else ""
    if region:
        parts.append(f"想找 {region} 附近")

    if not parts:
        return "适合想快速了解并联系老师的用户。"
    return "适合" + "、".join(parts) + "的用户。"


def format_teacher_detail_text(
    teacher: dict,
    *,
    is_signed_in_today: bool,
    is_fav: bool,
    daily_status_row: dict | None = None,
    fav_count: int = 0,
    today_str: str = "",
) -> str:
    """Phase 7.1：决策型信息层级（spec §三）

    结构：
        👤 {display_name}

        📍 地区：...
        💰 价格：...
        📅 今日：...
        ⏰ 可约时间：...
        🔥 热度：...
        ⭐ 你的状态：...

        🏷 特点：
        {tags 用 ｜ 连接}

        📌 适合：
        {fit_text}

    daily_status_row（Phase 5）字段：
        status: available / full / unavailable / unknown
        available_time: 全天 / 下午 / 晚上 / 自定义 / 未设置 / NULL
        note: 自由文本 / NULL
    """
    tags = _parse_tags(teacher)
    tags_text = " ｜ ".join(tags) if tags else "暂无标签"

    status_val = (daily_status_row or {}).get("status") if daily_status_row else None
    avt_val = (daily_status_row or {}).get("available_time") if daily_status_row else None
    note_val = (daily_status_row or {}).get("note") if daily_status_row else None

    # 今日状态
    if not is_signed_in_today and status_val != "unavailable":
        today_status_text = "今日暂未开课"
    elif status_val == "unavailable":
        today_status_text = "❌ 今日已取消"
    elif status_val == "full":
        today_status_text = "🈵 今日已满"
    elif status_val == "available":
        today_status_text = "✅ 今日可约"
    else:
        # 已签到但无 daily_status → spec：视为可约
        today_status_text = "✅ 今日可约"

    # 可约时间
    if not is_signed_in_today or status_val == "unavailable":
        available_time_text = "未设置"
    else:
        avt = (avt_val or "").strip()
        note_clean = (note_val or "").strip()
        if avt == "全天":
            available_time_text = "全天"
        elif avt == "下午":
            available_time_text = "下午"
        elif avt == "晚上":
            available_time_text = "晚上"
        elif avt == "自定义":
            available_time_text = note_clean if note_clean else "自定义"
        elif not avt:
            available_time_text = "未设置"
        else:
            available_time_text = avt

    hot_text = _derive_hot_text(teacher, fav_count, today_str)
    favorite_text = "已收藏" if is_fav else "未收藏"
    fit_text = _derive_fit_text(teacher, tags)

    lines = [
        f"👤 {teacher['display_name']}",
        "",
        f"📍 地区：{teacher.get('region') or '未设置'}",
        f"💰 价格：{teacher.get('price') or '未设置'}",
        f"📅 今日：{today_status_text}",
        f"⏰ 可约时间：{available_time_text}",
        f"🔥 热度：{hot_text}",
        f"⭐ 你的状态：{favorite_text}",
        "",
        "🏷 特点：",
        tags_text,
        "",
        "📌 适合：",
        fit_text,
    ]
    return "\n".join(lines)


async def _build_detail_payload(
    user_id: int,
    teacher: dict,
) -> tuple[str, types.InlineKeyboardMarkup]:
    """聚合详情页文本 + 键盘，供本文件和 user_search 共用"""
    today = _today_str()
    is_signed_in = await is_checked_in(teacher["user_id"], today)
    is_fav = await is_favorited(user_id, teacher["user_id"])
    # Phase 5：今日状态
    daily_row = await get_teacher_daily_status(teacher["user_id"], today)
    # Phase 7.1：热度展示需要收藏数（异常时降级为 0）
    try:
        fav_count = await count_teacher_favoriters(teacher["user_id"])
    except Exception as e:
        logger.debug("count_teacher_favoriters 失败: %s", e)
        fav_count = 0
    # Phase 7.3：根据用户 notify_enabled 决定提醒按钮文案
    notify_enabled = True
    try:
        user_row = await get_user(user_id)
        if user_row is not None:
            val = user_row.get("notify_enabled")
            notify_enabled = bool(val) if val is not None else True
    except Exception as e:
        logger.debug("get_user (notify_enabled) 失败: %s", e)

    text = format_teacher_detail_text(
        teacher,
        is_signed_in_today=is_signed_in,
        is_fav=is_fav,
        daily_status_row=daily_row,
        fav_count=fav_count,
        today_str=today,
    )
    kb = teacher_detail_kb(
        teacher,
        is_favorited=is_fav,
        notify_enabled=notify_enabled,
    )
    return text, kb


async def send_teacher_detail_message(
    message: types.Message,
    user_id: int,
    teacher: dict,
    *,
    record_view: bool = True,
) -> None:
    """以"新消息"的形式发送详情页（用于 message handler 场景，如搜索 FSM 收到文字）

    callback 场景请改用 _render_detail（edit_text）。
    """
    text, kb = await _build_detail_payload(user_id, teacher)
    await message.answer(text, reply_markup=kb)
    if record_view:
        await record_teacher_view(user_id, teacher["user_id"])
        # Phase 6.1：用户画像 view_teacher 动作
        await update_user_tags_from_teacher_action(
            user_id, teacher["user_id"], "view_teacher",
        )


async def _render_detail(
    callback: types.CallbackQuery,
    teacher_id: int,
    *,
    record_view: bool,
) -> None:
    """以"编辑当前消息"的形式渲染详情页（用于 callback 场景）"""
    teacher = await get_teacher(teacher_id)
    if not teacher or not teacher.get("is_active"):
        await callback.answer("该老师暂不可查看", show_alert=True)
        return

    user = callback.from_user
    # 用户首次点详情可能尚未在 users 表（如管理员 / 老师），保险刷新
    try:
        await upsert_user(user.id, user.username, user.first_name)
    except Exception as e:
        logger.debug("upsert_user 失败 (user=%s): %s", user.id, e)

    if record_view:
        await record_teacher_view(user.id, teacher_id)
        # Phase 6.1：用户画像 view_teacher 动作
        await update_user_tags_from_teacher_action(
            user.id, teacher_id, "view_teacher",
        )

    text, kb = await _build_detail_payload(user.id, teacher)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        # 上一条是图片消息 / 内容相同 / 已无法编辑 → 退化为新发一条
        await callback.message.answer(text, reply_markup=kb)


# ============ teacher:view —— 打开详情页 ============


@router.callback_query(F.data.startswith("teacher:view:"))
async def cb_teacher_view(callback: types.CallbackQuery):
    """打开老师详情页（仅私聊场景）"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("详情页仅在私聊中可用", show_alert=True)
        return

    try:
        teacher_id = int(callback.data[len("teacher:view:"):])
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return

    await _render_detail(callback, teacher_id, record_view=True)
    await callback.answer()


# ============ teacher:toggle_fav —— 详情页内切换收藏 ============


@router.callback_query(F.data.startswith("teacher:toggle_fav:"))
async def cb_teacher_toggle_fav(callback: types.CallbackQuery):
    """详情页内切换收藏，切换后刷新当前页（v2 §2.1 + 第二阶段要求 10）"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("收藏切换仅在私聊中可用", show_alert=True)
        return

    try:
        teacher_id = int(callback.data[len("teacher:toggle_fav:"):])
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return

    teacher = await get_teacher(teacher_id)
    if not teacher or not teacher.get("is_active"):
        await callback.answer("该老师暂不可查看", show_alert=True)
        return

    user = callback.from_user
    try:
        await upsert_user(user.id, user.username, user.first_name)
    except Exception as e:
        logger.debug("upsert_user 失败 (user=%s): %s", user.id, e)

    is_fav_now = await toggle_favorite(user.id, teacher_id)
    if is_fav_now:
        # Phase 6.1：仅收藏成功时累加画像分；取消不扣分
        await update_user_tags_from_teacher_action(
            user.id, teacher_id, "favorite_add",
        )
        await callback.answer(f"✅ 已收藏 {teacher['display_name']}")
    else:
        await callback.answer(f"已取消收藏 {teacher['display_name']}")

    # 切换后刷新当前详情页（不再 record_view 以免覆盖 viewed_at）
    await _render_detail(callback, teacher_id, record_view=False)


# ============ teacher:remind —— 开课提醒（Phase 7.1） ============


async def _safe_log_event(user_id: int, event_type: str, payload=None) -> None:
    """log_user_event 缺失 / 异常时静默跳过"""
    try:
        from bot.database import log_user_event  # type: ignore
    except ImportError:
        return
    try:
        await log_user_event(user_id, event_type, payload)
    except Exception as e:
        logger.debug("log_user_event(%s) 失败: %s", event_type, e)


@router.callback_query(F.data.startswith("teacher:remind:"))
async def cb_teacher_remind(callback: types.CallbackQuery):
    """开课提醒（Phase 7.1 第一版：复用收藏 + 开启 notify_enabled）

    流程：
        1. 若未收藏 → 添加收藏 + 累加用户画像分
        2. 调 set_user_notify_enabled(True) 开启用户级开关
        3. 弹 alert 反馈不同状态
        4. log_user_event teacher_remind_enable
        5. 收藏状态变化时刷新详情页（无变化保持原页）
    """
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    try:
        teacher_id = int(callback.data[len("teacher:remind:"):])
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return

    teacher = await get_teacher(teacher_id)
    if not teacher or not teacher.get("is_active"):
        await callback.answer("该老师暂不可查看", show_alert=True)
        return

    user = callback.from_user
    try:
        await upsert_user(user.id, user.username, user.first_name)
    except Exception as e:
        logger.debug("upsert_user 失败 (user=%s): %s", user.id, e)

    already_fav = await is_favorited(user.id, teacher_id)
    new_added = False
    if not already_fav:
        try:
            new_added = await add_favorite(user.id, teacher_id)
        except Exception as e:
            logger.warning("add_favorite 失败 (user=%s, teacher=%s): %s",
                           user.id, teacher_id, e)
        if new_added:
            try:
                await update_user_tags_from_teacher_action(
                    user.id, teacher_id, "favorite_add",
                )
            except Exception as e:
                logger.debug("用户画像写入失败: %s", e)

    # 尝试开启 notify_enabled；方法缺失 / 异常 → 静默降级
    notify_set = False
    try:
        notify_set = await set_user_notify_enabled(user.id, True)
    except Exception as e:
        logger.warning("set_user_notify_enabled 失败 (user=%s): %s", user.id, e)

    if new_added:
        if notify_set:
            alert = "已开启开课提醒。TA 今日开课时，你会收到提醒。"
        else:
            alert = f"已收藏 {teacher['display_name']}，后续可在通知设置中开启提醒"
    elif already_fav:
        if notify_set:
            alert = "你已收藏该老师，开课提醒已开启。"
        else:
            alert = "你已收藏该老师。"
    else:
        # 既没新加成功，又没已收藏 → 极端情况（add_favorite 异常）
        alert = "操作未完成，请稍后重试"

    await _safe_log_event(
        user.id,
        "teacher_remind_enable",
        {"teacher_id": teacher_id, "new_added": new_added, "notify_set": notify_set},
    )

    await callback.answer(alert, show_alert=True)

    # 仅当收藏状态发生变化时才刷新详情页（避免无意义重渲染）
    if new_added:
        await _render_detail(callback, teacher_id, record_view=False)


# ============ teacher:similar —— 相似推荐（Phase 7.3 §一） ============


def _short_status_label(t: dict) -> str:
    """从一行老师 dict 派生短状态文案（结果列表用）"""
    status = t.get("daily_status")
    if status == "unavailable":
        return "今日已取消"
    if status == "full":
        return "今日已满"
    if bool(t.get("signed_in_today")):
        return "今日可约"
    return "今日暂未开课"


def _similar_back_kb(teacher_id: int) -> types.InlineKeyboardMarkup:
    """相似推荐结果页底部按钮：返回详情页 / 返回主菜单"""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="🔙 返回老师详情",
            callback_data=f"teacher:view:{teacher_id}",
        )],
        [types.InlineKeyboardButton(
            text="🏠 返回主菜单",
            callback_data="user:main",
        )],
    ])


def _similar_empty_kb() -> types.InlineKeyboardMarkup:
    """相似推荐 0 结果时的兜底键盘"""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔥 热门推荐", callback_data="user:hot")],
        [types.InlineKeyboardButton(text="🏠 返回主菜单", callback_data="user:main")],
    ])


@router.callback_query(F.data.startswith("teacher:similar:"))
async def cb_teacher_similar(callback: types.CallbackQuery):
    """展示与目标老师相似的老师列表（Phase 7.3）"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    try:
        teacher_id = int(callback.data[len("teacher:similar:"):])
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return

    base = await get_teacher(teacher_id)
    if not base:
        await callback.answer("该老师暂不可查看", show_alert=True)
        return

    try:
        similars = await get_similar_teachers(teacher_id, limit=5)
    except Exception as e:
        logger.warning("get_similar_teachers(%s) 失败: %s", teacher_id, e)
        similars = []

    if not similars:
        text = f"✨ 和 {base['display_name']} 相似的老师\n\n暂时没有找到相似老师。"
        kb = _similar_empty_kb()
    else:
        lines = [
            f"✨ 和 {base['display_name']} 相似的老师",
            "",
            "你可能也喜欢：",
            "",
        ]
        for i, t in enumerate(similars, start=1):
            lines.append(
                f"{i}. {t.get('display_name') or '?'}"
                f"｜{(t.get('region') or '?').strip() or '?'}"
                f"｜{(t.get('price') or '?').strip() or '?'}"
                f"｜{_short_status_label(t)}"
            )
        text = "\n".join(lines)

        rows: list[list[types.InlineKeyboardButton]] = []
        for t in similars:
            label = (
                f"{t.get('display_name') or '?'} · "
                f"{(t.get('region') or '?').strip() or '?'} · "
                f"{(t.get('price') or '?').strip() or '?'}"
            )
            rows.append([types.InlineKeyboardButton(
                text=label,
                callback_data=f"teacher:view:{t['user_id']}",
            )])
        rows.append([
            types.InlineKeyboardButton(
                text="🔙 返回老师详情",
                callback_data=f"teacher:view:{teacher_id}",
            ),
            types.InlineKeyboardButton(
                text="🏠 返回主菜单",
                callback_data="user:main",
            ),
        ])
        kb = types.InlineKeyboardMarkup(inline_keyboard=rows)

    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()

    # 埋点
    await _safe_log_event(
        callback.from_user.id,
        "user_similar_view",
        {"teacher_id": teacher_id, "count": len(similars)},
    )


# ============ user:recent —— 最近浏览列表 ============


@router.callback_query(F.data == "user:recent")
async def cb_user_recent(callback: types.CallbackQuery):
    """最近浏览过的老师列表（Phase 2 新增主菜单入口）"""
    if callback.message and callback.message.chat.type != "private":
        await callback.answer("仅在私聊中可用", show_alert=True)
        return

    user_id = callback.from_user.id
    views = await list_recent_teacher_views(user_id, limit=10)
    if not views:
        await callback.message.edit_text(
            "🕘 最近看过\n\n你还没有浏览过老师。\n可以先去 🔍 搜索老师 看看。",
            reply_markup=back_to_user_main_kb(),
        )
        await callback.answer()
        return

    text = f"🕘 最近看过（{len(views)} 位）\n\n最近浏览的老师如下："
    await callback.message.edit_text(text, reply_markup=recent_views_kb(views))
    await callback.answer()
