# Debian 12 VPS 部署文档

本文档说明如何在 **Debian 12 VPS** 上部署 `Chiyanlu-Exclusive-Bot`。

适用场景：

- 独立 VPS 长期运行
- `systemd` 守护进程
- SQLite 本地存储（已启用 WAL 模式）
- Telegram Bot 7x24 小时在线
- 使用项目自带的 `update.sh` 做更新、备份和回滚

> **关于运行用户：**
> 本文档**默认使用 root 用户**完成安装演示，便于新手按步骤执行。但**生产环境强烈建议**改用独立的 `chiyanlu` 系统用户运行 Bot（详见 [§9.2 推荐：非 root 用户运行](#92-推荐生产创建独立用户运行)）。root 部署只适合**测试或小规模个人使用**。

---

## 目录

1. [部署前准备](#1-部署前准备)
2. [登录 VPS](#2-登录-vps)
3. [系统环境准备](#3-系统环境准备)
4. [拉取项目代码](#4-拉取项目代码)
5. [创建虚拟环境并安装依赖](#5-创建虚拟环境并安装依赖)
6. [配置环境变量](#6-配置环境变量)
7. [创建数据目录](#7-创建数据目录)
8. [首次手动启动检查](#8-首次手动启动检查)
9. [配置 systemd 服务](#9-配置-systemd-服务)
10. [启动服务](#10-启动服务)
11. [日常维护：update.sh 推荐方式](#11-日常维护updatesh-推荐方式)
12. [配置完成后的管理步骤](#12-配置完成后的管理步骤)
13. [发布与签到工作方式](#13-发布与签到工作方式)
14. [备份与恢复](#14-备份与恢复)
15. [排错指南](#15-排错指南)
16. [验收 Checklist](#16-验收-checklist)
17. [推荐运维习惯](#17-推荐运维习惯)

---

## 1. 部署前准备

### 1.1 需要准备的信息

- Telegram Bot Token（BotFather 颁发）
- 超级管理员 Telegram 数字 ID
- 发布频道 ID
- 响应群组 ID（可在配置后补）
- 时区（一般 `Asia/Shanghai`）
- 每日自动发布时间（如 `14:00`）

### 1.2 Telegram 侧要求

- Bot 已创建完成
- Bot 已加入发布频道，**具备发送消息权限**
- 如需删除历史发布消息，Bot 需**删除消息权限**
- 如需在群组内响应关键词，Bot **已加入对应群组**
- 如需 Bot 读取群组普通消息，请在 BotFather 中**关闭隐私模式**

---

## 2. 登录 VPS

```bash
ssh root@你的服务器IP
whoami         # 应该返回 root
```

---

## 3. 系统环境准备

更新系统并安装基础依赖：

```bash
apt update
apt upgrade -y
apt install -y git python3 python3-venv python3-pip sqlite3
```

| 包 | 用途 |
|---|---|
| `git` | 克隆代码、`update.sh` 拉取更新 |
| `python3` / `python3-venv` / `python3-pip` | 运行 Bot |
| **`sqlite3`** | **必装**。`update.sh` 用它做 WAL-safe 备份（`sqlite3 .backup` + `PRAGMA integrity_check`）；缺失时 `update.sh` 会**硬失败拒绝继续**。|

可选工具（便于排错）：

```bash
apt install -y curl htop unzip nano
```

检查版本：

```bash
python3 --version           # 应 >= 3.11
sqlite3 --version           # 应 >= 3.34
```

Debian 12 默认 Python 是 3.11，可正常运行。

---

## 4. 拉取项目代码

```bash
mkdir -p /opt
cd /opt
git clone https://github.com/ARi1059/Chiyanlu-Exclusive-Bot.git
cd /opt/Chiyanlu-Exclusive-Bot
```

> **重要：** 后续更新代码请使用 `./update.sh`（见 [§11](#11-日常维护updatesh-推荐方式)），而不是直接 `git pull` 重启服务。

---

## 4.5 敏感文件与 `.gitignore` 注意事项

项目根目录已包含 `.gitignore`，覆盖以下敏感路径：

```
.env / .env.*                # 含 BOT_TOKEN，绝不能提交
data/                        # SQLite 主库 + WAL/SHM 副产物
backups/                     # update.sh 自动备份目录
*.db / *.sqlite / *.sqlite3
logs/ / *.log
.venv/ / venv/
```

⚠️ **铁律：**

- **`.env` 不可提交**：含 BOT_TOKEN，泄露后需立即去 BotFather `/revoke` 重新生成
- **`data/` 不可提交**：含全部生产数据
- **`backups/` 不可提交**：含历史数据快照
- 即使有 `.gitignore` 自动保护，**任何 commit 前请人工 `git status` 确认**

如果某次发现 `.env` 已被 commit（`git log --all -- .env` 有输出），**必须立即去 BotFather `/revoke` 重新生成 token**，然后改写 `.env` 并 force push 清历史（或重建仓库）。

---

## 5. 创建虚拟环境并安装依赖

```bash
cd /opt/Chiyanlu-Exclusive-Bot
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

语法自检：

```bash
python3 -m compileall bot
```

无报错即通过。

---

## 6. 配置环境变量

```bash
cp .env.example .env
nano .env
```

填入：

```env
BOT_TOKEN=1234567890:xxxxxxxxxxxxxxxxxxxxxxxxxxxx
SUPER_ADMIN_ID=123456789
DATABASE_PATH=./data/bot.db
TIMEZONE=Asia/Shanghai
PUBLISH_TIME=14:00
COOLDOWN_SECONDS=30
```

| 变量 | 说明 |
|---|---|
| `BOT_TOKEN` | Telegram Bot Token |
| `SUPER_ADMIN_ID` | 超级管理员 Telegram 数字 ID |
| `DATABASE_PATH` | SQLite 路径，默认 `./data/bot.db` |
| `TIMEZONE` | 时区，建议 `Asia/Shanghai` |
| `PUBLISH_TIME` | 每日自动发布时间，格式 `HH:MM` |
| `COOLDOWN_SECONDS` | 群组关键词响应冷却时间（秒） |

**收紧权限**（含 token，必须做）：

```bash
chmod 600 .env
ls -la .env       # 应显示 -rw-------
```

---

## 7. 创建数据目录

```bash
mkdir -p data backups
chmod 750 data backups
```

数据库文件会在首次启动时自动创建。WAL 模式下会出现 3 个文件：

```
data/bot.db          # 主库
data/bot.db-wal      # 预写日志
data/bot.db-shm      # 共享内存映射
```

---

## 8. 首次手动启动检查

建议先手动启动一次验证配置：

```bash
source .venv/bin/activate
python3 -m bot.main
```

启动成功表明：

- 配置读取正常
- 数据库初始化通过（含所有 `_migrate_*`）
- 已开始 Telegram 长轮询

在 Telegram 中给 Bot 发 `/start` 测试一下。完成后 `Ctrl+C` 停止，继续配置 systemd。

---

## 9. 配置 systemd 服务

有两种部署方案：

| 方案 | 适用 | 安全性 |
|---|---|---|
| **9.1 root 简易部署** | 测试 / 个人小规模 / VPS 只跑这一个 Bot | ⚠ token 泄露面大 |
| **9.2 chiyanlu 独立用户部署**（推荐） | 生产 / 长期运营 | ✅ 标准做法 |

### 9.1 root 简易部署

```bash
nano /etc/systemd/system/chiyanlu-bot.service
```

```ini
[Unit]
Description=Chiyanlu Exclusive Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/Chiyanlu-Exclusive-Bot
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/Chiyanlu-Exclusive-Bot/.venv/bin/python -m bot.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- 未指定 `User=` 默认以 root 运行
- 适合"测试 / 个人小规模"场景
- 生产环境请走 §9.2

### 9.2 推荐生产：创建独立用户运行

#### 9.2.1 创建系统用户

```bash
# 新建无登录权限的 chiyanlu 系统用户
useradd -r -s /usr/sbin/nologin -d /opt/Chiyanlu-Exclusive-Bot chiyanlu
```

#### 9.2.2 调整文件 / 目录所有权

```bash
cd /opt/Chiyanlu-Exclusive-Bot
chown -R chiyanlu:chiyanlu /opt/Chiyanlu-Exclusive-Bot
chmod 750 /opt/Chiyanlu-Exclusive-Bot
chmod 600 .env
chmod 750 data backups
```

权限要点：

- 项目目录 / `data/` / `backups/` 必须 chiyanlu **可读写**
- `.env` 必须 chiyanlu **可读**（`chmod 600` + `chown chiyanlu:chiyanlu`）
- `.venv/` 必须 chiyanlu **可执行**

#### 9.2.3 systemd 单元（含 User= / Group=）

```bash
nano /etc/systemd/system/chiyanlu-bot.service
```

```ini
[Unit]
Description=Chiyanlu Exclusive Telegram Bot
After=network.target

[Service]
Type=simple
User=chiyanlu
Group=chiyanlu
WorkingDirectory=/opt/Chiyanlu-Exclusive-Bot
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/Chiyanlu-Exclusive-Bot/.venv/bin/python -m bot.main
Restart=always
RestartSec=5

# 可选：systemd 内置隔离（按需开启，注意 update.sh 需写 backups/）
# NoNewPrivileges=true
# ProtectSystem=strict
# ReadWritePaths=/opt/Chiyanlu-Exclusive-Bot/data /opt/Chiyanlu-Exclusive-Bot/backups
# PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

#### 9.2.4 关于 update.sh 的权限

`update.sh` 当前需要这些操作权限：

- 读写 `/opt/Chiyanlu-Exclusive-Bot/`（`git pull --rebase`、`pip install`）
- 读写 `data/` 和 `backups/`（备份、还原）
- `systemctl start/stop/restart chiyanlu-bot`
- `journalctl -u chiyanlu-bot`（日志扫描）

两种可行做法：

- **运维以 root 跑 `update.sh`**（最简单，但执行更新会临时修改 chiyanlu 用户拥有的文件 —— 操作后请确认 `chown -R chiyanlu:chiyanlu /opt/Chiyanlu-Exclusive-Bot`）
- **给 chiyanlu 用户 sudo 白名单**：仅允许 `systemctl start/stop/restart chiyanlu-bot` 和 `journalctl -u chiyanlu-bot`，其它操作 chiyanlu 本身已具备权限

短期推荐第一种（root 跑 `update.sh`），简单且不会暴露 sudo 通道。

---

## 10. 启动服务

```bash
systemctl daemon-reload
systemctl enable chiyanlu-bot
systemctl start chiyanlu-bot
systemctl status chiyanlu-bot
journalctl -u chiyanlu-bot -f
```

服务正常时会看到 Bot 启动日志（含 `Bot 启动成功: @YourBotUsername`）。

---

## 11. 日常维护：update.sh 推荐方式

`update.sh`（项目根目录）是项目的统一运维入口，**强烈建议生产环境用它代替手工 `git pull` + `pip install` + `systemctl restart`**。

### 11.1 为什么不推荐手工流程

手工更新（已 **deprecated**）：

```bash
# ⚠️ 不推荐：缺备份、缺健康检查、缺迁移风险扫描、出错难回滚
cd /opt/Chiyanlu-Exclusive-Bot
git pull
source .venv/bin/activate
python3 -m pip install -r requirements.txt
systemctl restart chiyanlu-bot
```

问题：

- 没有备份 → 迁移失败无法回滚
- 没有 schema diff 预警 → 不知道这次更新动了哪些表
- 没有重启后健康检查 → 启动失败但没人发现
- 没有日志扫描 → `Traceback` / 迁移警告被淹没

### 11.2 推荐：使用 update.sh

```bash
cd /opt/Chiyanlu-Exclusive-Bot
./update.sh                 # 默认：完整更新流程
```

`update.sh` 完整流程会做：

1. **拉远程并比对版本**：`git fetch --prune origin` + 显示新提交清单
2. **schema diff 预警**：检测新提交是否引入 `_migrate_*` / `ALTER TABLE`，提前告知
3. **WAL-safe 数据库备份**：
   - 用 `sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"`（**绝不**用 cp）
   - 备份后做 `PRAGMA integrity_check;` —— 必须返回 `ok`
   - 自动保留最近 10 份（`KEEP_BACKUPS=10`）
4. **停服**：`systemctl stop chiyanlu-bot`
5. **rebase + autostash 拉代码**：兼容本地有未推送提交（如服务器侧 `.gitignore` 调整）；冲突时尝试用旧代码恢复服务
6. **同步依赖**：`pip install -r requirements.txt`
7. **语法自检**：`python3 -m compileall bot`
8. **启服 + 健康检查**：`systemctl start` 后 `is-active` 轮询 15s（覆盖大表迁移）
9. **日志扫描**：`journalctl --since "$START_TS"` 检查 `Traceback / CRITICAL / 迁移失败` 关键字
10. **总结**：显示新 HEAD + 异常引导回滚

### 11.3 子命令

| 命令 | 用途 |
|---|---|
| `./update.sh` 或 `./update.sh update` | 默认：完整更新流程 |
| `./update.sh start` | 仅启动服务（不更新代码） |
| `./update.sh stop` | 仅停止服务 |
| `./update.sh restart` | 仅重启服务（改 .env 后用，不更新代码） |
| `./update.sh status` | 显示服务状态 + 最近 20 行日志 |
| `./update.sh rollback` | 紧急回滚：还原最近一次备份 + `git reset --hard HEAD~1`（需 `yes` 确认） |
| `./update.sh help` | 帮助 |

### 11.4 紧急回滚

升级后发现异常，立即回滚：

```bash
./update.sh rollback
```

`update.sh rollback` 流程：

1. 找到 `backups/` 中最新的 `bot.db.*.bak`
2. 显示当前 HEAD 和将回滚到的 commit
3. **需要输入 `yes` 二次确认**
4. `systemctl stop chiyanlu-bot`
5. **删除残留 `data/bot.db-wal` / `data/bot.db-shm`**（关键，否则旧 WAL 会被 replay 到刚还原的主库）
6. `cp -p $latest_backup data/bot.db`
7. 还原后做 `PRAGMA integrity_check;` 校验
8. `git reset --hard HEAD~1`
9. `systemctl start chiyanlu-bot` + 健康检查

### 11.5 ⚠️ 不要手工覆盖主库

WAL 模式下**绝不要**手工 `cp 备份.db data/bot.db` —— 残留的 `-wal` / `-shm` 会污染恢复结果。如必须手工恢复，请严格按 §14.5 的步骤执行。

---

## 12. 配置完成后的管理步骤

Bot 启动后，超级管理员私聊：

- 发送 `/start` 或 `/admin`

在管理面板中依次：

1. 设置发布频道
2. 设置响应群组 / 讨论群
3. 设置必关订阅（如需要）
4. 添加老师
5. 添加其它管理员（如需要）
6. 检查系统状态
7. 用「发布预览」确认明日发布内容
8. 必要时用「手动发布」

---

## 13. 发布与签到工作方式

### 13.1 老师签到

老师私聊 Bot 发送：

```text
签到
```

Bot 会判断：老师是否已录入、是否启用、当前时间是否在签到截止前、当天是否已签到过。

### 13.2 每日自动发布

定时任务在 `PUBLISH_TIME`：

1. 删除前一天已发送的发布消息
2. 获取当天已签到老师
3. 生成带按钮的发布内容
4. 发送到配置好的发布频道

### 13.3 手动发布 / 发布预览

- 「手动发布」：立即把当天签到汇总发到发布频道
- 「发布预览」：仅在管理员私聊中展示，不发送到频道

---

## 14. 备份与恢复

项目使用 SQLite，自 2026-05-18 起启用 **WAL 模式**（`PRAGMA journal_mode=WAL`）。
WAL 模式下数据库由 3 个文件组成：

```text
/opt/Chiyanlu-Exclusive-Bot/data/bot.db       # 主库
/opt/Chiyanlu-Exclusive-Bot/data/bot.db-wal   # 预写日志（最近未 checkpoint 的写入）
/opt/Chiyanlu-Exclusive-Bot/data/bot.db-shm   # 共享内存映射
```

### 14.1 ⚠️ 不要直接 cp 主库

直接 `cp data/bot.db` **会丢掉仍在 `-wal` 里未 checkpoint 的最近写入**。表面上文件大小正常，但备份内容缺最新数据。**已发现**这是 WAL 模式下最常见的"假成功"陷阱。

### 14.2 ✅ 推荐：sqlite3 .backup（在线一致性快照）

`sqlite3 .backup` 命令在 SQLite 内部会自动把 WAL 内容合入备份文件，是 WAL 模式下唯一安全的在线备份方式：

```bash
mkdir -p /root/chiyanlu-backups
TS=$(date +%F-%H%M%S)
BACKUP=/root/chiyanlu-backups/bot-${TS}.db

# 1. 一致性备份（服务无需停机）
sqlite3 /opt/Chiyanlu-Exclusive-Bot/data/bot.db ".backup '$BACKUP'"

# 2. 完整性校验（必须返回 ok）
sqlite3 "$BACKUP" "PRAGMA integrity_check;"
```

### 14.3 自动备份首选 `update.sh`

`update.sh` 在 `update` / `rollback` 流程里已按这个模式做备份和校验。**只要使用 `update.sh` 做版本更新，每次更新前会自动产生一份带完整性校验的备份**。

但注意：`update.sh` 只在检测到**远程有新提交**的情况下才会备份；如果你只是做 `restart`、或者远程没有新提交而本地服务长时间运行，**它不会产生新备份**。

历史备份位于：

```text
/opt/Chiyanlu-Exclusive-Bot/backups/bot.db.YYYYMMDD-HHMMSS.bak              # update.sh 自动产生
/opt/Chiyanlu-Exclusive-Bot/backups/bot.db.YYYYMMDD-HHMMSS.manual.bak       # scripts/backup.sh 产生
```

`update.sh` 自动保留最近 10 份 `*.bak`（不含 `*.manual.bak`）。
`scripts/backup.sh` 默认保留最近 30 份 `*.manual.bak`，不会动 `update.sh` 的备份。
**`backups/` 目录已被 `.gitignore` 忽略**，不会进 git。当前不采用异地备份方案；如未来业务规模扩大，可另行评估。

### 14.4 日常手动备份 / 定时备份：`scripts/backup.sh`

项目自带 `scripts/backup.sh`，是独立于 `update.sh` 的备份脚本：
- 内部使用 `sqlite3 .backup`，WAL-safe，**绝不 cp 主库**
- 备份后强制执行 `PRAGMA integrity_check`，返回 `ok` 才算成功
- 备份文件命名 `backups/bot.db.YYYYMMDD-HHMMSS.manual.bak`，与 `update.sh` 的 `*.bak` 互不干扰
- 不会读取或输出 `.env` / `BOT_TOKEN`

**人工备份（重大操作前 / 排查异常前）：**

```bash
cd /opt/Chiyanlu-Exclusive-Bot
./scripts/backup.sh                 # 默认保留最近 30 份 manual 备份
./scripts/backup.sh --keep 10       # 仅保留最近 10 份
./scripts/backup.sh --help          # 查看帮助
```

成功时输出形如：

```text
[ OK ] 备份成功
  路径：/opt/Chiyanlu-Exclusive-Bot/backups/bot.db.20260518-033000.manual.bak
  大小：12345678 bytes
  integrity_check=ok
```

**crontab 定时备份：**

```bash
# 1. 准备日志目录（仅首次）
mkdir -p /opt/Chiyanlu-Exclusive-Bot/logs

# 2. 编辑 root（或运行用户）的 crontab
crontab -e
```

加入一行（每天凌晨 03:30 自动备份，保留最近 30 份）：

```cron
30 3 * * * cd /opt/Chiyanlu-Exclusive-Bot && ./scripts/backup.sh --keep 30 >> logs/backup.log 2>&1
```

> ⚠️ 仍然**不可** `cp /opt/Chiyanlu-Exclusive-Bot/data/bot.db` —— WAL 模式下会丢失 `-wal` 中未 checkpoint 的最近写入，
> 即使在 cron 里包装成"脚本"也一样。任何脚本里出现 `cp data/bot.db` 都属于错误用法。

### 14.5 手动还原（不推荐，但备查）

**首选 `./update.sh rollback`**（见 §11.4）。如必须手工还原：

```bash
# 0. 确认要恢复的备份文件
ls -lh /opt/Chiyanlu-Exclusive-Bot/backups/
# 或
ls -lh /root/chiyanlu-backups/

# 1. 停服（必须！）
systemctl stop chiyanlu-bot

# 2. 清掉残留 WAL/SHM（关键！否则旧 WAL 会被 replay 到刚还原的主库上）
rm -f /opt/Chiyanlu-Exclusive-Bot/data/bot.db-wal
rm -f /opt/Chiyanlu-Exclusive-Bot/data/bot.db-shm

# 3. 覆盖主库
cp /opt/Chiyanlu-Exclusive-Bot/backups/bot.db.20260518-143000.bak \
   /opt/Chiyanlu-Exclusive-Bot/data/bot.db

# 4. 校验
sqlite3 /opt/Chiyanlu-Exclusive-Bot/data/bot.db "PRAGMA integrity_check;"
# 期望返回：ok

# 5. 调整文件所有权（如果使用 chiyanlu 用户运行）
chown chiyanlu:chiyanlu /opt/Chiyanlu-Exclusive-Bot/data/bot.db

# 6. 起服
systemctl start chiyanlu-bot

# 7. 查日志确认
journalctl -u chiyanlu-bot -n 50 --no-pager
```

---

## 15. 排错指南

> 💡 **遇到任何异常先跑一次：**
> ```bash
> cd /opt/Chiyanlu-Exclusive-Bot
> ./scripts/healthcheck.sh
> ```
> 这个脚本是只读的，能在 1～2 秒内给出 Python、SQLite（WAL / integrity_check / 核心表）、
> systemd 状态、journalctl 关键字命中、Git 工作区是否干净的整体快照。
> 它不会输出 `.env` 内容、不会打印 BOT_TOKEN，也不会修改任何业务数据。
> 看 summary 的 ERR/WARN 项再对照下方小节定位问题，比盲查日志快很多。

### 15.1 服务无法启动

检查：

- `.env` 是否存在 + 权限是否 600
- `BOT_TOKEN` 是否正确（去 BotFather 复制）
- `SUPER_ADMIN_ID` 是否为纯数字
- 虚拟环境是否已创建 + `requirements.txt` 是否已安装
- `ExecStart` 路径是否正确
- 若用 `User=chiyanlu`，chiyanlu 是否对项目目录有权限

详细日志：

```bash
journalctl -u chiyanlu-bot -xe
journalctl -u chiyanlu-bot -n 200 --no-pager
```

### 15.2 无法收到群组关键词响应

- Bot 是否在群组内
- 群组是否已配置到后台（响应群组）
- BotFather 是否关闭了隐私模式
- 是否处于冷却时间内
- 关键词是否完全匹配老师艺名 / 地区 / 价格 / 标签

### 15.3 无法自动发布

- 发布频道是否已配置
- Bot 是否有频道发送权限
- 当天是否有老师签到（无签到默认跳过发布）
- `PUBLISH_TIME` 是否正确
- VPS 时区是否与 `TIMEZONE` 配置一致

### 15.4 数据库路径错误

- `data/` 目录存在 + 服务用户可读写
- `DATABASE_PATH` 配置正确
- 服务确实在 `WorkingDirectory` 目录下运行

### 15.5 `update.sh` 提示找不到 sqlite3

```text
[ERR ] 未找到 sqlite3 命令。WAL 模式下不能简单 cp 备份。
```

立即安装：

```bash
apt install -y sqlite3
```

WAL 模式下 sqlite3 是**强依赖**，不可绕过。

### 15.6 备份提示 `integrity_check` 失败

```text
[ERR ] 备份完整性校验失败：integrity_check 返回 '...'
```

这表明数据库本身已有损坏。**不要继续部署**，先：

1. `systemctl stop chiyanlu-bot`
2. 用之前一次成功的备份还原（§14.5）
3. 排查损坏原因（磁盘 / 异常断电 / 异常 kill）

### 15.7 git clone 权限错误

```text
fatal: could not create work tree dir 'Chiyanlu-Exclusive-Bot': Permission denied
```

当前用户没目标目录写权限。本文档使用 root，请确认：

```bash
whoami      # 应该是 root
```

---

## 16. 验收 Checklist

部署完成后，按顺序执行下列命令；全部正常即可视为部署完成。

```bash
# 0. 一键体检（推荐先跑）
cd /opt/Chiyanlu-Exclusive-Bot
./scripts/healthcheck.sh
# 期望：summary 显示 ERR=0；只读检查，覆盖文件 / .env 权限 / Python / .venv /
#       SQLite WAL & integrity_check / 核心表 / 数据库体积 / schema_migrations /
#       systemd / Git 工作区。
# 退出码：ERR=0 时返回 0，存在 ERR 时返回 1（适合放进 CI 或部署后脚本断言）
#
# DB 体积提醒默认阈值 512 MB；如生产数据量较大可调高：
#   HEALTHCHECK_DB_WARN_MB=1024 ./scripts/healthcheck.sh
# WAL 文件 > 100 MB 也会单独 WARN，但不会变成 ERR；绝不要手工删除 -wal/-shm。

# 0.5 单元测试（纯逻辑回归，不连真实 Telegram / 不访问真实数据库）
cd /opt/Chiyanlu-Exclusive-Bot
.venv/bin/python -m pytest
# 期望：全部通过（80+ 测试，1 秒内完成）
# 测试覆盖：parse_start_args / compute_reimbursement_amount /
#           group_search 工具函数 / 抽奖状态常量 / schema_migrations baseline
# 测试不会读取真实 .env、不会触碰 data/bot.db

# 0.6 历史数据 pruning · dry-run（评估日志规模，不删除任何数据）
./scripts/prune.sh --dry-run --days 180
# 期望：列出 user_events / user_teacher_views 命中行数；exit 0
# 当前版本严格只读，不支持 --confirm；任何危险参数都会 exit 1
# 详见 docs/PRUNING-DESIGN.md

# 1. 代码语法
cd /opt/Chiyanlu-Exclusive-Bot
python3 -m compileall bot
# 期望：无 SyntaxError 输出

# 2. 手动启动测试（前台跑一次再 Ctrl+C）
source .venv/bin/activate
python3 -m bot.main
# 期望：日志显示 "Bot 启动成功: @xxx"，Telegram 中 /start 有响应
deactivate

# 3. systemd 状态
systemctl status chiyanlu-bot
# 期望：Active: active (running)

# 4. 实时日志（确认无 ERROR / Traceback）
journalctl -u chiyanlu-bot -f
# Ctrl+C 退出

# 5. SQLite 是否处于 WAL 模式
sqlite3 /opt/Chiyanlu-Exclusive-Bot/data/bot.db "PRAGMA journal_mode;"
# 期望：wal

# 6. 数据库完整性
sqlite3 /opt/Chiyanlu-Exclusive-Bot/data/bot.db "PRAGMA integrity_check;"
# 期望：ok

# 7. WAL 文件是否存在（首次启动后应该出现）
ls -la /opt/Chiyanlu-Exclusive-Bot/data/
# 期望：bot.db + bot.db-wal + bot.db-shm

# 8. update.sh 健康检查（不更新代码）
cd /opt/Chiyanlu-Exclusive-Bot
./update.sh status
# 期望：显示 active (running) 和最近 20 行日志

# 9. 备份目录验证
# 注意：./update.sh restart 只重启服务，不会创建备份。
# 数据库备份只会在完整更新流程 ./update.sh 中、且检测到远程有新提交时执行（§13.3 第 4 步）。
# 如果当前没有远程新提交，./update.sh 会提前退出，也不会生成新备份。
# 因此首次部署刚完成时，backups/ 通常为空属于正常现象，需在真实更新后再次验证。
ls -lh /opt/Chiyanlu-Exclusive-Bot/backups/
# 期望：在「有远程新提交」的真实 ./update.sh 完整流程跑完后，
#       可看到 bot.db.YYYYMMDD-HHMMSS.bak 文件
# 目前项目尚未提供独立的 backup 子命令；
# 如需主动测试备份链路，可参考 §14.4 crontab 备份脚本，
# 或后续在 scripts/ 下补一个 backup.sh / update.sh backup 子命令
```

---

## 17. 推荐运维习惯

### 17.1 日常

- **使用 `update.sh` 而非手工 git pull**：每次更新都自动备份 + 健康检查 + 日志扫描
- **更新代码后先看 5 分钟日志**：`journalctl -u chiyanlu-bot -f`
- **每周检查 `backups/`**：确认备份在产，文件大小合理（不应为 0 或异常缩水）
- **定期 `apt update && apt upgrade`**：保持系统补丁

### 17.2 安全

- ⚠️ **不要将 `.env` 提交到 Git**（已在 `.gitignore` 中保护，但仍需注意）
- ⚠️ **不要在群里贴 `.env` 内容**
- ⚠️ **不要把 BOT_TOKEN 用在多个 Bot**
- ⚠️ **如发现 `.env` 曾被提交**：立即 BotFather `/revoke` 重新生成 token
- **生产环境用 chiyanlu 独立用户**（§9.2）而非 root

### 17.3 备份

- `update.sh` 已自动备份到 `backups/`，保留 10 份（WAL-safe `sqlite3 .backup` + `integrity_check`）
- `scripts/backup.sh` 可手动 / 定时（crontab）产生 `*.manual.bak`
- **不要把 `backups/` 进 Git**（已 `.gitignore`，但 `git add backups/` 会绕过 ignore，禁止）
- 当前不采用异地备份方案；如未来业务规模扩大，可另行评估

### 17.4 升级前

- 看本次拉取的 commit 是否含 `_migrate_*` 或 `ALTER TABLE`（`update.sh` 会自动提示）
- 涉及大 schema 改动时，**提前手工 `sqlite3 .backup` 多备一份到独立路径**

### 17.5 升级后

- 跟 5 分钟日志确认无异常
- 关键功能抽测（写评价 / 报销申请 / 抽奖参与 / 老师签到）
- 异常立即 `./update.sh rollback`

---

## 相关文档

- 项目总览：[README.md](../README.md)
- 设计文档：[DESIGN.md](DESIGN.md)（v1） / [FEATURES-v2.md](FEATURES-v2.md)（v2 增量）
