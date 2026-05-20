"""集中注册全部 aiogram Router。

⚠️ 本模块在 2026-05-18 main.py 拆分时建立。**注册顺序逐行等价于拆分前的
bot/main.py L109-213**，注释一并保留——这些注释解释了"为什么 X 必须在 Y 之前
注册"，是当前 FSM / callback 命名空间 / message handler 命中关系的事实文档，
不要重排。

如果未来需要新增 router，请追加到 register_routers 内部的合适位置，并补充
"为什么放在这里"的注释。
"""

from __future__ import annotations

from aiogram import Dispatcher

from bot.handlers.admin_panel import router as admin_panel_router
from bot.handlers.admin_review import router as admin_review_router
from bot.handlers.favorite import router as favorite_router
from bot.handlers.hot_teachers import router as hot_teachers_router
from bot.handlers.publish_templates import router as publish_templates_router
from bot.handlers.admin_lottery import router as admin_lottery_router
from bot.handlers.admin_points import router as admin_points_router
from bot.handlers.admin_reimburse import router as admin_reimburse_router
from bot.handlers.discussion_anchor_listener import router as discussion_anchor_router
from bot.handlers.lottery_entry import router as lottery_entry_router
from bot.handlers.noop_handlers import router as noop_router
from bot.handlers.report_settings import router as report_settings_router
from bot.handlers.review_card import router as review_card_router
from bot.handlers.review_submit import router as review_submit_router
from bot.handlers.rreview_admin import router as rreview_admin_router
from bot.handlers.subreq_admin import router as subreq_admin_router
from bot.handlers.reimburse_subreq_admin import router as reimburse_subreq_admin_router
from bot.handlers.reimburse_settings_admin import router as reimburse_settings_admin_router
from bot.handlers.admin_keyword import router as admin_keyword_router
from bot.handlers.start_router import router as start_router
from bot.handlers.teacher_daily_status import router as teacher_daily_status_router
from bot.handlers.review_list import router as review_list_router
from bot.handlers.teacher_detail import router as teacher_detail_router
from bot.handlers.user_tags import router as user_tags_router
from bot.handlers.teacher_flow import router as teacher_flow_router
from bot.handlers.teacher_profile import router as teacher_profile_router
from bot.handlers.teacher_checkin import router as checkin_router
from bot.handlers.teacher_self import router as teacher_self_router
from bot.handlers.user_filter import router as user_filter_router
from bot.handlers.user_history import router as user_history_router
from bot.handlers.user_panel import router as user_panel_router
from bot.handlers.user_points import router as user_points_router
from bot.handlers.user_reimburse import router as user_reimburse_router
from bot.handlers.user_lottery import router as user_lottery_router
from bot.handlers.user_recommend import router as user_recommend_router
from bot.handlers.user_search import router as user_search_router
from bot.handlers.keyword import router as keyword_router


def register_routers(dp: Dispatcher) -> None:
    """把所有 router 按拆分前 main.py L109-213 的顺序注册到 dp。

    本函数与拆分前 main() 中的 include_router 序列**逐行等价**，注释也一并保留。
    """
    # 注册路由
    # start_router 必须最先：/start 角色分流入口（v2 §2.5）
    dp.include_router(start_router)
    # Phase 9.5.3：noop:* callback 占位（讨论群评论中间徽章按钮等）
    # 在所有具名 callback 之前注册，命名空间 noop: 与其它 callback 不冲突
    dp.include_router(noop_router)
    # favorite_router：fav:* callback（卡片场景 + "我的收藏"列表）
    dp.include_router(favorite_router)
    # teacher_detail_router（Phase 2）：teacher:view / teacher:toggle_fav / user:recent
    # 位置：favorite 之后、user_panel 之前。三个 callback 命名空间互不重叠，
    # keyword 也不会拦截（keyword 处理 group message，详情页全是 callback）
    dp.include_router(teacher_detail_router)
    # review_list_router (Phase 9.6.2)：teacher:reviews:<id> / teacher:reviews:<id>:<page>
    # 注册在 teacher_detail_router 之后；callback 命名空间 teacher:reviews:* 与
    # teacher:view:* / teacher:toggle_fav:* 等独立，分隔符明确
    dp.include_router(review_list_router)
    # hot_teachers_router（Phase 3）：user:hot / admin:hot_manage / admin:hot:*
    # FSM 状态 HotManageStates 保证文字消息只在该状态下被截获，
    # 与 admin_panel / teacher_self / user_search / keyword 的 message handler 不冲突
    dp.include_router(hot_teachers_router)
    # promo_links / source_stats（Phase 4）：2026-05-18 已下线
    # - promo_links handler / keyboard / FSM state 已于 2026-05-20 Sprint 7
    #   §9.1 第 1 批 dead code 删除
    # - source_stats handler / keyboard / FSM state 已于 2026-05-20 Sprint 7
    #   §9.1 第 2 批 dead code 删除
    # - bot/database.py 中 4 个 source DB helper 留待后续 PR 单独清理
    # teacher_daily_status_router（Phase 5）：
    # 老师今日状态（设置时间/取消/已满）+ 时间选择器 + 管理员今日总览 + noop 占位
    # 注册位置：在 teacher_self / user_panel / keyword 之前，保证 teacher:*/admin:today_status
    # callback 命名空间清晰；TeacherDailyStatusStates 保证文字消息仅在 FSM 中被截获
    dp.include_router(teacher_daily_status_router)
    # user_tags_router（Phase 6.1）：
    # admin:user_tags / admin:user_tags:query + 查询标签用户 FSM
    # UserTagsQueryStates 保证文字消息仅在 FSM 状态下被截获
    dp.include_router(user_tags_router)
    # publish_templates_router（Phase 6.2）：
    # admin:publish_templates / :list / :create / :edit_default / :set_default
    # PublishTemplateStates 4 个状态保证文字消息仅在 FSM 中被截获
    dp.include_router(publish_templates_router)
    # report_settings_router（Phase 6.3）：
    # admin:report_settings / admin:report:* + 4 个 FSM 状态
    # ReportSettingsStates 保证文字消息只在 FSM 中被截获
    dp.include_router(report_settings_router)
    # admin_review_router 在 admin_panel 之前：review:* callback 不会和老师管理 callback 冲突，
    # FSM 状态 (ReviewStates.waiting_reject_reason) 保证文字消息只在该状态下被接住
    dp.include_router(admin_review_router)
    # rreview_admin_router (Phase 9.4)：rreview:* 报告审核 callback + FSM
    # 在 admin_review 之后、admin_panel 之前：callback 命名空间 rreview:* 与
    # review:* 完全独立，FSM 状态保证文字消息只在 RReviewRejectStates 中被截获
    dp.include_router(rreview_admin_router)
    dp.include_router(admin_panel_router)
    # admin_points_router (Phase P.3)：admin:points:* 超管积分管理工具
    # 必须在 admin_panel 之后（主菜单已嵌入 admin:points 入口），_super_admin_required
    # 装饰器保证非超管被拒
    dp.include_router(admin_points_router)
    # admin_lottery_router (Phase L.1)：admin:lottery:* 超管抽奖管理
    # 在 admin_panel 之后，与 admin_points 命名空间独立
    dp.include_router(admin_lottery_router)
    # admin_reimburse_router (报销审核子系统)：reimburse:* 超管报销审批
    dp.include_router(admin_reimburse_router)
    # subreq_admin_router (Phase 9.3)：admin:subreq:* callback + SubReqAddStates
    # 必须在 admin_panel 之后（系统设置子菜单已含 admin:subreq 入口），
    # SubReqAddStates FSM 保证文字消息仅在状态中被截获
    dp.include_router(subreq_admin_router)
    # reimburse_subreq_admin_router：报销专用必关 system:reimburse_subreq:* +
    # ReimburseSubReqAddStates FSM；命名空间与 admin:subreq:* 独立，互不影响
    dp.include_router(reimburse_subreq_admin_router)
    # reimburse_settings_admin_router：报销门槛 + 月度池重置基线配置
    # callback 命名空间 system:reimburse_min_points:* + system:reimburse_pool_reset:*
    # 与 system:reimburse_pool / system:reimburse_toggle 独立，互不影响
    dp.include_router(reimburse_settings_admin_router)
    # UX-9.1：admin_keyword_router 群组快捷词配置
    # callback 命名空间 admin:keywords:*；QuickEntryKeywordStates 保证文字消息
    # 仅在 FSM 中被截获，不与 keyword.py 的群消息 catch-all 冲突
    dp.include_router(admin_keyword_router)
    # teacher_profile_router (Phase 9.1)：tprofile:* callback + 完整档案录入 FSM
    # 必须在 teacher_flow_router 之前注册，避免 teacher_flow 通用 message handler
    # 拦截 TeacherProfileAddStates 的输入。callback 命名空间独立 (tprofile:*)。
    dp.include_router(teacher_profile_router)
    dp.include_router(teacher_flow_router)
    dp.include_router(checkin_router)
    # teacher_self_router 在 user_panel 之前：teacher_self:* callback 仅对老师角色有意义
    dp.include_router(teacher_self_router)
    # user_panel / user_search 在 keyword 之前：
    #   - user_panel 的 callback (user:*) 不会和 keyword 冲突
    #   - user_search 的 SearchStates filter 保证只在搜索 FSM 状态下匹配
    dp.include_router(user_panel_router)
    # Phase P.2：user_points_router 在 user_panel 之后；
    #   - user:points / user:points:list / user:points:list:<page> 命名空间独立
    #   - 不与 user:favorites / user:recent 等冲突
    dp.include_router(user_points_router)
    # 报销子系统用户侧：user:reimburse / user:reimburse:list[:page]
    dp.include_router(user_reimburse_router)
    # UX-6.1：抽奖中心用户侧（user:lottery / user:lottery:active / :joined / :drawn）
    # 注册在 user_panel 之后、keyword 之前；callback 命名空间 user:lottery:*
    # 与既有 user:* / lottery_entry handler 完全独立
    dp.include_router(user_lottery_router)
    # Phase 7.2：user_filter_router / user_recommend_router
    # 注册在 user_panel 之后、user_search / keyword 之前。
    #   - callback 命名空间独立：user:filter:* / user:recommend:*
    #   - FilterStates 仅在该状态下截获 /cancel，不影响其他文字消息
    dp.include_router(user_filter_router)
    dp.include_router(user_recommend_router)
    # Phase 7.3：user_history_router
    #   - user:search_history / user:continue_last / user:reminders
    #   - SearchHistoryStates 仅在自身 FSM 状态下截获 /cancel
    dp.include_router(user_history_router)
    # review_submit_router：[📝 写评价] 入口 + 个人评价主页
    # - review:start:<id> 入口经 start_review_flow 直接重定向到 CardReviewStates
    # - 旧线性 ReviewSubmitStates FSM 已于 2026-05-20 Sprint 7 §9.1 第 3 批
    #   dead code 删除中清理（commit <本 PR>）
    # review_card_router (2026-05-18 Phase 2)：卡片驱动评价 FSM
    # - 命名空间 card:* 与 review:* 独立；CardReviewStates 状态过滤防误截
    # - 注册位置在 review_submit_router 之前（即更早注册），保证 card:* 优先匹配；
    #   实际入口由 review_submit.start_review_flow 重定向到 card 流程
    dp.include_router(review_card_router)
    dp.include_router(review_submit_router)
    dp.include_router(user_search_router)
    # Phase 9.5.2：discussion_anchor_listener 监听讨论群 is_automatic_forward 消息
    # 必须在 keyword 之前（keyword 是 catch-all）；F.is_automatic_forward 过滤
    # 保证只对自动转发消息触发，不与正常群组关键词冲突
    dp.include_router(discussion_anchor_router)
    # Phase L.2.3：lottery_entry 私聊文字尝试匹配口令；不匹配 silent skip
    # 必须在 keyword 之前；F.chat.type == "private" + F.text 过滤；
    # 群消息走 keyword 不冲突
    dp.include_router(lottery_entry_router)
    dp.include_router(keyword_router)  # keyword 放最后，避免拦截其他消息
