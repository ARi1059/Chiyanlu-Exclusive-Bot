#!/usr/bin/env bash
# Chiyanlu-Exclusive-Bot 健康检查脚本
#
# 用法：
#   ./scripts/healthcheck.sh
#
# 说明：
#   - 只做只读检查，不修改任何业务数据
#   - 不输出 .env 内容，不输出 BOT_TOKEN
#   - 输出风格与 update.sh 一致：[ OK ] / [WARN] / [ERR ]
#   - 退出码：存在 ERR 项时 1，否则 0
#
# 适用：Debian 12 生产服务器、本地开发环境（macOS 等无 systemd 环境会降级为 WARN）

set -euo pipefail

# ============ 配置 ============
SERVICE_NAME="${SERVICE_NAME:-chiyanlu-bot}"
PYTHON_MIN_MAJOR=3
PYTHON_MIN_MINOR=11
JOURNAL_LINES=100
CORE_TABLES=(
    admins
    teachers
    users
    favorites
    checkins
    config
    teacher_reviews
    point_transactions
    reimbursements
    lotteries
)
# ==============================

# 颜色输出（保持与 update.sh 一致）
if [[ -t 1 ]]; then
    RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BLUE=$'\033[0;34m'; NC=$'\033[0m'
else
    RED=""; GREEN=""; YELLOW=""; BLUE=""; NC=""
fi

OK_COUNT=0
WARN_COUNT=0
ERR_COUNT=0

info() { echo "${BLUE}[INFO]${NC} $*"; }
ok()   { echo "${GREEN}[ OK ]${NC} $*"; OK_COUNT=$((OK_COUNT + 1)); }
warn() { echo "${YELLOW}[WARN]${NC} $*"; WARN_COUNT=$((WARN_COUNT + 1)); }
err()  { echo "${RED}[ERR ]${NC} $*" >&2; ERR_COUNT=$((ERR_COUNT + 1)); }
section() { echo; echo "===== $* ====="; }

# 解析项目根目录：脚本位于 <project>/scripts/healthcheck.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

info "项目根目录：${PROJECT_ROOT}"


# ============================================================
# 一、基础文件检查
# ============================================================
section "一、基础文件检查"

# 是否像项目根目录
if [[ -f "bot/main.py" && -f "requirements.txt" ]]; then
    ok "当前目录是项目根目录"
else
    err "当前目录不像 Chiyanlu-Exclusive-Bot 项目根目录（缺少 bot/main.py 或 requirements.txt）"
fi

# 关键源码
for f in bot/main.py bot/database.py requirements.txt; do
    if [[ -f "$f" ]]; then
        ok "存在 ${f}"
    else
        err "缺失 ${f}"
    fi
done

# .env 检查（绝不读取或打印内容）
if [[ -f ".env" ]]; then
    ok "存在 .env"
    # 权限检查；stat 在 GNU coreutils 与 macOS BSD coreutils 上参数不同
    env_perm=""
    if env_perm=$(stat -c %a .env 2>/dev/null); then
        :
    elif env_perm=$(stat -f %Lp .env 2>/dev/null); then
        :
    else
        env_perm=""
    fi

    if [[ -z "${env_perm}" ]]; then
        warn ".env 权限无法读取（stat 命令不可用？）"
    elif [[ "${env_perm}" == "600" ]]; then
        ok ".env 权限 600"
    else
        warn ".env 权限为 ${env_perm}，建议 chmod 600 .env"
    fi
else
    err "缺失 .env"
fi

# data / backups 目录
if [[ -d "data" ]]; then
    ok "存在 data/ 目录"
else
    err "缺失 data/ 目录"
fi

if [[ -d "backups" ]]; then
    ok "存在 backups/ 目录"
else
    warn "缺失 backups/ 目录（首次部署可能为空属正常，但建议预创建）"
fi


# ============================================================
# 二、Python 检查
# ============================================================
section "二、Python 检查"

if command -v python3 >/dev/null 2>&1; then
    py_version="$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || echo "unknown")"
    ok "python3 可用（版本 ${py_version}）"

    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (${PYTHON_MIN_MAJOR}, ${PYTHON_MIN_MINOR}) else 1)" 2>/dev/null; then
        ok "Python 版本 >= ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}"
    else
        err "Python 版本过低（要求 >= ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}，当前 ${py_version}）"
    fi
else
    err "未找到 python3"
fi

VENV_PY=".venv/bin/python"
if [[ -x "${VENV_PY}" ]]; then
    ok "${VENV_PY} 存在且可执行"

    if "${VENV_PY}" -m compileall -q bot >/dev/null 2>&1; then
        ok ".venv 编译 bot/ 通过（compileall -q bot）"
    else
        err ".venv 编译 bot/ 失败，存在语法错误（请运行 ${VENV_PY} -m compileall bot 查看详情）"
    fi
else
    err "${VENV_PY} 不存在或不可执行（虚拟环境未创建？）"
fi


# ============================================================
# 三、SQLite 检查
# ============================================================
section "三、SQLite 检查"

if command -v sqlite3 >/dev/null 2>&1; then
    ok "sqlite3 命令可用"
else
    err "未找到 sqlite3（WAL 模式下不可绕过：apt install -y sqlite3）"
fi

# 从 .env 读取 DATABASE_PATH，仅读取这一行的值，不输出 .env 其它内容
DB_PATH="data/bot.db"
if [[ -f ".env" ]]; then
    db_line=$(grep -E '^[[:space:]]*DATABASE_PATH[[:space:]]*=' .env 2>/dev/null | head -1 || true)
    if [[ -n "${db_line}" ]]; then
        raw="${db_line#*=}"
        raw="${raw#"${raw%%[![:space:]]*}"}"     # 去左空格
        raw="${raw%"${raw##*[![:space:]]}"}"     # 去右空格
        raw="${raw%\"}"; raw="${raw#\"}"         # 去双引号
        raw="${raw%\'}"; raw="${raw#\'}"         # 去单引号
        if [[ -n "${raw}" ]]; then
            DB_PATH="${raw}"
        fi
    fi
fi
info "DATABASE_PATH = ${DB_PATH}"

if [[ -f "${DB_PATH}" ]] && command -v sqlite3 >/dev/null 2>&1; then
    ok "数据库文件存在：${DB_PATH}"

    integrity=$(sqlite3 "${DB_PATH}" "PRAGMA integrity_check;" 2>/dev/null | head -1 || true)
    if [[ "${integrity}" == "ok" ]]; then
        ok "PRAGMA integrity_check = ok"
    else
        err "PRAGMA integrity_check 异常（返回值非 ok，请勿继续部署，立即升级开发者）"
    fi

    journal=$(sqlite3 "${DB_PATH}" "PRAGMA journal_mode;" 2>/dev/null | head -1 || true)
    if [[ "${journal}" == "wal" ]]; then
        ok "PRAGMA journal_mode = wal"
    else
        warn "PRAGMA journal_mode = '${journal}'（预期 wal）"
    fi

    # 核心表存在性
    existing_tables=$(sqlite3 "${DB_PATH}" "SELECT name FROM sqlite_master WHERE type='table';" 2>/dev/null || true)
    for t in "${CORE_TABLES[@]}"; do
        if grep -Fxq "$t" <<<"${existing_tables}"; then
            ok "存在核心表：${t}"
        else
            err "缺失核心表：${t}"
        fi
    done

    # reimbursements_new 残留表（迁移残留指示）
    if grep -Fxq "reimbursements_new" <<<"${existing_tables}"; then
        new_count=$(sqlite3 "${DB_PATH}" "SELECT COUNT(*) FROM reimbursements_new;" 2>/dev/null || echo "?")
        warn "存在 reimbursements_new 表（行数 ${new_count}），属于迁移残留，请按 docs/POLICY-reimbursement.md 处理"
    fi

    # schema_migrations 失败迁移检查（P2 baseline；表不存在视为旧库或未启动新版本 → WARN）
    # 仅统计数量，不打印 error 内容（避免日志冗长或潜在敏感信息）
    if grep -Fxq "schema_migrations" <<<"${existing_tables}"; then
        hard_failed=$(sqlite3 "${DB_PATH}" \
            "SELECT COUNT(*) FROM schema_migrations WHERE success = 0 AND kind = 'hard';" \
            2>/dev/null || echo "0")
        soft_failed=$(sqlite3 "${DB_PATH}" \
            "SELECT COUNT(*) FROM schema_migrations WHERE success = 0 AND kind = 'soft';" \
            2>/dev/null || echo "0")
        unknown_failed=$(sqlite3 "${DB_PATH}" \
            "SELECT COUNT(*) FROM schema_migrations WHERE success = 0 AND kind NOT IN ('soft','hard');" \
            2>/dev/null || echo "0")

        any_failed=0
        if [[ "${hard_failed}" -gt 0 ]]; then
            err "schema_migrations 存在 hard failed migration: ${hard_failed}"
            any_failed=1
        fi
        if [[ "${soft_failed}" -gt 0 ]]; then
            warn "schema_migrations 存在 soft failed migration: ${soft_failed}"
            any_failed=1
        fi
        if [[ "${unknown_failed}" -gt 0 ]]; then
            warn "schema_migrations 存在 unknown-kind failed migration: ${unknown_failed}"
            any_failed=1
        fi
        if [[ "${any_failed}" -eq 0 ]]; then
            total=$(sqlite3 "${DB_PATH}" "SELECT COUNT(*) FROM schema_migrations;" 2>/dev/null || echo "?")
            ok "schema_migrations 无失败迁移（共 ${total} 条记录）"
        fi
    else
        warn "schema_migrations 表不存在（旧库或尚未启动新版本，兼容口径）"
    fi
else
    if [[ ! -f "${DB_PATH}" ]]; then
        err "数据库文件不存在：${DB_PATH}"
    fi
fi


# ============================================================
# 四、systemd 检查
# ============================================================
section "四、systemd 检查"

has_systemctl=0
has_unit=0

if command -v systemctl >/dev/null 2>&1; then
    has_systemctl=1
    # 进一步确认 systemd 在跑（避免容器/macOS brew 装了 systemctl 但无法工作）
    if ! systemctl --version >/dev/null 2>&1; then
        has_systemctl=0
    fi
fi

if [[ "${has_systemctl}" -eq 0 ]]; then
    warn "未检测到可用的 systemctl（本地或非 systemd 环境跳过 systemd 检查）"
else
    if systemctl cat "${SERVICE_NAME}" >/dev/null 2>&1; then
        has_unit=1
        ok "service unit 存在：${SERVICE_NAME}"
    else
        warn "未找到 service unit：${SERVICE_NAME}（如未配置 systemd 部署可忽略）"
    fi

    if [[ "${has_unit}" -eq 1 ]]; then
        active_state=$(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || true)
        if [[ "${active_state}" == "active" ]]; then
            ok "${SERVICE_NAME} 当前 active (running)"
        else
            err "${SERVICE_NAME} 非 active（当前状态：${active_state:-unknown}）"
        fi

        # journalctl 关键字扫描（仅计数，不打印命中行内容以避免泄露）
        if command -v journalctl >/dev/null 2>&1; then
            recent_log=$(journalctl -u "${SERVICE_NAME}" -n "${JOURNAL_LINES}" --no-pager 2>/dev/null || true)
            if [[ -n "${recent_log}" ]]; then
                hits=0
                for kw in "Traceback" "CRITICAL" "database is locked" "migration failed" "迁移失败"; do
                    n=$(grep -c -- "${kw}" <<<"${recent_log}" || true)
                    if [[ "${n}" -gt 0 ]]; then
                        warn "最近 ${JOURNAL_LINES} 行日志含关键字 \"${kw}\" ×${n}（请用 journalctl -u ${SERVICE_NAME} -n ${JOURNAL_LINES} 自查）"
                        hits=$((hits + n))
                    fi
                done
                if [[ "${hits}" -eq 0 ]]; then
                    ok "最近 ${JOURNAL_LINES} 行日志未命中告警关键字"
                fi
            else
                warn "无法读取 ${SERVICE_NAME} 的 journalctl 日志（可能无权限或服务从未启动）"
            fi
        else
            warn "未找到 journalctl，跳过日志关键字扫描"
        fi
    fi
fi


# ============================================================
# 五、Git 检查
# ============================================================
section "五、Git 检查"

if command -v git >/dev/null 2>&1; then
    if git -C "${PROJECT_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        ok "项目目录是 Git 仓库"

        branch=$(git -C "${PROJECT_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
        commit=$(git -C "${PROJECT_ROOT}" rev-parse --short HEAD 2>/dev/null || echo "unknown")
        info "当前分支：${branch}（commit ${commit}）"

        dirty=$(git -C "${PROJECT_ROOT}" status --porcelain --untracked-files=no 2>/dev/null || true)
        if [[ -z "${dirty}" ]]; then
            ok "工作区干净（已跟踪文件无修改）"
        else
            dirty_lines=$(printf "%s\n" "${dirty}" | wc -l | tr -d ' ')
            warn "工作区存在 ${dirty_lines} 个已跟踪文件被修改，部署前请确认是否需要 stash/还原"
        fi
    else
        warn "项目目录不是 Git 仓库（如通过打包方式部署可忽略）"
    fi
else
    warn "未找到 git 命令"
fi


# ============================================================
# 六、输出总结
# ============================================================
section "六、总结"

echo "Healthcheck summary:"
echo "- OK: ${OK_COUNT}"
echo "- WARN: ${WARN_COUNT}"
echo "- ERR: ${ERR_COUNT}"

if [[ "${ERR_COUNT}" -gt 0 ]]; then
    err "存在 ${ERR_COUNT} 个失败项，请处理后再继续部署或视为事故。"
    exit 1
fi

if [[ "${WARN_COUNT}" -gt 0 ]]; then
    info "存在 ${WARN_COUNT} 个警告项，建议复核但不阻塞。"
fi

exit 0
