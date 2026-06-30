"""迁移版本 baseline —— 单一事实来源（替代 30+ 测试文件各自硬编码）。

这些护栏测试（test_no_schema_migration_added / test_migrations_list_still_empty /
test_module_level_migrations_is_baseline 等）锁定 bot.database.MIGRATIONS：
**新增或删除迁移时，只需更新此处一个常量**，护栏即重新对齐——以强制 code
review 注意到 schema 变更。

历史背景：以前每个测试文件各自硬编码完整版本集，加一个迁移要批量改 30+ 处
（极易漏改 / 改错）；现集中到此常量。
"""

EXPECTED_MIGRATION_VERSIONS = frozenset({
    "20260520_001_teacher_draft_states",
    "20260520_002_quick_entry_keywords",
    "20260521_001_teacher_reviews_gesture_nullable",
    "20260613_001_teacher_is_deleted",
    "20260613_002_remove_quick_entry_keywords",
    "20260630_001_rating_from_overall",
    "20260630_002_review_hidden",
})
