"""群组关键词搜索结果渲染（2026-05：完整 + 超链接 + 分页）契约测试。

要点：
    1. 老师名整行做超链接 <a href="button_url">...</a>
    2. button_url 无效 → 退化为纯文本（同样布局）
    3. 不再硬截到前 5 位，遍历全部 teachers
    4. per_page 控制每页条数；超过 per_page 自动分页
    5. 单条消息 ≤ Telegram 4096 字符
    6. HTML 注入防御（< > & 必 escape）
    7. _handle_combo_search 用 ParseMode.HTML + disable_web_page_preview
    8. 组合搜索结果不再附底部按钮（2026-06 查看全部/筛选/热门整组移除）
"""
from __future__ import annotations

import inspect


def _src(module) -> str:
    return inspect.getsource(module)


def _fake_teacher(
    *, name: str = "老师A", url: str = "https://example.com/a",
    region: str = "上海", price: str = "100",
    signed_in: int = 0,
    daily_status: str = "",
    **extra,
) -> dict:
    t = {
        "user_id": hash(name) & 0xfff,
        "display_name": name,
        "button_url": url,
        "button_text": "联系老师",
        "region": region,
        "price": price,
        "signed_in_today": signed_in,
        "daily_status_class": daily_status,
    }
    t.update(extra)
    return t


# ============================================================
# 1. 单页：HTML + 超链接
# ============================================================


def test_render_pages_single_page_has_hyperlinks():
    """有 button_url 的老师 → 渲染为 <a href=...> 超链接。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [
        _fake_teacher(name="张三", url="https://example.com/zhang"),
        _fake_teacher(name="李四", url="https://example.com/li"),
    ]
    pages = render_group_search_result_pages(teachers, total_count=2)
    assert len(pages) == 1
    text = pages[0]
    assert '<a href="https://example.com/zhang">' in text
    assert '<a href="https://example.com/li">' in text
    assert "</a>" in text


def test_render_pages_no_url_degrades_to_plain_text():
    """button_url 缺失 → 退化为纯文本（不带 <a>），布局保留。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [
        _fake_teacher(name="无链接老师", url=""),
    ]
    pages = render_group_search_result_pages(teachers, total_count=1)
    text = pages[0]
    assert "1. 无链接老师" in text
    # 无链接的这条不应有 <a 标签
    assert "<a " not in text or 'href="">' not in text  # 防御


def test_render_pages_mixed_url_and_no_url():
    """同一页混合：有 url 的成超链接，没 url 的纯文本。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [
        _fake_teacher(name="有链接", url="https://example.com/ok"),
        _fake_teacher(name="无链接", url=""),
        _fake_teacher(name="也有链接", url="https://example.com/ok2"),
    ]
    pages = render_group_search_result_pages(teachers, total_count=3)
    text = pages[0]
    assert text.count("<a ") == 2  # 仅 2 个超链接
    assert "1. 有链接" in text
    assert "2. 无链接" in text
    assert "3. 也有链接" in text


# ============================================================
# 2. 完整覆盖（不再截断）
# ============================================================


def test_render_pages_does_not_truncate():
    """命中 20 位 → 全部展示（不再截断到前 5）。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [_fake_teacher(name=f"老师{i}", url=f"https://e.com/{i}") for i in range(20)]
    pages = render_group_search_result_pages(teachers, total_count=20)
    full = "\n".join(pages)
    # 每位老师都应出现
    for i in range(20):
        assert f"老师{i}" in full


def test_render_pages_total_count_in_header():
    """每页头部应含 total_count（命中总数）。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [_fake_teacher(name=f"老师{i}", url=f"https://e.com/{i}") for i in range(5)]
    pages = render_group_search_result_pages(teachers, total_count=5)
    assert "找到 5 位相关老师" in pages[0]


# ============================================================
# 3. 分页
# ============================================================


def test_render_pages_paginates_when_exceeding_per_page():
    """命中 60 位、per_page=25 → 3 页。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [_fake_teacher(name=f"T{i}", url=f"https://e.com/{i}") for i in range(60)]
    pages = render_group_search_result_pages(teachers, total_count=60, per_page=25)
    assert len(pages) == 3  # 25+25+10
    # 每页头部含页码
    assert "第 1/3 页" in pages[0]
    assert "第 2/3 页" in pages[1]
    assert "第 3/3 页" in pages[2]


def test_render_pages_single_page_no_pagination_marker():
    """单页（≤ per_page）头部不应含页码。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [_fake_teacher(name=f"T{i}", url=f"https://e.com/{i}") for i in range(5)]
    pages = render_group_search_result_pages(teachers, total_count=5, per_page=25)
    assert len(pages) == 1
    assert "/" not in pages[0].splitlines()[0]  # 第一行无 "第 X/Y 页"


def test_render_pages_continues_numbering_across_pages():
    """跨页时序号继续递增（不从 1 重新开始）。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [_fake_teacher(name=f"T{i}", url=f"https://e.com/{i}") for i in range(30)]
    pages = render_group_search_result_pages(teachers, total_count=30, per_page=25)
    assert len(pages) == 2
    # 第 1 页含 1./25.（号码包在 <a href="..."> 中，匹配 ">1. " 等形式）
    assert ">1. " in pages[0]
    assert ">25. " in pages[0]
    assert ">26. " not in pages[0]  # 26 不应在第一页
    # 第 2 页应从 26 开始
    assert ">26. " in pages[1]
    assert ">30. " in pages[1]
    assert ">1. " not in pages[1]   # 第二页不应再从 1 开始


def test_render_pages_empty_returns_empty_list():
    from bot.utils.group_search import render_group_search_result_pages
    assert render_group_search_result_pages([], total_count=0) == []


# ============================================================
# 4. Telegram 长度约束
# ============================================================


def test_render_pages_each_page_under_telegram_limit():
    """每页文本 ≤ Telegram 4096 字符上限。"""
    from bot.utils.group_search import render_group_search_result_pages
    # 极端：60 位老师 + 较长 url
    teachers = [
        _fake_teacher(
            name=f"老师 #{i} 完整名字",
            url=f"https://example.com/teachers/{i}?ref=group",
            region=f"区域{i}",
            price=f"{100+i}",
        )
        for i in range(60)
    ]
    pages = render_group_search_result_pages(teachers, total_count=60, per_page=25)
    for idx, p in enumerate(pages):
        assert len(p) <= 4096, (
            f"page {idx} 超过 Telegram 4096 字符限制（{len(p)} 字节）"
        )


def test_per_page_25_default():
    """默认 per_page=25。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [_fake_teacher(name=f"T{i}", url=f"https://e.com/{i}") for i in range(30)]
    pages = render_group_search_result_pages(teachers, total_count=30)
    assert len(pages) == 2  # 25 + 5


# ============================================================
# 5. HTML 注入防御
# ============================================================


def test_html_escape_in_name():
    """老师名含 < > & 必须 HTML 转义。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [
        _fake_teacher(name="<script>alert(1)</script>", url="https://e.com/x"),
    ]
    pages = render_group_search_result_pages(teachers, total_count=1)
    text = pages[0]
    # 原始尖括号不应出现在输出中
    assert "<script>" not in text
    # 应被转义为 &lt;script&gt;
    assert "&lt;script&gt;" in text


def test_html_escape_in_url():
    """URL 含 " 等特殊字符必须 escape。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [
        _fake_teacher(name="X", url='https://e.com/"; onclick="evil()'),
    ]
    pages = render_group_search_result_pages(teachers, total_count=1)
    text = pages[0]
    # 不应有未转义的双引号 + onclick
    assert 'onclick=' not in text or '&quot;' in text


def test_html_escape_in_region_price():
    """region / price 字段也必须 escape（防止注入）。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [
        _fake_teacher(name="X", url="https://e.com/x", region="<b>北京</b>", price="<100>"),
    ]
    pages = render_group_search_result_pages(teachers, total_count=1)
    text = pages[0]
    assert "<b>北京</b>" not in text
    assert "&lt;100&gt;" in text


# ============================================================
# 6. _handle_combo_search 使用 ParseMode.HTML + 分页
# ============================================================


def test_handle_combo_search_uses_parse_mode_html():
    """_handle_combo_search 应用 ParseMode.HTML 发送。"""
    import bot.handlers.keyword as mod
    src = _src(mod)
    idx = src.find("async def _handle_combo_search(")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert "ParseMode.HTML" in body


def test_handle_combo_search_uses_paginated_renderer():
    """_handle_combo_search 应调用 render_group_search_result_pages（不再用旧 _text）。"""
    import bot.handlers.keyword as mod
    src = _src(mod)
    idx = src.find("async def _handle_combo_search(")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert "render_group_search_result_pages" in body


def test_handle_combo_search_keeps_disable_web_page_preview():
    """禁止 url 预览（避免列表中大量超链接生成预览刷屏）。"""
    import bot.handlers.keyword as mod
    src = _src(mod)
    idx = src.find("async def _handle_combo_search(")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert "disable_web_page_preview=True" in body


def test_handle_combo_search_attaches_no_buttons():
    """≥2 结果：逐页 send，各页均不附底部按钮（2026-06 三按钮整组移除）。"""
    import bot.handlers.keyword as mod
    src = _src(mod)
    idx = src.find("async def _handle_combo_search(")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    # 仍逐页循环发送
    assert "for " in body
    # 不再有"最后一页才附 kb"的逻辑 / 不再引用废弃的 kb 构造
    assert "page_kb" not in body
    assert "_build_combo_search_kb" not in body
    # reply_markup 仅以 None 形式出现（不附任何按钮）
    assert "reply_markup=None" in body


# ============================================================
# 7. 兼容性 + 老接口
# ============================================================


def test_legacy_render_text_function_still_callable():
    """旧 render_group_search_result_text 仍可调用（向后兼容）。"""
    from bot.utils.group_search import render_group_search_result_text
    teachers = [_fake_teacher(name=f"T{i}", url=f"https://e.com/{i}") for i in range(5)]
    text = render_group_search_result_text(
        teachers, total_count=5, display_limit=5,
    )
    assert isinstance(text, str)
    assert "找到 5 位相关老师" in text


def test_legacy_no_truncation_message():
    """旧文案"建议私聊查看更多" / "先展示前 X 位" 已被移除（不再有不完整展示）。"""
    from bot.utils.group_search import render_group_search_result_pages
    teachers = [_fake_teacher(name=f"T{i}", url=f"https://e.com/{i}") for i in range(30)]
    pages = render_group_search_result_pages(teachers, total_count=30, per_page=25)
    full = "\n".join(pages)
    assert "建议私聊查看更多" not in full
    assert "先展示前" not in full


def test_combo_search_bottom_buttons_removed():
    """组合搜索底部三按钮（查看全部结果/按条件筛选/热门推荐）已整组移除。

    断言代码级 token（非散文措辞——解释性注释可合法提及这些中文名）：
    不再构造按钮键盘、不再引用 filter/hot 死深链与 q_ 编码。
    """
    import bot.handlers.keyword as mod
    src = _src(mod)
    assert "_build_combo_search_kb" not in src       # 键盘构造函数已删
    assert "?start=filter" not in src                # filter 死深链已清
    assert "?start=hot" not in src                   # hot 死深链已清
    assert "encode_query_for_deep_link" not in src   # q_ 编码不再在本 handler 引用
    # 单老师卡片仍走 _send_teacher_group_card_v2（matched_count==1 分支）
    assert "_send_teacher_group_card_v2" in src


def test_handle_combo_search_single_match_unchanged():
    """单结果路径未受影响：仍调 _send_teacher_group_card_v2。"""
    import bot.handlers.keyword as mod
    src = _src(mod)
    idx = src.find("async def _handle_combo_search(")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    body = src[idx:end if end > 0 else idx + 5000]
    assert "matched_count == 1" in body
    assert "_send_teacher_group_card_v2" in body


# ============================================================
# 8. Schema / 业务隔离（防御性）
# ============================================================


def test_schema_migrations_baseline_unchanged():
    """本批仅 UI 文案改动，零 schema 影响。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    from _migration_baseline import EXPECTED_MIGRATION_VERSIONS
    assert {m.version for m in MIGRATIONS} == EXPECTED_MIGRATION_VERSIONS


def test_keyword_router_still_importable():
    from bot.handlers.keyword import router
    assert router is not None


def test_teacher_card_v2_kb_two_buttons_deeplink_only():
    """单老师群卡片（精简版）：仅「私聊详情」「写评价」两个 startapp 深链按钮，
    不再有联系老师(button_url) / 收藏(group:fav)。"""
    from bot.utils.teacher_render import build_teacher_group_card_v2_kb
    teacher = {
        "user_id": 100,
        "button_url": "https://example.com/contact",
        "button_text": "联系",
    }
    kb = build_teacher_group_card_v2_kb(teacher, bot_username="testbot")
    buttons = [b for row in kb.inline_keyboard for b in row]
    urls = [b.url or b.callback_data or "" for b in buttons]
    # 恰好两个按钮
    assert len(buttons) == 2
    # 两个 startapp 深链直达 MiniApp（详情页 + 写评价页）
    assert any("?startapp=teacher_100" in u for u in urls)
    assert any("?startapp=write_100" in u for u in urls)
    # 不再有联系老师（button_url）与收藏（group:fav）
    assert not any("example.com/contact" in u for u in urls)
    assert not any("group:fav" in u for u in urls)


def test_teacher_card_v2_kb_fallback_without_bot_username():
    """bot_username 缺失兜底：私聊详情退化为 callback，写评价跳过。"""
    from bot.utils.teacher_render import build_teacher_group_card_v2_kb
    kb = build_teacher_group_card_v2_kb({"user_id": 100, "button_url": "", "button_text": ""}, None)
    buttons = [b for row in kb.inline_keyboard for b in row]
    assert len(buttons) == 1
    assert buttons[0].callback_data == "teacher:view:100"
