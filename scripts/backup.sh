#!/usr/bin/env bash
# Chiyanlu-Exclusive-Bot 独立数据库备份脚本
#
# 用法：
#   ./scripts/backup.sh                 # 默认保留最近 30 份 manual 备份
#   ./scripts/backup.sh --keep 10       # 仅保留最近 10 份 manual 备份
#   ./scripts/backup.sh --help          # 显示帮助
#
# 行为：
#   - 使用 sqlite3 .backup 做 WAL-safe 在线一致性快照（绝不 cp 主库）
#   - 备份完成后执行 PRAGMA integrity_check，返回 ok 才算成功
#   - 备份文件名：backups/bot.db.YYYYMMDD-HHMMSS.manual.bak
#   - 只清理 *.manual.bak，不动 update.sh 产生的 backups/bot.db.*.bak
#   - 不读取或输出 .env / BOT_TOKEN
#   - 任何失败：[ERR ] 并 exit 1
#
# 适用：Debian 12 生产服务器；可放入 crontab。

set -euo pipefail

# ============ 解析项目根 ============
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}"

# ============ 默认配置 ============
KEEP=30
BACKUP_DIR="${PROJECT_DIR}/backups"
DEFAULT_DB_PATH="data/bot.db"
# ==================================

# 颜色输出（与 update.sh / healthcheck.sh 风格一致）
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
  ./scripts/backup.sh                 默认保留最近 30 份 manual 备份
  ./scripts/backup.sh --keep N        保留最近 N 份 manual 备份（N 为非负整数）
  ./scripts/backup.sh --help          显示帮助

输出：
  备份成功时打印备份路径、文件大小、integrity_check=ok。
  备份文件位于 backups/bot.db.YYYYMMDD-HHMMSS.manual.bak。

注意：
  - 仅清理 *.manual.bak，不影响 update.sh 产生的 *.bak。
  - 必须使用 sqlite3 .backup；不允许 cp data/bot.db。
EOF
}


# ============ 参数解析 ============
while [[ $# -gt 0 ]]; do
    case "$1" in
        --keep)
            shift
            if [[ $# -eq 0 ]]; then
                err "--keep 需要一个非负整数参数"
                exit 1
            fi
            if [[ ! "$1" =~ ^[0-9]+$ ]]; then
                err "--keep 必须是非负整数，得到：$1"
                exit 1
            fi
            KEEP="$1"
            ;;
        --keep=*)
            v="${1#--keep=}"
            if [[ ! "$v" =~ ^[0-9]+$ ]]; then
                err "--keep 必须是非负整数，得到：$v"
                exit 1
            fi
            KEEP="$v"
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


# ============ 依赖检查 ============
if ! command -v sqlite3 >/dev/null 2>&1; then
    err "未找到 sqlite3 命令。WAL 模式下不可绕过：apt install -y sqlite3"
    exit 1
fi


# ============ 读取 DATABASE_PATH（不输出 .env 内容） ============
DB_PATH="${DEFAULT_DB_PATH}"
if [[ -f .env ]]; then
    # 只匹配以 DATABASE_PATH 开头的一行，绝不 cat 整文件
    db_line=$(grep -E '^[[:space:]]*DATABASE_PATH[[:space:]]*=' .env 2>/dev/null | tail -n 1 || true)
    if [[ -n "${db_line}" ]]; then
        raw="${db_line#*=}"
        # 去前后空白
        raw="${raw#"${raw%%[![:space:]]*}"}"
        raw="${raw%"${raw##*[![:space:]]}"}"
        # 去单/双引号
        raw="${raw%\"}"; raw="${raw#\"}"
        raw="${raw%\'}"; raw="${raw#\'}"
        if [[ -n "${raw}" ]]; then
            DB_PATH="${raw}"
        fi
    fi
fi

# 相对路径相对于项目根
if [[ "${DB_PATH}" != /* ]]; then
    DB_PATH="${PROJECT_DIR}/${DB_PATH}"
fi

if [[ ! -f "${DB_PATH}" ]]; then
    err "数据库文件不存在：${DB_PATH}"
    exit 1
fi


# ============ 执行备份 ============
mkdir -p "${BACKUP_DIR}"
TS=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/bot.db.${TS}.manual.bak"

info "数据库源：${DB_PATH}"
info "备份目标：${BACKUP_FILE}"
info "保留份数：${KEEP}（仅作用于 *.manual.bak）"

if ! sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"; then
    err "sqlite3 .backup 失败：${DB_PATH} -> ${BACKUP_FILE}"
    exit 1
fi

if [[ ! -s "${BACKUP_FILE}" ]]; then
    err "备份文件不存在或为空：${BACKUP_FILE}"
    exit 1
fi


# ============ 完整性校验 ============
INTEGRITY=$(sqlite3 "${BACKUP_FILE}" "PRAGMA integrity_check;" 2>&1 | head -1 || true)
if [[ "${INTEGRITY}" != "ok" ]]; then
    err "备份完整性校验失败：integrity_check 返回 '${INTEGRITY}'"
    err "可疑备份已保留以便排查：${BACKUP_FILE}"
    exit 1
fi

# integrity_check 用 sqlite3 客户端打开备份时会按 source 的 WAL 模式建出
# 伴随 -wal / -shm 文件；备份主文件本身已完整（.backup 已落盘），
# 删掉这两个伴随文件可保证 backups/ 目录干净、便于异地拷贝。
rm -f "${BACKUP_FILE}-wal" "${BACKUP_FILE}-shm"


# ============ 输出成功信息 ============
SIZE=$(stat -c%s "${BACKUP_FILE}" 2>/dev/null || stat -f%z "${BACKUP_FILE}" 2>/dev/null || echo "?")
ok "备份成功"
echo "  路径：${BACKUP_FILE}"
echo "  大小：${SIZE} bytes"
echo "  integrity_check=ok"


# ============ 清理旧 manual 备份（不动 update.sh 的 *.bak） ============
# 仅匹配 backups/bot.db.*.manual.bak，update.sh 产生的 bot.db.*.bak 不会被这条 glob 命中
if compgen -G "${BACKUP_DIR}/bot.db.*.manual.bak" >/dev/null; then
    # 按修改时间倒序，保留前 KEEP 份，剩下的删除
    to_delete=$(ls -1t "${BACKUP_DIR}"/bot.db.*.manual.bak 2>/dev/null | tail -n +$((KEEP + 1)) || true)
    if [[ -n "${to_delete}" ]]; then
        del_count=$(printf '%s\n' "${to_delete}" | wc -l | tr -d ' ')
        info "保留最近 ${KEEP} 份，清理 ${del_count} 份过期 manual 备份："
        printf '%s\n' "${to_delete}" | sed 's/^/  - /'
        # 同时清理对应的 -wal / -shm 伴随文件（如果存在）
        while IFS= read -r f; do
            [[ -z "$f" ]] && continue
            rm -f "$f" "${f}-wal" "${f}-shm"
        done <<<"${to_delete}"
    else
        info "manual 备份数量未超过 keep=${KEEP}，无需清理"
    fi
fi

exit 0
