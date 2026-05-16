"""/start 命令角色分流入口（v2 §2.5 C1 私聊冷启动 + Phase 4 来源追踪）

按角色分流到对应菜单:
    - 管理员（含超管） → 管理面板（v1 行为不变）
    - 老师（含停用 is_active=0） → 老师私聊菜单
    - 普通用户 → 用户主菜单

多角色重叠时优先匹配高权限（管理员 > 老师 > 普通用户）。

Deep Link 参数（Phase 4 扩展，向下兼容）:
    /start                                    → 角色分流主流程
    /start activate                           → 激活通知（v2 §2.1.4）
    /start fav_<teacher_id>                   → 自动收藏 + 激活（v2）
    /start fav_<id>_src_channel_<cid>         → Phase 4：收藏 + 频道来源
    /start fav_<id>_src_group_<gid>           → Phase 4：收藏 + 群组来源
    /start fav_<id>_src_teacher_<tid>         → Phase 4：收藏 + 老师来源
    /start fav_<id>_campaign_<code>           → Phase 4：收藏 + 活动来源
    /start fav_<id>_invite_<code>             → Phase 4：收藏 + 邀请来源
    /start src_channel_<id>                   → Phase 4：频道来源（id 可数字 / 别名）
    /start src_group_<id>                     → Phase 4：群组来源
    /start src_teacher_<id>                   → Phase 4：老师来源
    /start campaign_<code>                    → Phase 4：活动来源
    /start invite_<code>                      → Phase 4：邀请来源
    /start <其它>                              → Phase 4：source_type='unknown'

来源追踪所有失败都被吞掉，绝不阻断用户进入菜单。
"""

import logging
import re

from aiogram import Router, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext

from bot.config import config
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database import (
    add_favorite,
    add_user_tag,
    get_teacher,
    get_user_onboarding_seen,
    is_admin,
    list_recent_teacher_views,
    mark_user_started,
    record_user_source,
    update_user_tags_from_teacher_action,
    upsert_user,
)
from bot.keyboards.admin_kb import main_menu_kb
from bot.keyboards.teacher_self_kb import teacher_main_menu_kb
from bot.keyboards.user_kb import onboarding_kb, user_main_menu_kb


# Phase 7.3：群内快捷入口 deep link
_QUICK_ENTRY_VALUES = {"menu", "today", "hot", "filter", "recommend"}

# 群内快捷入口对应的私聊跳转目标 callback + 文案
_QUICK_ENTRY_PAGES: dict[str, tuple[str, str, str]] = {
    # value: (banner, button_text, target_callback)
    "today":     ("📚 今日开课", "📚 打开今日开课", "user:today"),
    "hot":       ("🔥 热门推荐", "🔥 打开热门推荐", "user:hot"),
    "filter":    ("🔎 条件筛选", "🔎 打开条件筛选", "user:filter"),
    "recommend": ("🎯 帮我推荐", "🎯 打开帮我推荐", "user:recommend"),
}

logger = logging.getLogger(__name__)

router = Router(name="start_router")


# ============ Deep Link 解析（Phase 4） ============


def parse_start_args(raw: str) -> dict:
    """解析 /start deep link 参数为结构化 dict

    Returns:
        {
            "activate": bool,                  # /start activate
            "fav_teacher_id": int | None,      # /start fav_<id>...
            "teacher_detail_id": int | None,   # Phase 8.1: /start teacher_<id>
            "search_query": str | None,        # Phase 8.2: /start q_<base64url> 解码后；"" 表示空查询
            "search_entry": bool,              # Phase 8.2: /start search
            "source_type": str | None,         # channel/group/teacher/campaign/invite/unknown
            "source_id": str | None,
            "quick_entry": str | None,         # Phase 7.3: menu/today/hot/filter/recommend
            "raw": str,                        # 原始 args
        }
    """
    result = {
        "activate": False,
        "fav_teacher_id": None,
        "teacher_detail_id": None,
        "review_target_id": None,
        "search_query": None,
        "search_entry": False,
        "source_type": None,
        "source_id": None,
        "quick_entry": None,
        "raw": raw or "",
    }
    if not raw:
        return result

    if raw == "activate":
        result["activate"] = True
        return result

    # Phase 7.3：群内快捷入口 deep link（menu / today / hot / filter / recommend）
    if raw in _QUICK_ENTRY_VALUES:
        result["quick_entry"] = raw
        return result

    # Phase 8.2：/start search 进入私聊搜索入口
    if raw == "search":
        result["search_entry"] = True
        return result

    # Phase 8.2：/start q_<base64url> 编码搜索词，解码后回放
    if raw.startswith("q_"):
        from bot.utils.group_search import decode_query_from_deep_link
        decoded = decode_query_from_deep_link(raw[2:])
        # 解码失败 / 解码后空串 → 退化为 search_entry（spec §八）
        if decoded:
            result["search_query"] = decoded
        else:
            result["search_entry"] = True
        return result

    # Phase 8.1：/start teacher_<digits> 私聊详情 deep link（群组卡片"私聊详情"按钮）
    # 必须放在 fav_ / 来源解析之前，且与 src_teacher_<id> 不冲突（后者以 src_ 开头）
    m_td = re.match(r"^teacher_(\d+)$", raw)
    if m_td:
        try:
            result["teacher_detail_id"] = int(m_td.group(1))
        except ValueError:
            pass
        return result

    # Phase 9.5.4：/start write_<digits> 直达评价 FSM（讨论群评论"🤖 给XXX写报告"按钮）
    m_wr = re.match(r"^write_(\d+)$", raw)
    if m_wr:
        try:
            result["review_target_id"] = int(m_wr.group(1))
        except ValueError:
            pass
        return result

    # fav 前缀：可能是 fav_<digits> 或 fav_<digits>_<source-suffix>
    if raw.startswith("fav_"):
        rest = raw[len("fav_"):]
        m = re.match(r"^(\d+)(?:_(.+))?$", rest)
        if m:
            try:
                result["fav_teacher_id"] = int(m.group(1))
            except ValueError:
                pass
            suffix = m.group(2)
            if suffix:
                _parse_source_into(result, suffix)
            return result
        # fav_<非数字> → 视为未知
        result["source_type"] = "unknown"
        result["source_id"] = raw[:64]
        return result

    # 无 fav 前缀，尝试纯来源
    if _parse_source_into(result, raw):
        return result

    # 完全无法识别 → unknown
    result["source_type"] = "unknown"
    result["source_id"] = raw[:64]
    return result


def _parse_source_into(result: dict, segment: str) -> bool:
    """从一段字符串尝试解析 source_type / source_id 并写入 result。
    匹配成功返回 True，否则 False。
    """
    mappings: list[tuple[str, str]] = [
        ("src_channel_", "channel"),
        ("src_group_", "group"),
        ("src_teacher_", "teacher"),
        ("campaign_", "campaign"),
        ("invite_", "invite"),
    ]
    for prefix, stype in mappings:
        if segment.startswith(prefix):
            sid = segment[len(prefix):]
            if not sid:
                return False
            result["source_type"] = stype
            result["source_id"] = sid
            return True
    return False


async def _resolve_source_name(source_type: str, source_id: str | None) -> str:
    """source_name 渲染规则（Phase 4 §三）"""
    if source_type == "channel":
        return "频道来源"
    if source_type == "group":
        return "群组来源"
    if source_type == "teacher":
        try:
            t = await get_teacher(int(source_id or ""))
            if t and t.get("display_name"):
                return t["display_name"]
        except (ValueError, TypeError):
            pass
        return "老师来源"
    if source_type == "campaign":
        return source_id or "campaign"
    if source_type == "invite":
        return source_id or "invite"
    return "unknown"


# ============ 兼容降级 helper ============


async def _safe_log_user_event(
    user_id: int,
    event_type: str,
    payload=None,
) -> None:
    """log_user_event 不存在或失败时静默跳过"""
    try:
        from bot.database import log_user_event  # type: ignore
    except ImportError:
        return
    try:
        await log_user_event(user_id, event_type, payload)
    except Exception as e:
        logger.debug("log_user_event 失败 (type=%s): %s", event_type, e)


# ============ 通用工具 ============


async def _is_admin_user(user_id: int) -> bool:
    """统一管理员判定：含超管"""
    return user_id == config.super_admin_id or await is_admin(user_id)


async def _track_source_if_any(user_id: int, parsed: dict) -> None:
    """如果 parsed 含来源信息，记录 user_sources + user_events + 用户画像标签。
    全程吞异常，绝不上抛。
    """
    stype = parsed.get("source_type")
    if not stype:
        return
    sid = parsed.get("source_id")
    raw = parsed.get("raw")
    try:
        source_name = await _resolve_source_name(stype, sid)
    except Exception as e:
        logger.debug("_resolve_source_name 失败: %s", e)
        source_name = stype
    try:
        await record_user_source(
            user_id=user_id,
            source_type=stype,
            source_id=sid,
            source_name=source_name,
            raw_payload=raw,
        )
    except Exception as e:
        logger.warning("record_user_source 失败 (user=%s): %s", user_id, e)
    await _safe_log_user_event(
        user_id=user_id,
        event_type="source_enter",
        payload={"type": stype, "id": sid, "raw": raw},
    )

    # Phase 6.1：根据来源类型沉淀用户画像标签
    try:
        if stype == "teacher":
            # teacher 来源：复用 view_teacher 权重（老师标签/地区/价格 +1 + 浏览型用户 +1）
            try:
                tid_int = int(sid) if sid is not None else None
            except (ValueError, TypeError):
                tid_int = None
            if tid_int is not None:
                await update_user_tags_from_teacher_action(
                    user_id, tid_int, "view_teacher",
                )
        elif stype in ("group", "channel", "campaign", "invite"):
            await add_user_tag(user_id, f"来源:{stype}", 1, "source")
            await add_user_tag(user_id, "新用户来源触达", 1, "source")
        # unknown 来源不写画像（噪音太大）
    except Exception as e:
        logger.debug("用户画像写入失败 (source=%s): %s", stype, e)


# ============ /start handlers ============


@router.message(CommandStart(deep_link=True))
async def cmd_start_with_arg(
    message: types.Message,
    command: CommandObject,
    state: FSMContext,
):
    """/start 带参数（deep link）入口

    解析 command.args 后做相应动作，最后仍走主流程展示对应菜单。
    """
    await state.clear()
    user = message.from_user
    user_id = user.id
    raw_args = (command.args or "").strip()

    # 普通用户身份层维护
    await upsert_user(user_id, user.username, user.first_name)
    await mark_user_started(user_id)

    parsed = parse_start_args(raw_args)
    extras: list[str] = []

    # activate（v2 §2.1.4 兼容保留）
    if parsed["activate"]:
        extras.append("✅ 已激活开课通知，14:00 会收到收藏老师的开课提醒")

    # fav_<teacher_id>（v2 兼容保留）
    if parsed["fav_teacher_id"] is not None:
        msg = await _handle_fav_deep_link(user_id, str(parsed["fav_teacher_id"]))
        if msg:
            extras.append(msg)

    # Phase 4：来源追踪（任何异常都不阻断后续菜单展示）
    try:
        await _track_source_if_any(user_id, parsed)
    except Exception as e:
        logger.warning("来源追踪整体失败 (user=%s, raw=%s): %s", user_id, raw_args, e)

    extra_text = "\n\n".join(extras) if extras else None
    await _route_by_role(
        message,
        user_id,
        extra_text=extra_text,
        quick_entry=parsed.get("quick_entry"),
        teacher_detail_id=parsed.get("teacher_detail_id"),
        review_target_id=parsed.get("review_target_id"),
        search_entry=parsed.get("search_entry", False),
        search_query=parsed.get("search_query"),
        state=state,
    )


async def _handle_fav_deep_link(user_id: int, raw_teacher_id: str) -> str:
    """处理 ?start=fav_<teacher_id> deep link 自动收藏

    校验老师存在且启用后写入 favorites（幂等）。无论是否新增收藏，
    都返回给用户一条提示（避免静默）。
    """
    try:
        teacher_id = int(raw_teacher_id)
    except ValueError:
        return "⚠️ 收藏链接无效"

    teacher = await get_teacher(teacher_id)
    if not teacher or not teacher["is_active"]:
        return "⚠️ 该老师暂不可收藏"

    inserted = await add_favorite(user_id, teacher_id)
    if inserted:
        return f"✅ 已收藏 {teacher['display_name']}，14:00 会收到 TA 的开课提醒"
    return f"💡 你已经收藏过 {teacher['display_name']}"


@router.message(CommandStart())
async def cmd_start_plain(message: types.Message, state: FSMContext):
    """/start 无参数入口：角色分流"""
    await state.clear()
    user = message.from_user
    user_id = user.id

    # 普通用户身份层维护
    await upsert_user(user_id, user.username, user.first_name)
    await mark_user_started(user_id)

    await _route_by_role(message, user_id)


def _quick_entry_kb(target_callback: str, button_label: str) -> InlineKeyboardMarkup:
    """Phase 7.3：群内 deep link 落地页的 CTA 键盘"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=button_label, callback_data=target_callback)],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


def _continue_last_kb() -> InlineKeyboardMarkup:
    """Phase 7.3：欢迎回来 + 继续看上次老师 / 进主菜单"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="继续查看", callback_data="user:continue_last")],
        [InlineKeyboardButton(text="进入主菜单", callback_data="user:onboarding:main")],
    ])


def _teacher_detail_landing_kb(teacher_id: int) -> InlineKeyboardMarkup:
    """Phase 8.1：/start teacher_<id> 落地页 CTA 键盘"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔍 查看老师详情",
            callback_data=f"teacher:view:{teacher_id}",
        )],
        [InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")],
    ])


async def _route_by_role(
    message: types.Message,
    user_id: int,
    extra_text: str | None = None,
    quick_entry: str | None = None,
    teacher_detail_id: int | None = None,
    review_target_id: int | None = None,
    search_entry: bool = False,
    search_query: str | None = None,
    state: FSMContext | None = None,
):
    """根据角色展示对应菜单。

    优先级：管理员 > 老师 > 普通用户。
    extra_text 用于在菜单前展示一行额外提示（deep link 场景）。
    quick_entry (Phase 7.3): 普通用户从群组 deep link 进入时的目标快捷页。
    """
    # 1. 管理员
    if await _is_admin_user(user_id):
        text = "🔧 痴颜录管理面板"
        if extra_text:
            text = f"{extra_text}\n\n{text}"
        # Phase 9.4：超管用户能看到 [📝 报告审核] 入口
        from bot.database import is_super_admin, count_pending_reviews, count_pending_edits
        n_edits = await count_pending_edits()
        rcount = 0
        is_super = False
        if user_id == config.super_admin_id or await is_super_admin(user_id):
            is_super = True
            rcount = await count_pending_reviews()
        await message.answer(
            text,
            reply_markup=main_menu_kb(
                pending_count=n_edits,
                pending_review_count=rcount,
                is_super=is_super,
            ),
        )
        return

    # 2. 老师（含停用，v2 §2.5.5 决策 15）
    teacher = await get_teacher(user_id)
    if teacher:
        # Step 5：完整老师菜单（"我的资料" + "今日签到"按钮）
        # v1 文字"签到"行为仍保留（teacher_checkin.py），两种触发方式并存
        status = "" if teacher["is_active"] else "（账号已停用）"
        text = (
            f"👤 你好，{teacher['display_name']}{status}\n\n"
            "你的私聊功能："
        )
        if extra_text:
            text = f"{extra_text}\n\n{text}"
        await message.answer(text, reply_markup=teacher_main_menu_kb())
        return

    # 3. 普通用户（Phase 7.1：首次进入展示新手引导，已看过则进主菜单）
    try:
        seen = await get_user_onboarding_seen(user_id)
    except Exception as e:
        logger.warning("get_user_onboarding_seen 异常（默认已看过）: %s", e)
        seen = True

    if not seen:
        onboarding_text = (
            "👋 欢迎使用痴颜录 Bot\n\n"
            "你可以这样使用：\n\n"
            "1. 看今天有哪些老师开课\n"
            "2. 收藏喜欢的老师\n"
            "3. 开课时收到提醒\n"
            "4. 也可以通过搜索快速找到老师\n\n"
            "请选择你的第一步："
        )
        if extra_text:
            onboarding_text = f"{extra_text}\n\n{onboarding_text}"
        await message.answer(onboarding_text, reply_markup=onboarding_kb())
        await _safe_log_user_event(user_id, "onboarding_view", None)
        return

    # Phase 9.5.4：/start write_<id> 直达评价 FSM（讨论群评论"🤖 给XXX写报告"按钮）
    # 仅普通用户分支处理；管理员 / 老师角色已在前面 return
    if review_target_id is not None and state is not None:
        from bot.handlers.review_submit import start_review_flow
        from bot.keyboards.user_kb import review_cancel_kb, review_subscribe_links_kb

        await _safe_log_user_event(
            user_id,
            "deep_link_write_review",
            {"teacher_id": review_target_id},
        )

        status, extra = await start_review_flow(
            message.bot, message.chat.id, user_id, review_target_id, state,
        )
        if status == "not_found":
            body = "⚠️ 该老师不存在或已被删除。"
            if extra_text:
                body = f"{extra_text}\n\n{body}"
            await message.answer(body, reply_markup=user_main_menu_kb())
            return
        if status == "inactive":
            body = "⚠️ 该老师已停用，无法提交评价。"
            if extra_text:
                body = f"{extra_text}\n\n{body}"
            await message.answer(body, reply_markup=user_main_menu_kb())
            return
        if status == "rate_limited":
            body = f"⚠️ {extra['reason']}"
            if extra_text:
                body = f"{extra_text}\n\n{body}"
            await message.answer(body, reply_markup=user_main_menu_kb())
            return
        if status == "need_subscribe":
            lines = ["⚠️ 提交评价前请先加入：\n"]
            for it in extra["missing"]:
                lines.append(f"📺 {it['display_name']}")
            lines.append('\n加入后再次点击讨论群里的 "🤖 给XXX写报告" 按钮。')
            body = "\n".join(lines)
            if extra_text:
                body = f"{extra_text}\n\n{body}"
            await message.answer(
                body,
                reply_markup=review_subscribe_links_kb(extra["missing"]),
                disable_web_page_preview=True,
            )
            return

        # status == "ok"
        teacher = extra["teacher"]
        body = (
            f"📝 为「{teacher['display_name']}」写评价\n\n"
            "[Step B/12] 上传约课记录截图（必填）\n\n"
            "请发送你和该老师的约课记录截图（一张图片）。\n"
            "仅作为审核证据，不会公开展示。\n\n"
            "任意时刻发 /cancel 中止。"
        )
        if extra_text:
            body = f"{extra_text}\n\n{body}"
        await message.answer(body, reply_markup=review_cancel_kb())
        return

    # Phase 8.1：/start teacher_<id> 落地页（仅普通用户分支处理；不破坏现有 deep link）
    if teacher_detail_id is not None:
        try:
            target_teacher = await get_teacher(teacher_detail_id)
        except Exception as e:
            logger.warning("get_teacher(deep link) 失败 id=%s: %s", teacher_detail_id, e)
            target_teacher = None

        await _safe_log_user_event(
            user_id,
            "deep_link_teacher_detail",
            {"teacher_id": teacher_detail_id},
        )

        if target_teacher and target_teacher.get("is_active"):
            body = (
                f"已为你打开老师详情：{target_teacher['display_name']}\n\n"
                "点击下方按钮查看完整信息。"
            )
            if extra_text:
                body = f"{extra_text}\n\n{body}"
            await message.answer(
                body,
                reply_markup=_teacher_detail_landing_kb(teacher_detail_id),
            )
            return

        # 无效 teacher_id → 直接进主菜单 + 提示（spec §四 3 末尾）
        menu_text = (
            "⚠️ 该老师暂不可查看\n\n"
            "👋 欢迎使用痴颜录 Bot\n\n你想怎么找？"
        )
        if extra_text:
            menu_text = f"{extra_text}\n\n{menu_text}"
        await message.answer(menu_text, reply_markup=user_main_menu_kb())
        return

    # Phase 8.2：/start q_<base64url> 解码搜索词 → 直接在私聊回放搜索
    if search_query:
        await _safe_log_user_event(
            user_id,
            "deep_link_group_search_entry",
            {"kind": "q", "query": search_query},
        )
        # 把成功提示放第一行，再调用 user_search._execute_search 回放
        hint = f"🔍 搜索：{search_query}"
        if extra_text:
            hint = f"{extra_text}\n\n{hint}"
        await message.answer(hint, reply_markup=user_main_menu_kb())
        try:
            from bot.handlers.user_search import _execute_search
            await _execute_search(user_id, search_query, message)
        except Exception as e:
            logger.warning("回放搜索失败 q=%r: %s", search_query, e)
        return

    # Phase 8.2：/start search 进入私聊搜索 FSM（与点击 user:search 等价）
    if search_entry:
        await _safe_log_user_event(
            user_id,
            "deep_link_group_search_entry",
            {"kind": "search"},
        )
        body = (
            "🔍 搜索老师\n\n"
            "请输入关键词：\n"
            "・艺名（精确命中直接返回该老师）\n"
            "・标签 / 地区 / 价格 的组合（例：御姐 1000P 天府一街）\n\n"
            "随时点击下方按钮退出搜索。"
        )
        if extra_text:
            body = f"{extra_text}\n\n{body}"
        # 把用户置入搜索 FSM，下条文字消息会被 user_search 接住
        try:
            from bot.keyboards.user_kb import search_cancel_kb
            from bot.states.user_states import SearchStates
            if state is not None:
                await state.set_state(SearchStates.waiting_query)
            await message.answer(body, reply_markup=search_cancel_kb())
        except Exception as e:
            logger.debug("进入 search_entry FSM 失败，回退到主菜单: %s", e)
            await message.answer(body, reply_markup=user_main_menu_kb())
        return

    # Phase 7.3：群内快捷入口 deep link → 落地为带 CTA 按钮的页面
    if quick_entry and quick_entry != "menu" and quick_entry in _QUICK_ENTRY_PAGES:
        banner, btn_label, target_cb = _QUICK_ENTRY_PAGES[quick_entry]
        body = (
            f"{banner}\n\n"
            "点击下方按钮进入对应页面："
        )
        if extra_text:
            body = f"{extra_text}\n\n{body}"
        await message.answer(body, reply_markup=_quick_entry_kb(target_cb, btn_label))
        return

    # Phase 7.3：欢迎回来 + 继续看上次（仅 plain /start 或 quick_entry=menu）
    if not quick_entry or quick_entry == "menu":
        try:
            views = await list_recent_teacher_views(user_id, limit=1)
        except Exception as e:
            logger.debug("list_recent_teacher_views 失败 user=%s: %s", user_id, e)
            views = []
        if views:
            last = views[0]
            name = last.get("display_name") or "?"
            region = (last.get("region") or "").strip() or "?"
            price = (last.get("price") or "").strip() or "?"
            body = (
                "👋 欢迎回来\n\n"
                "你上次看过：\n"
                f"{name}｜{region}｜{price}\n\n"
                "你想继续看看吗？"
            )
            if extra_text:
                body = f"{extra_text}\n\n{body}"
            await message.answer(body, reply_markup=_continue_last_kb())
            return

    text = "👋 欢迎使用痴颜录 Bot\n\n你想怎么找？"
    if extra_text:
        text = f"{extra_text}\n\n{text}"
    await message.answer(text, reply_markup=user_main_menu_kb())
