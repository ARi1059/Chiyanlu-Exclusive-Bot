#!/usr/bin/env bash
# Chiyanlu-Exclusive-Bot 磁盘告警脚本
#
# 用法：
#   ./scripts/disk_alert.sh [阈值百分比]      # 默认 85
#
# 说明：
#   - 检查根分区(/)使用率，超过阈值则 DM 超管（Telegram sendMessage）
#   - 只读 .env 里 BOT_TOKEN / SUPER_ADMIN_ID 两行的值，绝不打印 token
#   - 背景：2026-06-20 journald 日志把 4G 盘撑满 → SQLite 报 disk I/O error，
#     bot 查不出数据、形同"数据被清空"。本脚本在 100% 之前就提醒介入。
#
# 退出码：0 = 正常（无论是否触发告警 / Telegram 是否送达）
#         2 = 配置缺失或参数错误（cron 会据此报错）
#
# crontab（每 30 分钟一次，stdout/stderr 丢弃，告警走 Telegram）：
#   */30 * * * * /opt/Chiyanlu-Exclusive-Bot/scripts/disk_alert.sh >/dev/null 2>&1

set -euo pipefail

THRESHOLD="${1:-85}"
MOUNT="/"
PROJECT_DIR="/opt/Chiyanlu-Exclusive-Bot"
ENV_FILE="${PROJECT_DIR}/.env"

# 阈值必须是 1-99 的整数
if ! [[ "$THRESHOLD" =~ ^[0-9]+$ ]] || (( THRESHOLD < 1 || THRESHOLD > 99 )); then
    echo "[ERR] 阈值必须是 1-99 的整数，得到：$THRESHOLD" >&2
    exit 2
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "[ERR] 未找到 curl（apt install -y curl）" >&2
    exit 2
fi

if [[ ! -f "$ENV_FILE" ]]; then
    echo "[ERR] 找不到 .env：$ENV_FILE" >&2
    exit 2
fi

# 仅取指定 key 这一行的值：去掉前后空白、成对引号、Windows CR；绝不打印
_read_env() {
    local key="$1" line val
    line=$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$ENV_FILE" 2>/dev/null | head -1 || true)
    val="${line#*=}"
    val="${val%$'\r'}"
    val="${val#\"}"; val="${val%\"}"
    val="${val#\'}"; val="${val%\'}"
    # 去首尾空白
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    printf '%s' "$val"
}

BOT_TOKEN="$(_read_env BOT_TOKEN)"
SUPER_ADMIN_ID="$(_read_env SUPER_ADMIN_ID)"

if [[ -z "$BOT_TOKEN" || -z "$SUPER_ADMIN_ID" ]]; then
    echo "[ERR] .env 缺少 BOT_TOKEN 或 SUPER_ADMIN_ID" >&2
    exit 2
fi

# 当前使用率(整数%)与可用空间，一次 df 读出。-P 保证单行 POSIX 输出。
USE=""; AVAIL=""
read -r USE AVAIL < <(df -Ph "$MOUNT" | awk 'NR==2 {gsub(/%/,"",$5); print $5, $4}') || true

if ! [[ "$USE" =~ ^[0-9]+$ ]]; then
    echo "[ERR] 无法解析磁盘使用率：'$USE'" >&2
    exit 2
fi

if (( USE >= THRESHOLD )); then
    MSG="⚠️ 痴颜录 VPS 磁盘告警
根分区(${MOUNT}) 已用 ${USE}%（剩余 ${AVAIL}），阈值 ${THRESHOLD}%。

建议尽快清理：
  journalctl --vacuum-size=100M
  apt-get clean
（参考 2026-06-20 磁盘写满 → bot 假性\"数据丢失\"事故）"
    if curl -s -m 15 "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${SUPER_ADMIN_ID}" \
        --data-urlencode "text=${MSG}" >/dev/null; then
        echo "[ALERT] 磁盘 ${USE}% ≥ ${THRESHOLD}%，已 DM 超管"
    else
        echo "[ERR] 磁盘 ${USE}% ≥ ${THRESHOLD}%，但 Telegram 发送失败（网络/Token？）" >&2
    fi
else
    echo "[ OK ] 磁盘 ${USE}% < ${THRESHOLD}%"
fi
