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


def _extract_price_tag(price: Optional[str]) -> str:
    """从老师 price 字段（如 '800P'）抽出展示价位 tag：'#8P'

    规则：抽数字 // 100 + 'P'。无数字 → 空串。
    """
    if not price:
        return ""
    digits = "".join(ch for ch in str(price) if ch.isdigit())
    if not digits:
        return ""
    return f"#{int(digits) // 100}P"


def render_teacher_channel_caption(
    teacher: dict,
    stats: Optional[dict] = None,
    bot_username: str = "ChiYanBookBot",
    brand_name: str = "《痴颜录》",
    brand_channels: str = "",
) -> str:
    """生成老师档案帖 caption（2026-05-17 模板）

    格式示例：
        👤 乔儿

        22 岁 · 163cm · 90kg · 胸 C

        课费：800P

        📊 0 条车评，综合评分 0.00
        好评 ---- | 人照 ---- | 服务 ----
        中评 ---- | 颜值 ---- | 态度 ----
        差评 ---- | 身材 ---- | 环境 ----

        ☎ 联系方式： @qiaoer

        🏷 #甜妹 #巨乳 #情绪价值 #8P

        ✳ 报告提交： @ChiYanBookBot

        成都 · 《痴颜录》： @CDCChiYanLog @ChiYanLog

    Args:
        teacher: get_teacher_full_profile 字典；必填 display_name / age /
                 height_cm / weight_kg / bra_size / price / contact_telegram。
        stats: teacher_channel_posts 行；None / review_count=0 → 占位符。
        bot_username: footer 「报告提交」展示用。
        brand_name: 末行品牌名（默认 '《痴颜录》'，可由 config 覆盖）。
        brand_channels: 末行品牌频道列表（空字符串则不显示该后缀；如
                        '@CDCChiYanLog @ChiYanLog'）。

    Returns:
        caption 字符串。超过 1024 字符时仅 tags 个数限制 + 末尾兜底硬截断。
        （新模板已不含可截断的长文本字段如 description/service_content/
        taboos/price_detail，超长极少出现。）

    Raises:
        ValueError: 必填字段缺失。
    """
    required = ["display_name", "age", "height_cm", "weight_kg", "bra_size",
                "price", "contact_telegram"]
    for f in required:
        v = teacher.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError(f"必填字段缺失: {f}")

    tags = teacher.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    price_raw = str(teacher.get("price", "")).strip()
    price_tag = _extract_price_tag(price_raw)
    region = (teacher.get("region") or "").strip()
    contact = str(teacher.get("contact_telegram", "")).strip()

    def _build(tags_count: int = 20) -> str:
        # 标签 + 价位 tag（价位 tag 排末尾）
        tag_items = []
        for t in tags[:tags_count]:
            s = str(t).strip().lstrip("#")
            if s:
                tag_items.append(f"#{s}")
        if price_tag:
            tag_items.append(price_tag)
        tag_line = " ".join(tag_items)

        lines: list[str] = []
        lines.append(f"👤 {teacher['display_name']}")
        lines.append("")
        lines.append(
            f"{teacher['age']} 岁 · {teacher['height_cm']}cm · "
            f"{teacher['weight_kg']}kg · 胸 {teacher['bra_size']}"
        )
        lines.append("")
        lines.append(f"课费：{price_raw}")
        lines.append("")
        lines.append(_format_stats_block(stats))
        lines.append("")
        lines.append(f"☎ 联系方式： {contact}")
        if tag_line:
            lines.append("")
            lines.append(f"🏷 {tag_line}")
        lines.append("")
        lines.append(f"✳ 报告提交： @{bot_username}")

        # 末行品牌
        brand_line_parts: list[str] = []
        if region:
            brand_line_parts.append(region)
        if brand_name:
            brand_suffix = brand_name
            if brand_channels:
                brand_suffix = f"{brand_name}： {brand_channels}"
            brand_line_parts.append(brand_suffix)
        if brand_line_parts:
            lines.append("")
            lines.append(" · ".join(brand_line_parts))

        return "\n".join(lines)

    cap = _build()
    if len(cap) <= CAPTION_MAX_LEN:
        return cap
    # 标签缩减
    cap = _build(tags_count=10)
    if len(cap) <= CAPTION_MAX_LEN:
        return cap
    cap = _build(tags_count=5)
    if len(cap) > CAPTION_MAX_LEN:
        cap = cap[: CAPTION_MAX_LEN - 1].rstrip() + "…"
    return cap
