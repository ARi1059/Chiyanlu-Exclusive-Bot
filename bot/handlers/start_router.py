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
from bot.database import (
    add_favorite,
    get_teacher,
    is_admin,
    mark_user_started,
    record_user_source,
    upsert_user,
)
from bot.keyboards.admin_kb import main_menu_kb
from bot.keyboards.teacher_self_kb import teacher_main_menu_kb
from bot.keyboards.user_kb import user_main_menu_kb

logger = logging.getLogger(__name__)

router = Router(name="start_router")


# ============ Deep Link 解析（Phase 4） ============


def parse_start_args(raw: str) -> dict:
    """解析 /start deep link 参数为结构化 dict

    Returns:
        {
            "activate": bool,                  # /start activate
            "fav_teacher_id": int | None,      # /start fav_<id>...
            "source_type": str | None,         # channel/group/teacher/campaign/invite/unknown
            "source_id": str | None,
            "raw": str,                        # 原始 args
        }
    """
    result = {
        "activate": False,
        "fav_teacher_id": None,
        "source_type": None,
        "source_id": None,
        "raw": raw or "",
    }
    if not raw:
        return result

    if raw == "activate":
        result["activate"] = True
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
    """如果 parsed 含来源信息，记录 user_sources + user_events。
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
    await _route_by_role(message, user_id, extra_text=extra_text)


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


async def _route_by_role(
    message: types.Message,
    user_id: int,
    extra_text: str | None = None,
):
    """根据角色展示对应菜单。

    优先级：管理员 > 老师 > 普通用户。
    extra_text 用于在菜单前展示一行额外提示（deep link 场景）。
    """
    # 1. 管理员
    if await _is_admin_user(user_id):
        text = "🔧 痴颜录管理面板"
        if extra_text:
            text = f"{extra_text}\n\n{text}"
        await message.answer(text, reply_markup=main_menu_kb())
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

    # 3. 普通用户
    text = "👋 欢迎使用痴颜录 Bot\n\n请选择下方功能："
    if extra_text:
        text = f"{extra_text}\n\n{text}"
    await message.answer(text, reply_markup=user_main_menu_kb())
