from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    """普通用户私聊搜索状态（F4，v2 §2.4）"""
    waiting_query = State()
