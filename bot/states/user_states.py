from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    """普通用户私聊搜索状态（F4，v2 §2.4）"""
    waiting_query = State()


class FilterStates(StatesGroup):
    """条件筛选器临时状态（Phase 7.2）

    waiting_pick: 用户已选择"按地区/价格/标签"，等待从动态选项中点选一个。
    state.data 结构:
        {
            "filter_type": "region" | "price" | "tag",
            "options": ["天府一街", "金融城", ...]  # 与按钮 callback 的 index 对齐
        }

    把 options 放在 state 而不是 callback_data，避开中文长字符串和 Telegram 64 字节限制。
    """
    waiting_pick = State()


class SearchHistoryStates(StatesGroup):
    """搜索历史临时状态（Phase 7.3）

    waiting_pick: 已展示用户最近 N 次搜索词，等待点选其中一个回放。
    state.data 结构:
        {
            "queries": ["御姐 1000P", "天府一街", ...]  # 与按钮 callback index 对齐
        }
    """
    waiting_pick = State()
