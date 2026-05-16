"""老师档案 caption 渲染（Phase 9.1）

根据 spec §6.1 + 附录 D 生成"老师档案帖"的 caption。
本 phase 仅用于 [👁 预览档案 caption] 入口；Phase 9.2 会被频道发布逻辑复用。

纯函数，不访问 DB，不调用 Telegram API。
"""
from __future__ import annotations

from typing import Optional

# Telegram 媒体组 caption 上限 1024 字符
CAPTION_MAX_LEN: int = 1024


def _format_stats_block(stats: Optional[dict]) -> str:
    """格式化统计块（6 行）

    stats 为 None 或 review_count == 0 时用占位符 ----；
    否则按 spec §6.1 输出百分比 + 六维均分。
    """
    if not stats or stats.get("review_count", 0) == 0:
        return (
            "📊 0 条车评，综合评分 0.00\n"
            "好评 ----  | 人照 ----  | 服务 ----\n"
            "中评 ----  | 颜值 ----  | 态度 ----\n"
            "差评 ----  | 身材 ----  | 环境 ----"
        )
    rc = stats["review_count"]
    pos_pct = (stats.get("positive_count", 0) or 0) / rc * 100
    neu_pct = (stats.get("neutral_count", 0) or 0) / rc * 100
    neg_pct = (stats.get("negative_count", 0) or 0) / rc * 100
    return (
        f"📊 {rc} 条车评，综合评分 {stats.get('avg_overall', 0):.2f}\n"
        f"好评 {pos_pct:>5.1f}% | 人照 {stats.get('avg_humanphoto', 0):>5.2f} | "
        f"服务 {stats.get('avg_service', 0):>5.2f}\n"
        f"中评 {neu_pct:>5.1f}% | 颜值 {stats.get('avg_appearance', 0):>5.2f} | "
        f"态度 {stats.get('avg_attitude', 0):>5.2f}\n"
        f"差评 {neg_pct:>5.1f}% | 身材 {stats.get('avg_body', 0):>5.2f} | "
        f"环境 {stats.get('avg_environment', 0):>5.2f}"
    )


def _truncate(text: str, limit: int) -> str:
    """超过 limit 时尾部加省略号"""
    if not text or len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _format_tags(tags: list, max_count: int = 20) -> str:
    """tags → '#御姐 #高颜值 …' 字符串；空 list 返回 ''"""
    if not tags:
        return ""
    items = [str(t).strip().lstrip("#") for t in tags[:max_count] if str(t).strip()]
    return " ".join(f"#{t}" for t in items)


def render_teacher_channel_caption(
    teacher: dict,
    stats: Optional[dict] = None,
    bot_username: str = "ChiYanBookBot",
) -> str:
    """生成老师档案帖 caption（spec §6.1 + 附录 D）

    Args:
        teacher: get_teacher_full_profile 返回的字典；tags 应为 list；
                 必填：display_name/age/height_cm/weight_kg/bra_size/
                       price_detail/contact_telegram。缺必填时抛 ValueError。
        stats:   teacher_channel_posts 行；None 或 review_count=0 时
                 统计块用 ---- 占位符。
        bot_username: footer 显示用。

    Returns:
        caption 字符串。若超过 1024 字符，按以下优先级依次截断：
        taboos → service_content → price_detail → description → tags 个数限制。

    Raises:
        ValueError: 必填字段缺失，附带缺哪一项。
    """
    required = ["display_name", "age", "height_cm", "weight_kg", "bra_size",
                "price_detail", "contact_telegram"]
    for f in required:
        v = teacher.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError(f"必填字段缺失: {f}")

    # 可选字段，可能 None
    description     = (teacher.get("description") or "").strip()
    service_content = (teacher.get("service_content") or "").strip()
    taboos          = (teacher.get("taboos") or "").strip()
    tags = teacher.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    def _build(
        desc_limit: Optional[int] = None,
        svc_limit: Optional[int] = None,
        price_limit: Optional[int] = None,
        taboos_limit: Optional[int] = None,
        tags_count: int = 20,
    ) -> str:
        d  = _truncate(description, desc_limit) if desc_limit else description
        sv = _truncate(service_content, svc_limit) if svc_limit else service_content
        pd = _truncate(teacher["price_detail"].strip(), price_limit) if price_limit else teacher["price_detail"].strip()
        tb = _truncate(taboos, taboos_limit) if taboos_limit else taboos
        tag_line = _format_tags(tags, max_count=tags_count)

        lines: list[str] = []
        lines.append(f"👤 {teacher['display_name']}")
        lines.append("")
        lines.append(
            f"{teacher['age']} 岁 · {teacher['height_cm']}cm · "
            f"{teacher['weight_kg']}kg · 胸 {teacher['bra_size']}"
        )
        if d:
            lines.append(f"📋 描述：{d}")
        if sv:
            lines.append(f"📋 服务：{sv}")
        lines.append(f"💰 价格详述：{pd}")
        if tb:
            lines.append(f"🚫 禁忌：{tb}")
        lines.append("")
        lines.append(_format_stats_block(stats))
        lines.append("")
        lines.append("☎ 联系方式")
        lines.append(f"电报：{teacher['contact_telegram']}")
        if tag_line:
            lines.append("")
            lines.append(f"🏷 {tag_line}")
        lines.append("")
        lines.append(f"✳ Powered by @{bot_username}")
        return "\n".join(lines)

    # 截断顺序（spec §3.1 缓解）
    cap = _build()
    if len(cap) <= CAPTION_MAX_LEN:
        return cap
    cap = _build(taboos_limit=100)
    if len(cap) <= CAPTION_MAX_LEN:
        return cap
    cap = _build(taboos_limit=100, svc_limit=200)
    if len(cap) <= CAPTION_MAX_LEN:
        return cap
    cap = _build(taboos_limit=100, svc_limit=200, price_limit=100)
    if len(cap) <= CAPTION_MAX_LEN:
        return cap
    cap = _build(taboos_limit=100, svc_limit=200, price_limit=100, desc_limit=80)
    if len(cap) <= CAPTION_MAX_LEN:
        return cap
    cap = _build(taboos_limit=100, svc_limit=200, price_limit=100,
                 desc_limit=80, tags_count=10)
    # 最后兜底硬截断
    if len(cap) > CAPTION_MAX_LEN:
        cap = cap[: CAPTION_MAX_LEN - 1].rstrip() + "…"
    return cap
