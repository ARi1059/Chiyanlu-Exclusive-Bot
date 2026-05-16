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
    """生成老师档案帖 caption（2026-05-17 模板 v2）

    格式示例：
        👤 乔儿

        22 岁 · 163cm · 90kg · 胸 C

        📍 地区：金融城 · 成都
        💰 价格：800P
        📋 服务：正规推油 / 60 分钟正点
        🚫 禁忌：不接老外 / 不戴套

        📊 0 条车评，综合评分 0.00
        好评 ---- | 人照 ---- | 服务 ----
        中评 ---- | 颜值 ---- | 态度 ----
        差评 ---- | 身材 ---- | 环境 ----

        ☎ 联系方式： @qiaoer

        🏷 #甜妹 #巨乳 #情绪价值 #8P

        ✳ 报告提交： @ChiYanBookBot

        《痴颜录》： @CDCChiYanLog @ChiYanLog

    Args:
        teacher: get_teacher_full_profile 字典；必填 display_name / age /
                 height_cm / weight_kg / bra_size / price / contact_telegram。
                 region / service_content / taboos 为空时跳过对应行。
        stats: teacher_channel_posts 行；None / review_count=0 → 占位符。
        bot_username: footer 「报告提交」展示用。
        brand_name: 末行品牌名（默认 '《痴颜录》'）。**不再自动前缀 region**；
                    如要在 footer 显示城市，admin 把 brand_name 配置成
                    '成都 · 《痴颜录》' 即可。
        brand_channels: 末行品牌频道列表（空字符串则不显示该后缀；如
                        '@CDCChiYanLog @ChiYanLog'）。

    Returns:
        caption 字符串。超过 1024 字符时按 服务/禁忌 截断 → 标签缩减 → 兜底硬截断。

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
    service = (teacher.get("service_content") or "").strip()
    taboos = (teacher.get("taboos") or "").strip()

    def _build(
        tags_count: int = 20,
        svc_limit: Optional[int] = None,
        taboos_limit: Optional[int] = None,
    ) -> str:
        # 标签 + 价位 tag（去重：若 tags 已含 #8P 等同款，不重复追加）
        existing_norm = {
            str(t).strip().lstrip("#").upper() for t in tags if str(t).strip()
        }
        tag_items: list[str] = []
        for t in tags[:tags_count]:
            s = str(t).strip().lstrip("#")
            if s:
                tag_items.append(f"#{s}")
        if price_tag:
            price_norm = price_tag.lstrip("#").upper()
            if price_norm not in existing_norm:
                tag_items.append(price_tag)
        tag_line = " ".join(tag_items)

        svc = _truncate(service, svc_limit) if svc_limit else service
        tb  = _truncate(taboos, taboos_limit) if taboos_limit else taboos

        lines: list[str] = []
        lines.append(f"👤 {teacher['display_name']}")
        lines.append("")
        lines.append(
            f"{teacher['age']} 岁 · {teacher['height_cm']}cm · "
            f"{teacher['weight_kg']}kg · 胸 {teacher['bra_size']}"
        )

        # 「评价统计前」字段块：地区 / 价格 / 服务 / 禁忌
        detail_lines: list[str] = []
        if region:
            detail_lines.append(f"📍 地区：{region}")
        detail_lines.append(f"💰 价格：{price_raw}")
        if svc:
            detail_lines.append(f"📋 服务：{svc}")
        if tb:
            detail_lines.append(f"🚫 禁忌：{tb}")
        if detail_lines:
            lines.append("")
            lines.extend(detail_lines)

        lines.append("")
        lines.append(_format_stats_block(stats))
        lines.append("")
        lines.append(f"☎ 联系方式： {contact}")
        if tag_line:
            lines.append("")
            lines.append(f"🏷 {tag_line}")
        lines.append("")
        lines.append(f"✳ 报告提交： @{bot_username}")

        # 末行品牌：{brand_name}： {brand_channels}
        # 注意：teacher.region 已在正文「📍 地区：」展示，footer 不再附加，
        # 避免出现「金融城 · 成都 · 《痴颜录》」这类把地名混进品牌行的问题。
        # 如需在 footer 显示城市，admin 可把 brand_name 配置为如「成都 · 《痴颜录》」
        if brand_name:
            brand_line = brand_name
            if brand_channels:
                brand_line = f"{brand_name}： {brand_channels}"
            lines.append("")
            lines.append(brand_line)

        return "\n".join(lines)

    cap = _build()
    if len(cap) <= CAPTION_MAX_LEN:
        return cap
    # 1) 禁忌缩到 100 字
    cap = _build(taboos_limit=100)
    if len(cap) <= CAPTION_MAX_LEN:
        return cap
    # 2) 服务缩到 200 字
    cap = _build(taboos_limit=100, svc_limit=200)
    if len(cap) <= CAPTION_MAX_LEN:
        return cap
    # 3) 服务 / 禁忌 进一步压缩
    cap = _build(taboos_limit=60, svc_limit=120)
    if len(cap) <= CAPTION_MAX_LEN:
        return cap
    # 4) 标签缩减
    cap = _build(tags_count=10, taboos_limit=60, svc_limit=120)
    if len(cap) <= CAPTION_MAX_LEN:
        return cap
    cap = _build(tags_count=5, taboos_limit=60, svc_limit=120)
    if len(cap) > CAPTION_MAX_LEN:
        cap = cap[: CAPTION_MAX_LEN - 1].rstrip() + "…"
    return cap
