#!/usr/bin/env bash
# Chiyanlu-Exclusive-Bot 管理脚本
#
# 用法：
#   ./update.sh             完整更新（拉代码 + 装依赖 + 自检 + 重启服务）
#   ./update.sh start       仅启动服务（不更新代码）
#   ./update.sh stop        仅停止服务
#   ./update.sh restart     仅重启服务（不更新代码）
#   ./update.sh status      显示服务运行状态和最近日志
#   ./update.sh help        显示帮助

set -euo pipefail

# ============ 可按需修改的配置 ============
PROJECT_DIR="/opt/Chiyanlu-Exclusive-Bot"
SERVICE_NAME="chiyanlu-bot"
VENV_DIR=".venv"
BRANCH="main"
BACKUP_DIR="backups"
DB_PATH="data/bot.db"
KEEP_BACKUPS=10                          # 仅保留最近 N 份数据库备份
# =========================================

# 颜色输出
RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BLUE=$'\033[0;34m'; NC=$'\033[0m'
info()  { echo "${BLUE}[INFO]${NC} $*"; }
ok()    { echo "${GREEN}[ OK ]${NC} $*"; }
warn()  { echo "${YELLOW}[WARN]${NC} $*"; }
err()   { echo "${RED}[ERR ]${NC} $*" >&2; }

trap 'err "脚本执行出错（行 $LINENO）。请检查上方输出。"' ERR


# ============ 服务控制子命令 ============

_has_service_unit() {
    # systemctl cat 比 list-unit-files | grep 更稳：直接读取服务定义
    # 存在返回 0；不存在返回非 0 且不抛 stderr
    systemctl cat "$SERVICE_NAME" >/dev/null 2>&1
}

_check_service_unit() {
    if ! _has_service_unit; then
        err "未找到 systemd 服务单元：${SERVICE_NAME}.service"
        err "诊断命令："
        err "  systemctl cat $SERVICE_NAME"
        err "  systemctl list-unit-files | grep -i ${SERVICE_NAME%-*}"
        err "或在脚本顶部修改 SERVICE_NAME 变量"
        exit 1
    fi
}

cmd_start() {
    _check_service_unit
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        warn "服务已经在运行，跳过启动"
        systemctl --no-pager --lines=10 status "$SERVICE_NAME" || true
        return 0
    fi
    info "启动服务 $SERVICE_NAME ..."
    systemctl start "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "服务已启动并处于运行状态"
        systemctl --no-pager --lines=10 status "$SERVICE_NAME" || true
        info "查看实时日志：journalctl -u $SERVICE_NAME -f"
    else
        err "启动失败！请查看日志：journalctl -u $SERVICE_NAME -n 100 --no-pager"
        exit 1
    fi
}

cmd_stop() {
    _check_service_unit
    if ! systemctl is-active --quiet "$SERVICE_NAME"; then
        warn "服务已经处于停止状态"
        return 0
    fi
    info "停止服务 $SERVICE_NAME ..."
    systemctl stop "$SERVICE_NAME"
    ok "服务已停止"
}

cmd_restart() {
    _check_service_unit
    info "重启服务 $SERVICE_NAME ..."
    systemctl restart "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "服务已重启并处于运行状态"
        systemctl --no-pager --lines=10 status "$SERVICE_NAME" || true
    else
        err "重启失败！请查看日志：journalctl -u $SERVICE_NAME -n 100 --no-pager"
        exit 1
    fi
}

cmd_status() {
    _check_service_unit
    systemctl --no-pager --lines=20 status "$SERVICE_NAME" || true
}

cmd_help() {
    cat <<EOF
Chiyanlu-Exclusive-Bot 管理脚本

用法: $(basename "$0") [command]

命令:
  (空) / update    完整更新流程（拉代码 + 装依赖 + 自检 + 重启服务）
  start            仅启动服务（不更新代码）
  stop             仅停止服务
  restart          仅重启服务（不更新代码）
  status           显示服务运行状态和最近日志
  help             显示此帮助

示例:
  $(basename "$0")           # 拉新代码并部署
  $(basename "$0") start     # 服务挂了，直接拉起
  $(basename "$0") restart   # 改了 .env 后只重启不更新
EOF
}


# ============ 命令分发 ============

COMMAND="${1:-update}"

case "$COMMAND" in
    start)             cmd_start;   exit 0 ;;
    stop)              cmd_stop;    exit 0 ;;
    restart)           cmd_restart; exit 0 ;;
    status)            cmd_status;  exit 0 ;;
    help|-h|--help)    cmd_help;    exit 0 ;;
    update|"")         ;;  # 继续往下走完整更新流程
    *)
        err "未知命令: $COMMAND"
        echo
        cmd_help
        exit 1
        ;;
esac


# ============ 完整更新流程 ============

# 1. 进入项目目录
if [[ ! -d "$PROJECT_DIR/.git" ]]; then
    err "项目目录不存在或不是 git 仓库：$PROJECT_DIR"
    exit 1
fi
cd "$PROJECT_DIR"
info "工作目录：$(pwd)"

# 2. 检查工作树（只看已跟踪文件；未跟踪文件假设已在 .gitignore 中）
TRACKED_DIRTY=$(git status --porcelain --untracked-files=no)
if [[ -n "$TRACKED_DIRTY" ]]; then
    warn "检测到已跟踪文件有未提交改动："
    echo "$TRACKED_DIRTY"
    warn "rebase 时会自动 autostash 暂存并在拉取后恢复。"
    warn "如不放心，按 Ctrl+C 中止后手动 git commit / git stash。3 秒后继续..."
    sleep 3
fi

# 3. 拉取远程并比较版本
info "拉取远程最新提交..."
git fetch --prune origin

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

# 用 rev-list 计算远程领先的提交数（兼容"本地有未推送提交"导致 HEAD!=REMOTE 的场景）
NEW_REMOTE_COUNT=$(git rev-list --count "$LOCAL..$REMOTE" 2>/dev/null || echo 0)
if [[ "$NEW_REMOTE_COUNT" -eq 0 ]]; then
    ok "远程没有新提交（当前 HEAD: ${LOCAL:0:7}），无需更新。"
    exit 0
fi

# 顺便提示本地是否有未推送提交（如 .gitignore 调整）
LOCAL_AHEAD=$(git rev-list --count "$REMOTE..$LOCAL" 2>/dev/null || echo 0)
if [[ "$LOCAL_AHEAD" -gt 0 ]]; then
    info "本地有 $LOCAL_AHEAD 个未推送提交，rebase 时会被垫到远程之上"
fi

echo
info "将要应用的 $NEW_REMOTE_COUNT 条新提交："
git --no-pager log --oneline --no-decorate "$LOCAL..$REMOTE"
echo

# 4. 备份数据库
if [[ -f "$DB_PATH" ]]; then
    mkdir -p "$BACKUP_DIR"
    TS=$(date +%Y%m%d-%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/bot.db.${TS}.bak"
    cp -p "$DB_PATH" "$BACKUP_FILE"
    ok "数据库已备份至 $BACKUP_FILE"
    # 清理旧备份
    ls -1t "$BACKUP_DIR"/bot.db.*.bak 2>/dev/null | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm -f
else
    warn "未发现数据库文件 $DB_PATH，跳过备份。"
fi

# 5. 停止服务
if _has_service_unit; then
    info "停止服务 $SERVICE_NAME ..."
    systemctl stop "$SERVICE_NAME" || warn "停止服务失败，继续执行"
else
    warn "未找到 $SERVICE_NAME.service，跳过停止步骤"
fi

# 6. 拉取代码（rebase + autostash 模式）
#   - 兼容本地有未推送提交（如服务器 .gitignore 调整）
#   - autostash 自动暂存工作树未提交改动并在 rebase 后恢复
#   - 不再使用 --ff-only，避免分叉时阻塞更新
info "更新代码到 origin/$BRANCH（rebase + autostash）..."
if ! git pull --rebase --autostash origin "$BRANCH"; then
    err "git pull --rebase 失败（可能有冲突）"
    # 清理半成品状态
    git rebase --abort 2>/dev/null || true
    git stash pop 2>/dev/null || true
    # 尝试用旧代码恢复服务，避免 bot 长时间宕机
    if systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then
        warn "正在用旧代码恢复服务以避免长时间宕机..."
        systemctl start "$SERVICE_NAME" 2>/dev/null || true
    fi
    err "请手动处理后重试：cd $PROJECT_DIR && git status && git log --oneline -5"
    exit 1
fi
NEW_HEAD=$(git rev-parse --short HEAD)
ok "代码已更新到 $NEW_HEAD"

# 7. 更新依赖
if [[ ! -d "$VENV_DIR" ]]; then
    warn "未找到虚拟环境 $VENV_DIR，正在创建..."
    python3 -m venv "$VENV_DIR"
fi

info "同步 Python 依赖..."
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python3 -m pip install --upgrade pip >/dev/null
python3 -m pip install -r requirements.txt
deactivate
ok "依赖同步完成"

# 8. 语法自检
info "执行语法检查..."
"$VENV_DIR/bin/python3" -m compileall -q bot
ok "语法检查通过"

# 9. 启动服务
if _has_service_unit; then
    info "启动服务 $SERVICE_NAME ..."
    systemctl start "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "服务已启动并处于运行状态"
        systemctl --no-pager --lines=10 status "$SERVICE_NAME" || true
    else
        err "服务启动失败！请查看日志：journalctl -u $SERVICE_NAME -n 100 --no-pager"
        exit 1
    fi
else
    warn "未配置 systemd 服务，请手动启动：source $VENV_DIR/bin/activate && python3 -m bot.main"
fi

echo
ok "更新完成。当前版本：$(git --no-pager log -1 --pretty=format:'%h %s')"
info "查看实时日志：journalctl -u $SERVICE_NAME -f"
