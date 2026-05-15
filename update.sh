#!/usr/bin/env bash
# Chiyanlu-Exclusive-Bot 一键更新脚本
# 用法：cd /opt/Chiyanlu-Exclusive-Bot && bash update.sh

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

trap 'err "更新过程中出错，已中止（行 $LINENO）。请检查上方输出。"' ERR

# 1. 进入项目目录
if [[ ! -d "$PROJECT_DIR/.git" ]]; then
    err "项目目录不存在或不是 git 仓库：$PROJECT_DIR"
    exit 1
fi
cd "$PROJECT_DIR"
info "工作目录：$(pwd)"

# 2. 检查工作树是否干净
if [[ -n "$(git status --porcelain)" ]]; then
    warn "检测到本地有未提交修改："
    git status --short
    read -r -p "是否暂存(stash)这些改动后继续？[y/N] " yn
    case "$yn" in
        [Yy]*)
            git stash push -u -m "auto-stash before update $(date +%Y%m%d-%H%M%S)"
            ok "已暂存本地修改（git stash list 可查看）"
            ;;
        *)
            err "请先处理本地改动后再运行更新。"
            exit 1
            ;;
    esac
fi

# 3. 拉取远程并比较版本
info "拉取远程最新提交..."
git fetch --prune origin

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [[ "$LOCAL" == "$REMOTE" ]]; then
    ok "本地已是最新版本（$LOCAL），无需更新。"
    exit 0
fi

echo
info "将要应用的新提交："
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
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    info "停止服务 $SERVICE_NAME ..."
    systemctl stop "$SERVICE_NAME" || warn "停止服务失败，继续执行"
else
    warn "未找到 $SERVICE_NAME.service，跳过停止步骤"
fi

# 6. 拉取代码（使用 fast-forward，避免意外 merge）
info "更新代码到 origin/$BRANCH ..."
git pull --ff-only origin "$BRANCH"
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
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
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
