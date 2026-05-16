import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone

from bot.config import config
from bot.database import init_db
from bot.handlers.admin_panel import router as admin_panel_router
from bot.handlers.admin_review import router as admin_review_router
from bot.handlers.favorite import router as favorite_router
from bot.handlers.hot_teachers import router as hot_teachers_router
from bot.handlers.promo_links import router as promo_links_router
from bot.handlers.publish_templates import router as publish_templates_router
from bot.handlers.admin_lottery import router as admin_lottery_router
from bot.handlers.admin_points import router as admin_points_router
from bot.handlers.admin_reimburse import router as admin_reimburse_router
from bot.handlers.discussion_anchor_listener import router as discussion_anchor_router
from bot.handlers.lottery_entry import router as lottery_entry_router
from bot.handlers.noop_handlers import router as noop_router
from bot.handlers.report_settings import router as report_settings_router
from bot.handlers.review_submit import router as review_submit_router
from bot.handlers.rreview_admin import router as rreview_admin_router
from bot.handlers.source_stats import router as source_stats_router
from bot.handlers.subreq_admin import router as subreq_admin_router
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
from bot.handlers.user_recommend import router as user_recommend_router
from bot.handlers.user_search import router as user_search_router
from bot.handlers.keyword import router as keyword_router
from bot.scheduler.lottery_tasks import schedule_pending_lotteries
from bot.scheduler.tasks import (
    schedule_checkin_reminder,
    schedule_daily_publish,
    schedule_daily_report,
    schedule_weekly_report,
)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 创建 Bot 和 Dispatcher
bot = Bot(token=config.bot_token)
dp = Dispatcher(storage=MemoryStorage())

# 创建调度器
scheduler = AsyncIOScheduler(timezone=timezone(config.timezone))


async def on_startup():
    """启动时执行"""
    await init_db()
    logger.info("数据库初始化完成")

    # 配置定时任务
    publish_time = await schedule_daily_publish(scheduler, bot)
    reminder_time = await schedule_checkin_reminder(scheduler, bot)
    daily_report_time = await schedule_daily_report(scheduler, bot)
    weekly_report_time = await schedule_weekly_report(scheduler, bot)
    scheduler.start()
    logger.info(
        f"定时任务已启动，发布时间: {publish_time}，签到提醒时间: {reminder_time}，"
        f"日报: {daily_report_time}，周报: {weekly_report_time} ({config.timezone})"
    )

    # Phase L.2：bot 重启时扫所有 scheduled/active 抽奖重注册定时任务（spec §8）
    try:
        lottery_summary = await schedule_pending_lotteries(scheduler, bot)
        logger.info(
            "抽奖任务扫描完成：发布 %d / 开奖 %d",
            lottery_summary["scheduled_publish"],
            lottery_summary["scheduled_draw"],
        )
    except Exception as e:
        logger.warning("schedule_pending_lotteries 失败（不阻断启动）: %s", e)

    me = await bot.get_me()
    logger.info(f"Bot 启动成功: @{me.username} (ID: {me.id})")


async def on_shutdown():
    """关闭时执行"""
    scheduler.shutdown(wait=False)
    await bot.session.close()
    logger.info("Bot 已关闭")


async def main():
    """主入口"""
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
    # promo_links_router / source_stats_router（Phase 4）：
    # 推广链接生成器 + 渠道统计 + 用户来源查询
    # PromoLinkStates / UserSourceLookupStates 保证文字消息只在对应状态下被截获
    dp.include_router(promo_links_router)
    dp.include_router(source_stats_router)
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
    # Phase 9.3：review_submit_router 在 user_search 之前
    # - review:start:<id> / review:rating:* / review:score:* / review:submit / review:cancel
    # - ReviewSubmitStates FSM 状态过滤保证文字消息只在评价 FSM 中被截获
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

    # 注册生命周期钩子
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # 启动轮询
    logger.info("开始轮询...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
