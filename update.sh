#!/usr/bin/env bash
# Chiyanlu-Exclusive-Bot 管理脚本
#
# 用法：
#   ./update.sh             完整更新（拉代码 + 装依赖 + 自检 + 重启服务）
#   ./update.sh start       仅启动服务（不更新代码）
#   ./update.sh stop        仅停止服务
#   ./update.sh restart     仅重启服务（不更新代码）
#   ./update.sh status      显示服务运行状态和最近日志
#   ./update.sh rollback    回滚到上一个 commit + 还原最近一份 DB 备份
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
HEALTHCHECK_TIMEOUT=15                   # 启动后健康检查最长等待秒数（覆盖大表重建迁移）
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

# 启动后健康检查：每秒轮询 is-active，最多等 HEALTHCHECK_TIMEOUT 秒
# 用法：_wait_service_active && echo OK || echo FAIL
_wait_service_active() {
    local i=0
    while [[ $i -lt "$HEALTHCHECK_TIMEOUT" ]]; do
        if systemctl is-active --quiet "$SERVICE_NAME"; then
            # 多等 1 秒确认稳定（避免启动瞬间 active 但 init_db 还在跑就卡死）
            sleep 1
            if systemctl is-active --quiet "$SERVICE_NAME"; then
                return 0
            fi
        fi
        sleep 1
        i=$((i + 1))
    done
    return 1
}

# 扫描启动后日志中的迁移失败 / 致命错误关键字
# 返回 0 = 干净；返回 1 = 检出问题（已打印警告）
_scan_post_start_logs() {
    local since="$1"  # systemctl 时间戳，如 "2 minutes ago"
    local log_output
    if ! log_output=$(journalctl -u "$SERVICE_NAME" --since "$since" --no-pager 2>/dev/null); then
        warn "无法读取 journalctl，跳过日志扫描"
        return 0
    fi

    local issues=0

    # 迁移失败警告（database.py 里的 logger.warning("xxx 迁移失败...")）
    local migration_warns
    migration_warns=$(echo "$log_output" | grep -iE "迁移失败|migration.*fail" || true)
    if [[ -n "$migration_warns" ]]; then
        warn "发现迁移警告："
        echo "$migration_warns" | sed 's/^/    /'
        issues=$((issues + 1))
    fi

    # 致命错误堆栈
    local errors
    errors=$(echo "$log_output" | grep -iE "Traceback|CRITICAL|FATAL" | head -20 || true)
    if [[ -n "$errors" ]]; then
        warn "发现错误堆栈/严重日志："
        echo "$errors" | sed 's/^/    /'
        issues=$((issues + 1))
    fi

    # 报销表重建的预期日志（信息，不是错误）
    if echo "$log_output" | grep -q "reimbursements 表已扩展 CHECK"; then
        info "✓ reimbursements 表重建迁移已执行（CHECK 扩展接受 'queued'）"
    fi

    return $((issues > 0 ? 1 : 0))
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
    info "等待服务进入 active 状态（最长 ${HEALTHCHECK_TIMEOUT}s）..."
    if _wait_service_active; then
        ok "服务已启动并处于运行状态"
        systemctl --no-pager --lines=10 status "$SERVICE_NAME" || true
        info "查看实时日志：journalctl -u $SERVICE_NAME -f"
    else
        err "启动失败或超时！请查看日志：journalctl -u $SERVICE_NAME -n 100 --no-pager"
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
    info "等待服务进入 active 状态（最长 ${HEALTHCHECK_TIMEOUT}s）..."
    if _wait_service_active; then
        ok "服务已重启并处于运行状态"
        systemctl --no-pager --lines=10 status "$SERVICE_NAME" || true
    else
        err "重启失败或超时！请查看日志：journalctl -u $SERVICE_NAME -n 100 --no-pager"
        exit 1
    fi
}

cmd_status() {
    _check_service_unit
    systemctl --no-pager --lines=20 status "$SERVICE_NAME" || true
}

cmd_rollback() {
    cd "$PROJECT_DIR"
    info "工作目录：$(pwd)"

    # 1. 找到最近一份 DB 备份
    if [[ ! -d "$BACKUP_DIR" ]]; then
        err "备份目录不存在：$BACKUP_DIR"
        exit 1
    fi
    local latest_backup
    latest_backup=$(ls -1t "$BACKUP_DIR"/bot.db.*.bak 2>/dev/null | head -n 1 || true)
    if [[ -z "$latest_backup" ]]; then
        err "未找到任何 DB 备份（$BACKUP_DIR/bot.db.*.bak）"
        exit 1
    fi
    info "将使用 DB 备份：$latest_backup（$(stat -c %y "$latest_backup" 2>/dev/null || stat -f %Sm "$latest_backup"))"

    # 2. 显示 git 当前位置
    local current_head
    current_head=$(git --no-pager log -1 --pretty=format:'%h %s')
    info "当前 HEAD：$current_head"
    info "上一个 commit 将作为回滚目标："
    git --no-pager log -2 --oneline --no-decorate | tail -n 1 | sed 's/^/    /'

    echo
    warn "⚠️  rollback 将执行："
    warn "  - systemctl stop $SERVICE_NAME"
    warn "  - cp $latest_backup -> $DB_PATH （覆盖当前 DB）"
    warn "  - git reset --hard HEAD~1"
    warn "  - systemctl start $SERVICE_NAME"
    read -p "确认继续？输入 yes 回车，其它任何输入中止：" confirm
    if [[ "$confirm" != "yes" ]]; then
        warn "已中止"
        exit 0
    fi

    # 3. 停服
    if _has_service_unit; then
        info "停止服务..."
        systemctl stop "$SERVICE_NAME" || warn "停止服务失败，继续"
    fi

    # 4. 还原 DB
    info "还原数据库..."
    cp -p "$latest_backup" "$DB_PATH"
    ok "DB 已还原"

    # 5. git 回退
    info "git reset --hard HEAD~1..."
    git reset --hard HEAD~1
    local new_head
    new_head=$(git --no-pager log -1 --pretty=format:'%h %s')
    ok "代码已回退到：$new_head"

    # 6. 启动
    if _has_service_unit; then
        info "启动服务..."
        systemctl start "$SERVICE_NAME"
        if _wait_service_active; then
            ok "回滚后服务已正常启动"
            systemctl --no-pager --lines=10 status "$SERVICE_NAME" || true
        else
            err "回滚后服务启动失败！请检查日志：journalctl -u $SERVICE_NAME -n 100 --no-pager"
            exit 1
        fi
    fi
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
  rollback         回退到上一个 commit + 还原最近一份 DB 备份（需 yes 确认）
  help             显示此帮助

示例:
  $(basename "$0")           # 拉新代码并部署
  $(basename "$0") start     # 服务挂了，直接拉起
  $(basename "$0") restart   # 改了 .env 后只重启不更新
  $(basename "$0") rollback  # 升级失败紧急回滚
EOF
}


# ============ 命令分发 ============

COMMAND="${1:-update}"

case "$COMMAND" in
    start)             cmd_start;    exit 0 ;;
    stop)              cmd_stop;     exit 0 ;;
    restart)           cmd_restart;  exit 0 ;;
    status)            cmd_status;   exit 0 ;;
    rollback)          cmd_rollback; exit 0 ;;
    help|-h|--help)    cmd_help;     exit 0 ;;
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

# 3.5 扫描新代码包含的 DB 迁移函数，提示潜在风险
# 检测远程新提交是否引入 / 修改 _migrate_* 或 reimbursements/lotteries DDL
MIGRATIONS_TOUCHED=$(git diff --name-only "$LOCAL..$REMOTE" -- bot/database.py 2>/dev/null || true)
if [[ -n "$MIGRATIONS_TOUCHED" ]]; then
    # 看 diff 里有没有重建表 / ALTER TABLE 关键字
    RISKY_MIGRATIONS=$(git diff "$LOCAL..$REMOTE" -- bot/database.py 2>/dev/null \
        | grep -E "^\+.*(_migrate_|ALTER TABLE|CREATE TABLE.*_new|DROP TABLE)" | head -20 || true)
    if [[ -n "$RISKY_MIGRATIONS" ]]; then
        warn "本次更新涉及 DB schema 变化（init_db 自动迁移）："
        echo "$RISKY_MIGRATIONS" | sed 's/^/    /'
        warn "已下方第 4 步备份数据库；如启动失败可用 './update.sh rollback' 回滚。"
        echo
    fi
fi

# 4. 备份数据库（含完整性校验）
if [[ -f "$DB_PATH" ]]; then
    mkdir -p "$BACKUP_DIR"
    TS=$(date +%Y%m%d-%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/bot.db.${TS}.bak"
    cp -p "$DB_PATH" "$BACKUP_FILE"
    # 校验：备份文件存在 + 大小一致
    if [[ ! -s "$BACKUP_FILE" ]]; then
        err "备份失败：$BACKUP_FILE 不存在或为空"
        exit 1
    fi
    ORIG_SIZE=$(stat -c%s "$DB_PATH" 2>/dev/null || stat -f%z "$DB_PATH")
    BACKUP_SIZE=$(stat -c%s "$BACKUP_FILE" 2>/dev/null || stat -f%z "$BACKUP_FILE")
    if [[ "$ORIG_SIZE" != "$BACKUP_SIZE" ]]; then
        err "备份完整性校验失败：原 $ORIG_SIZE bytes，备份 $BACKUP_SIZE bytes"
        exit 1
    fi
    ok "数据库已备份至 $BACKUP_FILE（${BACKUP_SIZE} bytes）"
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

# 9. 启动服务（含健康检查 + 迁移日志扫描）
if _has_service_unit; then
    info "启动服务 $SERVICE_NAME ..."
    START_TS=$(date '+%Y-%m-%d %H:%M:%S')
    systemctl start "$SERVICE_NAME"
    info "等待服务进入 active 状态（最长 ${HEALTHCHECK_TIMEOUT}s，覆盖大表迁移）..."
    if _wait_service_active; then
        ok "服务已启动并处于运行状态"
        systemctl --no-pager --lines=10 status "$SERVICE_NAME" || true
        echo
        # 扫描启动后日志，检测迁移失败 / 错误堆栈
        info "扫描启动后日志中的迁移警告..."
        if _scan_post_start_logs "$START_TS"; then
            ok "日志扫描未发现异常"
        else
            err "日志中检出迁移警告或错误堆栈！"
            err "建议操作："
            err "  1) journalctl -u $SERVICE_NAME -n 200 --no-pager  # 详查日志"
            err "  2) ./update.sh rollback                            # 紧急回滚"
            exit 1
        fi
    else
        err "服务启动失败或 ${HEALTHCHECK_TIMEOUT}s 内未进入 active 状态！"
        err "诊断："
        err "  journalctl -u $SERVICE_NAME -n 100 --no-pager"
        err "紧急回滚："
        err "  ./update.sh rollback"
        exit 1
    fi
else
    warn "未配置 systemd 服务，请手动启动：source $VENV_DIR/bin/activate && python3 -m bot.main"
fi

echo
ok "更新完成。当前版本：$(git --no-pager log -1 --pretty=format:'%h %s')"
info "查看实时日志：journalctl -u $SERVICE_NAME -f"
info "如发现异常可立即回滚：./update.sh rollback"
