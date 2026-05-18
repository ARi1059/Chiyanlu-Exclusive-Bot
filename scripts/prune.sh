#!/usr/bin/env bash
# Chiyanlu-Exclusive-Bot 历史数据 pruning · P2 dry-run（详见 docs/PRUNING-DESIGN.md）
#
# 用法：
#   ./scripts/prune.sh --dry-run                  # 默认 days=180
#   ./scripts/prune.sh --dry-run --days 180
#   ./scripts/prune.sh --dry-run --days 365
#   ./scripts/prune.sh --help
#
# ⚠️ 本阶段（P2）严格只读 —— 不删除任何数据，不执行 VACUUM。
#    脚本对数据库的实际 sqlite3 调用仅包含 PRAGMA / SELECT 语句。
#    任何形如 --confirm / --delete / --vacuum / --execute 的参数都会立即报错退出，
#    防止误以为 P3 已实现而触发删除路径。
#
# 适用：Debian 12 生产服务器；可手工触发，**不**接 scheduler。

set -euo pipefail

# ============ 解析项目根 ============
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}"

# ============ 默认配置 ============
DEFAULT_DAYS=180
DEFAULT_DB_PATH="data/bot.db"

# 第一阶段白名单表：仅纯日志类（详见 PRUNING-DESIGN §四）
# 不要在此列表中加入任何权益类表（point_transactions / reimbursements /
# lottery_entries / teacher_reviews 等），P3 阶段也不会加。
WHITELIST_TABLES=(
    "user_events"
    "user_teacher_views"
)

# 每张白名单表对应的时间字段（真实 schema 中的列名）
# 用 case 语句而不是 associative array，避免 bash 3 兼容性问题。
table_time_col() {
    case "$1" in
        user_events)         echo "created_at" ;;
        user_teacher_views)  echo "viewed_at" ;;
        *)                   echo "" ;;
    esac
}
# ==================================

# 颜色输出（与 update.sh / healthcheck.sh / backup.sh 风格一致）
if [[ -t 1 ]]; then
    RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BLUE=$'\033[0;34m'; NC=$'\033[0m'
else
    RED=""; GREEN=""; YELLOW=""; BLUE=""; NC=""
fi
info() { echo "${BLUE}[INFO]${NC} $*"; }
ok()   { echo "${GREEN}[ OK ]${NC} $*"; }
warn() { echo "${YELLOW}[WARN]${NC} $*"; }
err()  { echo "${RED}[ERR ]${NC} $*" >&2; }


# ============ 用法 ============
show_help() {
    cat <<'EOF'
用法：
  ./scripts/prune.sh --dry-run                默认 days=180，只统计、不删除
  ./scripts/prune.sh --dry-run --days N       自定义保留天数（非负整数）
  ./scripts/prune.sh --help                   显示帮助

输出：
  对每张白名单表（user_events / user_teacher_views）输出：
    condition         实际 WHERE 子句（含真实时间字段名）
    matched_rows      命中行数
    oldest_created_at 命中行中最早时间戳
    newest_created_at 命中行中最新时间戳
    action            safe-to-delete-after-backup 或 nothing-to-prune
  最后打印 summary（tables_checked / tables_skipped / total_matched_rows）

注意：
  - 本阶段仅 dry-run。任何 --confirm / --delete / --vacuum / --execute 参数
    会立即报错退出。
  - 实际清理路径（P3）尚未实施。即使本地有当天的 manual 备份，也无法用本脚本
    真正删除数据 —— 这是设计行为。
EOF
}


# ============ 参数解析 ============
MODE=""
DAYS="${DEFAULT_DAYS}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            MODE="dry-run"
            ;;
        --days)
            shift
            if [[ $# -eq 0 ]]; then
                err "--days 需要一个非负整数参数"
                exit 1
            fi
            if [[ ! "$1" =~ ^[0-9]+$ ]]; then
                err "--days 必须是非负整数，得到：$1"
                exit 1
            fi
            DAYS="$1"
            ;;
        --days=*)
            v="${1#--days=}"
            if [[ ! "$v" =~ ^[0-9]+$ ]]; then
                err "--days 必须是非负整数，得到：$v"
                exit 1
            fi
            DAYS="$v"
            ;;
        --confirm|--delete|--vacuum|--execute)
            err "当前版本只支持 --dry-run，不支持真实删除。"
            err "P3 阶段（带 --confirm 的实际清理）尚未实施。详见 docs/PRUNING-DESIGN.md §十"
            exit 1
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            err "未知参数：$1"
            echo
            show_help
            exit 1
            ;;
    esac
    shift
done

if [[ "${MODE}" != "dry-run" ]]; then
    err "必须显式传 --dry-run。本阶段不支持真实删除。"
    echo
    show_help
    exit 1
fi


# ============ 依赖检查 ============
if ! command -v sqlite3 >/dev/null 2>&1; then
    err "未找到 sqlite3 命令（apt install -y sqlite3）"
    exit 1
fi


# ============ 读取 DATABASE_PATH（不输出 .env） ============
DB_PATH="${DEFAULT_DB_PATH}"
if [[ -f .env ]]; then
    db_line=$(grep -E '^[[:space:]]*DATABASE_PATH[[:space:]]*=' .env 2>/dev/null | tail -n 1 || true)
    if [[ -n "${db_line}" ]]; then
        raw="${db_line#*=}"
        raw="${raw#"${raw%%[![:space:]]*}"}"
        raw="${raw%"${raw##*[![:space:]]}"}"
        raw="${raw%\"}"; raw="${raw#\"}"
        raw="${raw%\'}"; raw="${raw#\'}"
        [[ -n "${raw}" ]] && DB_PATH="${raw}"
    fi
fi

# 相对路径相对项目根
if [[ "${DB_PATH}" != /* ]]; then
    DB_PATH="${PROJECT_DIR}/${DB_PATH}"
fi

if [[ ! -f "${DB_PATH}" ]]; then
    err "数据库文件不存在：${DB_PATH}"
    exit 1
fi


# ============ 前置只读检查 ============
# 仅 PRAGMA + SELECT，绝不修改数据
integrity=$(sqlite3 "${DB_PATH}" "PRAGMA integrity_check;" 2>/dev/null | head -1 || true)
if [[ "${integrity}" != "ok" ]]; then
    err "PRAGMA integrity_check 异常（返回值非 ok）：${integrity}"
    err "数据库可能损坏，请勿继续运维操作。详见 docs/RUNBOOK.md §五"
    exit 1
fi

journal=$(sqlite3 "${DB_PATH}" "PRAGMA journal_mode;" 2>/dev/null | head -1 || true)
if [[ "${journal}" != "wal" ]]; then
    warn "PRAGMA journal_mode = '${journal}'（预期 wal，不阻断）"
fi


# ============ Dry-run banner ============
info "Dry-run only. No rows will be deleted."
info "days=${DAYS}"
info "target tables: ${WHITELIST_TABLES[*]}"
info "database: ${DB_PATH}"


# ============ 统计每张表 ============
# 拿到现有表清单（一次性，避免多次 IO）
existing_tables=$(sqlite3 "${DB_PATH}" \
    "SELECT name FROM sqlite_master WHERE type='table';" 2>/dev/null || true)

TABLES_CHECKED=0
TABLES_SKIPPED=0
TOTAL_MATCHED=0

for table in "${WHITELIST_TABLES[@]}"; do
    echo
    info "Table: ${table}"

    # 表是否存在
    if ! grep -Fxq "${table}" <<<"${existing_tables}"; then
        warn "  表不存在，跳过（兼容旧库或部分裁剪部署）"
        TABLES_SKIPPED=$((TABLES_SKIPPED + 1))
        continue
    fi

    # 该表使用的时间字段（脚本顶部已声明）
    time_col=$(table_time_col "${table}")
    if [[ -z "${time_col}" ]]; then
        warn "  未为该表声明时间字段，跳过"
        TABLES_SKIPPED=$((TABLES_SKIPPED + 1))
        continue
    fi

    # 真实列存在性（PRAGMA table_info 只读）
    table_cols=$(sqlite3 "${DB_PATH}" "PRAGMA table_info(${table});" 2>/dev/null \
        | awk -F'|' '{print $2}' || true)
    if ! grep -Fxq "${time_col}" <<<"${table_cols}"; then
        warn "  时间字段 '${time_col}' 在 ${table} 中不存在，跳过"
        TABLES_SKIPPED=$((TABLES_SKIPPED + 1))
        continue
    fi

    # WHERE 条件（共用模板：dry-run 与未来 P3 confirm 必须一致）
    condition="${time_col} < datetime('now', '-${DAYS} days')"

    # 统计 —— 只 SELECT，绝不修改
    matched=$(sqlite3 "${DB_PATH}" \
        "SELECT COUNT(*) FROM ${table} WHERE ${condition};" 2>/dev/null || echo "?")
    oldest=$(sqlite3 "${DB_PATH}" \
        "SELECT MIN(${time_col}) FROM ${table} WHERE ${condition};" 2>/dev/null || true)
    newest=$(sqlite3 "${DB_PATH}" \
        "SELECT MAX(${time_col}) FROM ${table} WHERE ${condition};" 2>/dev/null || true)

    echo "  condition: ${condition}"
    echo "  matched_rows: ${matched}"
    echo "  oldest_created_at: ${oldest:-N/A}"
    echo "  newest_created_at: ${newest:-N/A}"
    if [[ "${matched}" == "0" ]]; then
        echo "  action: nothing-to-prune"
    else
        echo "  action: safe-to-delete-after-backup"
    fi

    TABLES_CHECKED=$((TABLES_CHECKED + 1))
    # matched 可能是 "?" —— 仅在数值时累加
    if [[ "${matched}" =~ ^[0-9]+$ ]]; then
        TOTAL_MATCHED=$((TOTAL_MATCHED + matched))
    fi
done


# ============ Summary ============
echo
echo "Prune dry-run summary:"
echo "- tables_checked: ${TABLES_CHECKED}"
echo "- tables_skipped: ${TABLES_SKIPPED}"
echo "- total_matched_rows: ${TOTAL_MATCHED}"
echo "- days: ${DAYS}"
echo "- mode: dry-run"

exit 0
