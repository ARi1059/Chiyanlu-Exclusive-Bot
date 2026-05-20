"""普通用户私聊菜单的 callback handlers（v2 §2.5 C1 + Phase 2 详情页接入）

主菜单 5 个按钮:
    📚 user:today      → 今日所有开课老师（点击老师进入 teacher:view 详情页）
    ⭐ user:favorites  → 我的收藏（增强版：含今日可约/未签计数 + today/all 切换）
    💝 user:fav_today  → 收藏 ∩ 已签到（老师按钮 → 详情页）
    🕘 user:recent     → 最近看过（Phase 2 新增；handler 在 teacher_detail.py）
    🔍 user:search     → 进入搜索 FSM（user_search.py 接管）

user:main → 返回主菜单（通用按钮）
"""

from datetime import datetime

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from pytz import timezone

from bot.config import config
from bot.database import (
    add_user_tag,
    get_checked_in_teachers,
    get_sorted_teachers,
    list_user_favorites_signed_in,
    mark_user_onboarding_seen,
    remove_favorite,
)
from bot.keyboards.user_kb import (
    user_main_menu_kb,
    user_find_kb,
    user_my_records_kb,
    back_to_user_main_kb,
    search_cancel_kb,
    favorites_empty_kb,
    favorites_rich_kb,
    teacher_detail_list_kb,
)
from bot.states.user_states import SearchStates
from bot.utils.teacher_format import build_today_label

router = Router(name="user_panel")

tz = timezone(config.timezone)


def _today_str() -> str:
    return datetime.now(tz).strftime("%Y-%m-%d")


async def _safe_log_event(user_id: int, event_type: str, payload=None) -> None:
    """log_user_event 缺失或异常时静默跳过"""
    try:
        from bot.database import log_user_event  # type: ignore
    except ImportError:
        return
    try:
        await log_user_event(user_id, event_type, payload)
    except Exception:
        pass


# ============ 返回主菜单 ============

@router.callback_query(F.data == "user:main")
async def cb_user_main(callback: types.CallbackQuery, state: FSMContext):
    """返回用户主菜单（任何子菜单 / 搜索状态都可以走这里退出）"""
    await state.clear()
    try:
        await callback.message.edit_text(
            "👋 欢迎使用痴颜录 Bot\n\n你想怎么找？",
            reply_markup=user_main_menu_kb(),
        )
    except Exception:
        # 上一条是图片或不可编辑 → 退化为新发一条
        await callback.message.answer(
            "👋 欢迎使用痴颜录 Bot\n\n你想怎么找？",
            reply_markup=user_main_menu_kb(),
        )
    await callback.answer()


# ============ 🔎 找老师 二级页（UX-3 第一批） ============


@router.callback_query(F.data == "user:find")
async def cb_user_find(callback: types.CallbackQuery, state: FSMContext):
    """🔎 找老师 二级页：聚合 4 个找老师入口

    本 handler 仅渲染聚合页；4 个入口的 callback（user:hot / user:today /
    user:filter / user:search_history）含义未变，仍由各自原 handler 处理。
    """
    await state.clear()
    text = (
        "🔎 找老师\n\n"
        "请选择找老师方式：\n\n"
        "🔥 热门推荐：查看当前热门老师\n"
        "📚 今天能约谁：查看今日可约老师\n"
        "🔎 按条件找：按地区 / 价格 / 标签筛选\n"
        "📜 搜索历史:快速复用最近搜索"
    )
    try:
        await callback.message.edit_text(text, reply_markup=user_find_kb())
    except Exception:
        # 上一条若是图片或不可编辑 → 退化为新发一条
        await callback.message.answer(text, reply_markup=user_find_kb())
    await callback.answer()


# ============ 📝 我的记录 二级页（Sprint 5 §7.3.2） ============


@router.callback_query(F.data == "user:my_records")
async def cb_user_my_records(callback: types.CallbackQuery, state: FSMContext):
    """📝 我的记录 二级页：聚合 4 个个人记录入口

    本 handler 仅渲染聚合页；4 个子入口的 callback（user:write_review /
    user:reimburse / user:points / user:lottery:joined）含义未变，仍由各自
    原 handler 处理。Sprint 5 §7.3.2 + §7.4 实施纪律：旧主菜单一级入口
    保留双跑期，不删除。
    """
    await state.clear()
    text = (
        "📝 我的记录\n\n"
        "请选择查看类型：\n\n"
        "📝 我的评价：写过的评价 / 待审核 / 通过历史\n"
        "🧾 我的报销：报销申请与处理进度\n"
        "💰 积分流水：余额与最近积分变动明细\n"
        "🎁 抽奖记录：参与过的抽奖与中奖情况"
    )
    try:
        await callback.message.edit_text(text, reply_markup=user_my_records_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=user_my_records_kb())
    await callback.answer()


# ============ 🧭 新手引导 callbacks（Phase 7.1） ============


@router.callback_query(F.data == "user:onboarding:today")
async def cb_onboarding_today(callback: types.CallbackQuery):
    """新手引导 → 今日开课：复用 cb_today"""
    user_id = callback.from_user.id
    await mark_user_onboarding_seen(user_id)
    await _safe_log_event(user_id, "onboarding_done", {"path": "today"})
    await cb_today(callback)


@router.callback_query(F.data == "user:onboarding:hot")
async def cb_onboarding_hot(callback: types.CallbackQuery):
    """新手引导 → 热门推荐：复用 hot_teachers.cb_user_hot；不存在时降级到主菜单"""
    user_id = callback.from_user.id
    await mark_user_onboarding_seen(user_id)
    await _safe_log_event(user_id, "onboarding_done", {"path": "hot"})
    try:
        from bot.handlers.hot_teachers import cb_user_hot
    except ImportError:
        await callback.message.edit_text(
            "👋 欢迎使用痴颜录 Bot\n\n你想怎么找？",
            reply_markup=user_main_menu_kb(),
        )
        await callback.answer()
        return
    await cb_user_hot(callback)


@router.callback_query(F.data == "user:onboarding:search")
async def cb_onboarding_search(callback: types.CallbackQuery, state: FSMContext):
    """新手引导 → 直接搜索：复用 cb_search_entry"""
    user_id = callback.from_user.id
    await mark_user_onboarding_seen(user_id)
    await _safe_log_event(user_id, "onboarding_done", {"path": "search"})
    await cb_search_entry(callback, state)


@router.callback_query(F.data == "user:onboarding:main")
async def cb_onboarding_main(callback: types.CallbackQuery, state: FSMContext):
    """新手引导 → 进入主菜单：复用 cb_user_main"""
    user_id = callback.from_user.id
    await mark_user_onboarding_seen(user_id)
    await _safe_log_event(user_id, "onboarding_done", {"path": "main"})
    await cb_user_main(callback, state)


# ============ 📚 今日开课老师 ============


@router.callback_query(F.data == "user:today")
async def cb_today(callback: types.CallbackQuery):
    """展示当天所有已签到老师（扁平列表）

    范围：当天已签到 + 启用 + daily_status 不在 ('unavailable','full')
    按钮文案：'地区 艺名 价格'（价格除以 100 + P）
    按钮回调：teacher:view:<id>（私聊详情页）
    """
    today = _today_str()
    try:
        teachers = await get_sorted_teachers(
            active_only=True,
            signed_in_date=today,
            exclude_unavailable=True,
            exclude_full=True,
        )
    except Exception:
        # 老 schema 异常 fallback：不带 full 过滤
        teachers = await get_checked_in_teachers(today)

    if not teachers:
        await callback.message.edit_text(
            f"📚 {today}\n\n今日暂无老师开课。",
            reply_markup=back_to_user_main_kb(),
        )
        await callback.answer()
        return

    # UX-3 第二批：详情页"返回"指向 user:today
    from bot.keyboards.user_kb import format_teacher_view_callback
    rows: list[list[types.InlineKeyboardButton]] = []
    row: list[types.InlineKeyboardButton] = []
    for t in teachers:
        row.append(types.InlineKeyboardButton(
            text=build_today_label(t),
            callback_data=format_teacher_view_callback(t["user_id"], "today"),
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([types.InlineKeyboardButton(
        text="🔙 返回主菜单",
        callback_data="user:main",
    )])

    text = (
        f"📚 今日开课老师 · {today}（{len(teachers)} 位）\n\n"
        "点击老师查看详情。"
    )
    kb = types.InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

    # Phase 5 §九：记录用户查看今日事件（log_user_event 缺失时降级）
    try:
        from bot.database import log_user_event  # type: ignore
        await log_user_event(
            callback.from_user.id,
            "user_view_today",
            {"date": today, "count": len(teachers)},
        )
    except Exception:
        pass

    # Phase 6.1：今日开课关注者 + 活跃用户画像标签
    try:
        await add_user_tag(callback.from_user.id, "今日开课关注者", 1, "today")
        await add_user_tag(callback.from_user.id, "活跃用户", 1, "today")
    except Exception:
        pass


# ============ ⭐ 我的收藏（增强版） ============


async def _render_favorites(user_id: int, mode: str = "all"):
    """生成我的收藏的文本 + keyboard。

    抽出便于复用给 user:favorites / :today / :refresh / :rm:<id>。
    """
    from bot.services.user_favorites import (
        get_user_favorites,
        render_user_favorites,
    )
    stats = await get_user_favorites(user_id, mode=mode, limit=10)
    text = render_user_favorites(stats)
    # 空收藏：用引导 keyboard；有收藏（即使 today 模式 0 条）用 rich keyboard
    if (stats.total_count or 0) == 0:
        return text, favorites_empty_kb()
    return text, favorites_rich_kb(stats.items, mode=stats.mode)


@router.callback_query(F.data == "user:favorites")
async def cb_favorites(callback: types.CallbackQuery):
    """我的收藏主入口（mode=all，含今日可约/未签计数 + 切换按钮）。"""
    text, kb = await _render_favorites(callback.from_user.id, mode="all")
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "user:favorites:today")
async def cb_favorites_today(callback: types.CallbackQuery):
    """切换到「只看今日可约」视图。"""
    text, kb = await _render_favorites(callback.from_user.id, mode="today")
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "user:favorites:refresh")
async def cb_favorites_refresh(callback: types.CallbackQuery):
    """刷新当前收藏视图（保持当前 mode 不可知，复用 mode=all）。"""
    text, kb = await _render_favorites(callback.from_user.id, mode="all")
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer("已刷新")


@router.callback_query(F.data.startswith("user:favorites:rm:"))
async def cb_favorites_rm(callback: types.CallbackQuery):
    """从增强版列表中取消收藏单条；复用 remove_favorite，重绘当前视图。

    与既有 fav:rm_from_list:<id>（favorite.py）行为隔离：同一 DB 操作，
    不同重绘逻辑——避免老/新两个视图彼此覆盖。
    """
    try:
        teacher_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("⚠️ 无效操作", show_alert=True)
        return

    user_id = callback.from_user.id
    try:
        await remove_favorite(user_id, teacher_id)
    except Exception:
        # 取消收藏失败不阻塞 UI 重绘
        pass
    await callback.answer("已取消收藏")
    text, kb = await _render_favorites(user_id, mode="all")
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass


# ============ 💝 收藏开课（收藏 ∩ 今日签到） ============

@router.callback_query(F.data == "user:fav_today")
async def cb_fav_today(callback: types.CallbackQuery):
    """收藏老师中当天已签到的（扁平列表 + 隐藏 full 状态）"""
    today = _today_str()
    teachers = await list_user_favorites_signed_in(callback.from_user.id, today)
    teachers = [t for t in teachers if (t.get("daily_status") or "") != "full"]
    if not teachers:
        await callback.message.edit_text(
            f"💝 收藏开课 · {today}\n\n你的收藏老师今日均未开课。",
            reply_markup=back_to_user_main_kb(),
        )
        await callback.answer()
        return

    text = (
        f"💝 收藏开课 · {today}（{len(teachers)} 位）\n\n"
        "点击老师查看详情。"
    )
    kb = teacher_detail_list_kb(
        teachers,
        per_row=2,
        label_fn=build_today_label,
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# ============ 🔍 搜索老师 ============

@router.callback_query(F.data == "user:search")
async def cb_search_entry(callback: types.CallbackQuery, state: FSMContext):
    """进入搜索 FSM，等待用户输入关键词"""
    await state.set_state(SearchStates.waiting_query)
    await callback.message.edit_text(
        "🔍 搜索老师\n\n"
        "请输入关键词：\n"
        "・艺名（精确命中直接返回该老师）\n"
        "・标签 / 地区 / 价格 的组合（例：御姐 1000P 天府一街）\n\n"
        "支持空格、逗号分隔多个词；同类型 OR，跨类型 AND。\n"
        "随时点击下方按钮退出搜索。",
        reply_markup=search_cancel_kb(),
    )
    await callback.answer()
