#!/usr/bin/env bash
# Chiyanlu-Exclusive-Bot 历史数据 pruning · P2 dry-run + P3 --confirm
#   （详见 docs/INFRASTRUCTURE-DESIGN.md (Part B) + ROADMAP-PLAN.md §9.2）
#
# 用法：
#   ./scripts/prune.sh --dry-run                    # 默认 days=180，仅统计
#   ./scripts/prune.sh --dry-run --days 180
#   ./scripts/prune.sh --dry-run --days 365
#   ./scripts/prune.sh --confirm --days 180         # 真实删除（P3）
#   ./scripts/prune.sh --help
#
# ⚠️ --confirm 路径双重保护：
#    1. 必须**显式**传 --days N（即便用默认 180 也得显式带）—— 强制运维
#       重新输入 days，避免"依赖上一次 dry-run 的 days"
#    2. --confirm 与 --dry-run 互斥
#
# ⚠️ 永久禁止表（即使有人不慎修改 WHITELIST_TABLES 也会被 PERMANENT_FORBIDDEN
#    交集检查阻断）：
#      point_transactions / reimbursements / lottery_entries / teacher_reviews /
#      admin_audit_logs / users / teachers / favorites
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
BACKUP_DIR="${PROJECT_DIR}/backups"
SAFETY_DELAY_SECONDS=5

# 第一阶段白名单表：仅纯日志类（详见 INFRASTRUCTURE-DESIGN.md Part B §四）
# 不要在此列表中加入任何权益类表（point_transactions / reimbursements /
# lottery_entries / teacher_reviews 等）。下方 PERMANENT_FORBIDDEN_TABLES 会做
# 交集检查，违规会立即报错 exit。
WHITELIST_TABLES=(
    "user_events"
    "user_teacher_views"
)

# 永久禁止 prune 的权益表（ROADMAP §9.2 / POLICY 多处）。即使有人误把这些表加到
# WHITELIST_TABLES，--confirm 路径会先做交集检查并立即 exit 1（编程错误防护）。
PERMANENT_FORBIDDEN_TABLES=(
    "point_transactions"
    "reimbursements"
    "lottery_entries"
    "teacher_reviews"
    "admin_audit_logs"
    "users"
    "teachers"
    "favorites"
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
  ./scripts/prune.sh --confirm --days N       真实删除 N 天前的白名单表数据（P3）
  ./scripts/prune.sh --help                   显示帮助

输出：
  对每张白名单表（user_events / user_teacher_views）输出：
    condition         实际 WHERE 子句（含真实时间字段名）
    matched_rows      命中行数
    oldest_created_at 命中行中最早时间戳
    newest_created_at 命中行中最新时间戳
    action            safe-to-delete-after-backup / nothing-to-prune / pruned

--confirm 前置条件（双重保护）：
  - 必须显式传 --days N（即便用默认 180 也得显式带）
  - 必须存在当天的 manual 备份：backups/bot.db.YYYYMMDD-*.manual.bak
    （先手工跑 ./scripts/backup.sh）
  - --confirm 与 --dry-run 互斥
  - 5 秒安全倒计时（可 Ctrl-C 中止）
  - 每表 BEGIN / DELETE / COMMIT；单表失败 ROLLBACK 不影响其它表
  - 完成后 PRAGMA integrity_check（!= ok 即 exit 2）
  - 写入 admin_audit_logs（action='prune_confirm', admin_id=0）

权益数据表永久禁止 prune（即使有人不慎扩展 WHITELIST_TABLES 也会被
程序级交集检查阻断）：point_transactions / reimbursements /
lottery_entries / teacher_reviews / admin_audit_logs / users /
teachers / favorites
EOF
}


# ============ 参数解析 ============
MODE=""
DAYS=""
DAYS_EXPLICIT=0          # --confirm 必须显式传 --days，记录是否被赋过值
DRY_RUN_SEEN=0
CONFIRM_SEEN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN_SEEN=1
            ;;
        --confirm)
            CONFIRM_SEEN=1
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
            DAYS_EXPLICIT=1
            ;;
        --days=*)
            v="${1#--days=}"
            if [[ ! "$v" =~ ^[0-9]+$ ]]; then
                err "--days 必须是非负整数，得到：$v"
                exit 1
            fi
            DAYS="$v"
            DAYS_EXPLICIT=1
            ;;
        --delete|--vacuum|--execute)
            err "无效参数：$1（仅支持 --dry-run / --confirm；详见 --help）"
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

# 互斥：--dry-run 与 --confirm 不能同传（防止歧义）
if [[ ${DRY_RUN_SEEN} -eq 1 && ${CONFIRM_SEEN} -eq 1 ]]; then
    err "--dry-run 与 --confirm 互斥，不能同时使用"
    exit 1
fi

# 确定 MODE
if [[ ${CONFIRM_SEEN} -eq 1 ]]; then
    MODE="confirm"
    # --confirm 必须显式传 --days N，强制运维重新输入而非依赖默认值
    if [[ ${DAYS_EXPLICIT} -ne 1 ]]; then
        err "--confirm 必须显式传 --days N（即便用默认 180，也得显式 --days 180）"
        err "用法：./scripts/prune.sh --confirm --days 180"
        exit 1
    fi
elif [[ ${DRY_RUN_SEEN} -eq 1 ]]; then
    MODE="dry-run"
    # dry-run 允许不传 --days，回退默认
    if [[ ${DAYS_EXPLICIT} -ne 1 ]]; then
        DAYS="${DEFAULT_DAYS}"
    fi
else
    err "必须显式传 --dry-run 或 --confirm"
    echo
    show_help
    exit 1
fi


# ============ 依赖检查 ============
if ! command -v sqlite3 >/dev/null 2>&1; then
    err "未找到 sqlite3 命令（apt install -y sqlite3）"
    exit 1
fi


# ============ PERMANENT_FORBIDDEN 交集检查（编程错误防护） ============
# 即便有人不慎把权益表加到 WHITELIST_TABLES，也在此处兜底阻断。
for whitelisted in "${WHITELIST_TABLES[@]}"; do
    for forbidden in "${PERMANENT_FORBIDDEN_TABLES[@]}"; do
        if [[ "${whitelisted}" == "${forbidden}" ]]; then
            err "编程错误：WHITELIST_TABLES 包含永久禁止表 '${whitelisted}'"
            err "权益表永久禁止 prune，详见 ROADMAP-PLAN.md §9.2"
            exit 1
        fi
    done
done


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


# ============ Mode banner + backup 检查（仅 confirm 路径） ============
if [[ "${MODE}" == "dry-run" ]]; then
    info "Dry-run only. No rows will be deleted."
else
    info "⚠️  CONFIRM MODE: rows matching the condition WILL be deleted."
    # 检查当天 manual 备份是否存在（§9.2 必须先 backup）
    TODAY_TS=$(date +%Y%m%d)
    if ! compgen -G "${BACKUP_DIR}/bot.db.${TODAY_TS}-*.manual.bak" >/dev/null 2>&1; then
        err "未发现今日 manual 备份 ${BACKUP_DIR}/bot.db.${TODAY_TS}-*.manual.bak"
        err "请先执行：./scripts/backup.sh"
        exit 1
    fi
    # 取最新一份当天备份（同日多次备份取最新）
    BACKUP_FILE=$(ls -1t "${BACKUP_DIR}"/bot.db.${TODAY_TS}-*.manual.bak 2>/dev/null | head -1 || true)
    if [[ -z "${BACKUP_FILE}" || ! -s "${BACKUP_FILE}" ]]; then
        err "当天 manual 备份不存在或为空"
        exit 1
    fi
    info "today's backup: ${BACKUP_FILE}"
fi
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


# ============ Dry-run summary（dry-run 路径在此结束） ============
if [[ "${MODE}" == "dry-run" ]]; then
    echo
    echo "Prune dry-run summary:"
    echo "- tables_checked: ${TABLES_CHECKED}"
    echo "- tables_skipped: ${TABLES_SKIPPED}"
    echo "- total_matched_rows: ${TOTAL_MATCHED}"
    echo "- days: ${DAYS}"
    echo "- mode: dry-run"
    exit 0
fi


# ============ Confirm: 5 秒安全倒计时 + 真实 DELETE ============
echo
echo "Prune confirm pre-flight:"
echo "- tables_checked: ${TABLES_CHECKED}"
echo "- tables_skipped: ${TABLES_SKIPPED}"
echo "- total_matched_rows: ${TOTAL_MATCHED}"
echo "- days: ${DAYS}"
echo "- mode: confirm"
echo

if [[ "${TOTAL_MATCHED}" -eq 0 ]]; then
    info "没有命中任何行，无需执行 DELETE。"
    exit 0
fi

# 5 秒安全倒计时（可 Ctrl-C 中止）
warn "${SAFETY_DELAY_SECONDS} 秒后开始真实删除... 按 Ctrl-C 立刻中止。"
for ((i=SAFETY_DELAY_SECONDS; i>0; i--)); do
    printf >&2 "  ... %d\n" "${i}"
    sleep 1
done


# 对每张表 BEGIN / DELETE / COMMIT；单表失败 ROLLBACK 不影响其它表
declare -a PRUNE_RESULT_LABELS=()
TOTAL_DELETED=0
TABLES_FAILED=0

for table in "${WHITELIST_TABLES[@]}"; do
    # 仅对前面 dry-run 通过校验的表执行（同 dry-run 跳过逻辑）
    if ! grep -Fxq "${table}" <<<"${existing_tables}"; then
        continue
    fi
    time_col=$(table_time_col "${table}")
    if [[ -z "${time_col}" ]]; then
        continue
    fi
    table_cols=$(sqlite3 "${DB_PATH}" "PRAGMA table_info(${table});" 2>/dev/null \
        | awk -F'|' '{print $2}' || true)
    if ! grep -Fxq "${time_col}" <<<"${table_cols}"; then
        continue
    fi

    condition="${time_col} < datetime('now', '-${DAYS} days')"

    info "Pruning table: ${table}"
    # 用 BEGIN / DELETE / COMMIT 包裹，单表失败 ROLLBACK
    set +e
    deleted=$(sqlite3 "${DB_PATH}" <<SQL 2>&1
BEGIN TRANSACTION;
DELETE FROM ${table} WHERE ${condition};
SELECT changes();
COMMIT;
SQL
    )
    rc=$?
    set -e

    if [[ ${rc} -ne 0 ]]; then
        err "  表 ${table} DELETE 失败（rc=${rc}）：${deleted}"
        # 尝试 ROLLBACK（即便事务可能已 abort）
        sqlite3 "${DB_PATH}" "ROLLBACK;" >/dev/null 2>&1 || true
        TABLES_FAILED=$((TABLES_FAILED + 1))
        PRUNE_RESULT_LABELS+=("${table}=FAILED")
        continue
    fi

    # changes() 输出在 deleted 字符串末尾；提取最后一个非空数字行
    deleted_count=$(echo "${deleted}" | grep -E '^[0-9]+$' | tail -1 || echo "0")
    if [[ -z "${deleted_count}" ]]; then
        deleted_count="0"
    fi
    echo "  deleted_rows: ${deleted_count}"
    TOTAL_DELETED=$((TOTAL_DELETED + deleted_count))
    PRUNE_RESULT_LABELS+=("${table}=${deleted_count}")
done


# ============ 完整性校验 ============
echo
info "执行 PRAGMA integrity_check..."
integrity_after=$(sqlite3 "${DB_PATH}" "PRAGMA integrity_check;" 2>/dev/null | head -1 || true)
if [[ "${integrity_after}" != "ok" ]]; then
    err "PRAGMA integrity_check 异常：${integrity_after}"
    err "数据库可能损坏！请立即从 backup 恢复：${BACKUP_FILE}"
    exit 2
fi
ok "PRAGMA integrity_check = ok"


# ============ 写入 admin_audit_logs ============
# admin_id=0 表示运维脚本（与 cron / 系统操作惯例一致）
# detail 用 JSON 字符串，包含 days / 各表删除数 / 总数 / backup 路径
detail_tables=""
for label in "${PRUNE_RESULT_LABELS[@]}"; do
    name="${label%%=*}"
    val="${label#*=}"
    if [[ -n "${detail_tables}" ]]; then
        detail_tables="${detail_tables}, "
    fi
    detail_tables="${detail_tables}\"${name}\": \"${val}\""
done

# JSON 转义 BACKUP_FILE 路径中的反斜杠 / 引号（安全起见）
backup_escaped=${BACKUP_FILE//\\/\\\\}
backup_escaped=${backup_escaped//\"/\\\"}

audit_detail="{\"days\": ${DAYS}, \"tables\": {${detail_tables}}, \"total_deleted\": ${TOTAL_DELETED}, \"tables_failed\": ${TABLES_FAILED}, \"backup\": \"${backup_escaped}\"}"

# SQL 字符串转义：单引号 → 两个单引号（提前在 bash 层算好，避免 heredoc 中的复杂转义）
sql_db_path=$(printf "%s" "${DB_PATH}" | sed "s/'/''/g")
sql_audit_detail=$(printf "%s" "${audit_detail}" | sed "s/'/''/g")

# 用 INSERT ... RETURNING id 拿到 audit log id（SQLite 3.35+；Debian 12 sqlite3 满足）
audit_id=$(sqlite3 "${DB_PATH}" <<SQL 2>/dev/null
INSERT INTO admin_audit_logs (admin_id, action, target_type, target_id, detail, created_at)
VALUES (0, 'prune_confirm', 'database', '${sql_db_path}',
        '${sql_audit_detail}', CURRENT_TIMESTAMP)
RETURNING id;
SQL
)
if [[ -z "${audit_id}" ]]; then
    warn "admin_audit_logs 写入未返回 id（可能 sqlite3 不支持 RETURNING）；继续运行"
    audit_id="?"
fi


# ============ Confirm summary ============
echo
echo "Prune confirm summary:"
echo "- tables_checked: ${TABLES_CHECKED}"
echo "- tables_skipped: ${TABLES_SKIPPED}"
echo "- tables_failed: ${TABLES_FAILED}"
echo "- total_deleted_rows: ${TOTAL_DELETED}"
echo "- per_table:"
for label in "${PRUNE_RESULT_LABELS[@]}"; do
    echo "    ${label}"
done
echo "- days: ${DAYS}"
echo "- backup: ${BACKUP_FILE}"
echo "- audit_log_id: ${audit_id}"
echo "- mode: confirm"
echo "- integrity_check: ok"

if [[ ${TABLES_FAILED} -gt 0 ]]; then
    warn "${TABLES_FAILED} 张表 DELETE 失败，详见上方 [ERR ] 日志"
    exit 1
fi
exit 0
