# Debian 12 VPS 部署文档

本文档说明如何在 **Debian 12 VPS** 上使用 **root 用户** 部署 `Chiyanlu-Exclusive-Bot`。

适用场景：

- 独立 VPS 长期运行
- 使用 `root` 用户完成安装、运行和维护
- 使用 `systemd` 守护进程
- SQLite 本地存储
- Telegram Bot 7x24 小时在线

> 说明：生产环境更推荐创建独立运行用户，但如果 VPS 仅用于运行该 Bot，也可以按本文档使用 root 用户直接部署。

---

## 1. 部署前准备

### 1.1 需要准备的信息

部署前请先准备好以下内容：

- Telegram Bot Token
- 超级管理员 Telegram 数字 ID
- 发布频道 ID
- 响应群组 ID
- 目标时区，例如 `Asia/Shanghai`
- 每日自动发布时间，例如 `14:00`

### 1.2 Telegram 侧要求

请确认以下权限已经配置好：

- Bot 已创建完成
- Bot 已加入发布频道，并具备发送消息权限
- 如果需要删除历史发布消息，Bot 还需要具备删除消息权限
- 如果需要在群组中响应关键词，Bot 已加入对应群组
- 如需让 Bot 读取群组普通消息，请在 BotFather 中关闭隐私模式

---

## 2. 登录 VPS

使用 root 用户登录 VPS：

```bash
ssh root@你的服务器IP
```

确认当前用户是 root：

```bash
whoami
```

如果输出为：

```text
root
```

说明可以继续部署。

---

## 3. 系统环境准备

登录 VPS 后，先更新系统并安装基础依赖。

```bash
apt update
apt upgrade -y
apt install -y git python3 python3-venv python3-pip
```

可选工具：

```bash
apt install -y curl htop unzip nano
```

检查 Python 和 pip：

```bash
python3 --version
python3 -m pip --version
```

Debian 12 默认 Python 通常为 3.11，可以正常运行本项目。如果你的服务器输出的是 Python 3.9，请先更新系统或安装 Python 3.11 后再继续。

注意：`python3-pip` 是 Debian 的软件包名，不是命令。不要直接执行 `python3-pip`。

---

## 4. 拉取项目代码

建议将项目放在 `/opt` 下管理。

```bash
mkdir -p /opt
cd /opt
```

克隆项目：

```bash
git clone https://github.com/ARi1059/Chiyanlu-Exclusive-Bot.git
```

进入项目目录：

```bash
cd /opt/Chiyanlu-Exclusive-Bot
```

如果项目已经存在，后续更新代码使用：

```bash
cd /opt/Chiyanlu-Exclusive-Bot
git pull
```

---

## 5. 创建虚拟环境并安装依赖

在项目目录下创建 Python 虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

安装完成后可以确认 Python 依赖是否正常：

```bash
python3 -m compileall bot
```

如果没有报错，说明代码基础语法检查通过。

---

## 6. 配置环境变量

复制示例配置文件：

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
nano .env
```

推荐配置示例：

```env
BOT_TOKEN=1234567890:xxxxxxxxxxxxxxxxxxxxxxxxxxxx
SUPER_ADMIN_ID=123456789
DATABASE_PATH=./data/bot.db
TIMEZONE=Asia/Shanghai
PUBLISH_TIME=14:00
COOLDOWN_SECONDS=30
```

### 参数说明

| 变量 | 说明 |
| --- | --- |
| `BOT_TOKEN` | Telegram Bot Token |
| `SUPER_ADMIN_ID` | 超级管理员的 Telegram 数字 ID |
| `DATABASE_PATH` | SQLite 数据库路径，默认 `./data/bot.db` |
| `TIMEZONE` | 时区，建议 `Asia/Shanghai` |
| `PUBLISH_TIME` | 每日自动发布时间，格式 `HH:MM` |
| `COOLDOWN_SECONDS` | 群组关键词响应冷却时间，单位秒 |

保存后可以查看确认文件存在：

```bash
ls -la .env
```

---

## 7. 创建数据目录

SQLite 数据库文件默认放在 `data/` 目录下，确保该目录存在。

```bash
mkdir -p data
chmod 755 data
```

数据库文件会在首次启动时自动创建。

---

## 8. 首次手动启动检查

建议先手动启动一次，确认配置无误。

```bash
source .venv/bin/activate
python3 -m bot.main
```

如果启动成功，说明以下内容已正常：

- 配置文件读取成功
- 数据库初始化成功
- 机器人开始轮询 Telegram

启动成功后，可以在 Telegram 中给 Bot 发送 `/start` 测试。

测试完成后，在终端按 `Ctrl+C` 停止，再继续配置 `systemd`。

---

## 9. 配置 systemd 服务

创建服务文件：

```bash
nano /etc/systemd/system/chiyanlu-bot.service
```

写入以下内容：

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

### 说明

- 该服务会以 root 身份运行，因为没有设置 `User=` 和 `Group=`。
- `WorkingDirectory` 必须指向项目根目录。
- `ExecStart` 必须使用虚拟环境中的 Python。
- `Restart=always` 可保证 Bot 异常退出后自动拉起。

---

## 10. 启动服务

重新加载 systemd 配置并启动服务：

```bash
systemctl daemon-reload
systemctl enable chiyanlu-bot
systemctl start chiyanlu-bot
```

查看运行状态：

```bash
systemctl status chiyanlu-bot
```

查看实时日志：

```bash
journalctl -u chiyanlu-bot -f
```

如果服务正常运行，可以看到 Bot 启动相关日志。

---

## 11. 常用维护命令

### 重启服务

```bash
systemctl restart chiyanlu-bot
```

### 停止服务

```bash
systemctl stop chiyanlu-bot
```

### 启动服务

```bash
systemctl start chiyanlu-bot
```

### 查看服务状态

```bash
systemctl status chiyanlu-bot
```

### 查看是否开机自启

```bash
systemctl is-enabled chiyanlu-bot
```

### 查看日志

```bash
journalctl -u chiyanlu-bot -f
```

### 更新代码后重启

```bash
cd /opt/Chiyanlu-Exclusive-Bot
git pull
source .venv/bin/activate
python3 -m pip install -r requirements.txt
systemctl restart chiyanlu-bot
```

---

## 12. 配置完成后的管理步骤

Bot 启动后，使用超级管理员账号在 Telegram 中进入私聊：

- 发送 `/start`
- 或发送 `/admin`

然后在管理面板中依次完成：

1. 设置发布频道
2. 设置响应群组
3. 添加老师
4. 如有需要添加其他管理员
5. 检查系统状态
6. 使用发布预览确认内容
7. 必要时执行手动发布

---

## 13. 发布与签到工作方式

### 老师签到

老师在私聊 Bot 中发送：

```text
签到
```

Bot 会判断：

- 老师是否已录入
- 老师是否启用
- 当前时间是否在签到截止时间前
- 当天是否已经签到过

### 每日自动发布

定时任务会在设定时间：

1. 删除前一天已发送的发布消息
2. 获取当天已签到老师
3. 生成带按钮的发布内容
4. 发送到配置好的频道

### 手动发布

如果管理员需要临时发布，可以直接在系统设置中点击“手动发布”。

### 发布预览

“发布预览”只会在管理员私聊中展示内容，不会发送到频道。

---

## 14. 备份建议

项目使用 SQLite，建议定期备份数据库文件：

```text
/opt/Chiyanlu-Exclusive-Bot/data/bot.db
```

手动备份示例：

```bash
mkdir -p /root/chiyanlu-backups
cp /opt/Chiyanlu-Exclusive-Bot/data/bot.db /root/chiyanlu-backups/bot-$(date +%F-%H%M%S).db
```

---

## 15. 排错指南

### 15.1 服务无法启动

检查：

- `.env` 是否存在
- `BOT_TOKEN` 是否正确
- `SUPER_ADMIN_ID` 是否为纯数字
- 虚拟环境是否已创建
- `requirements.txt` 是否已安装
- `ExecStart` 路径是否正确

查看详细日志：

```bash
journalctl -u chiyanlu-bot -xe
```

### 15.2 无法收到群组关键词响应

检查：

- Bot 是否在群组内
- 群组是否已配置到后台
- 是否开启了 Bot 的群消息读取权限
- 是否处于冷却时间内
- 匹配的关键词是否完全一致

### 15.3 无法自动发布

检查：

- 发布频道是否已配置
- Bot 是否有发消息权限
- 当天是否有老师签到
- `PUBLISH_TIME` 是否正确
- VPS 时区是否与配置一致

### 15.4 数据库路径错误

如果服务日志中出现数据库文件找不到的情况，请确认：

- `data/` 目录存在
- `DATABASE_PATH` 配置正确
- 当前服务是否在 `/opt/Chiyanlu-Exclusive-Bot` 目录下运行

### 15.5 git clone 权限错误

如果出现：

```text
fatal: could not create work tree dir 'Chiyanlu-Exclusive-Bot': Permission denied
```

说明当前用户没有目标目录写入权限。

本文档使用 root 用户部署，建议确认当前用户：

```bash
whoami
```

如果不是 root，请切换到 root 后再执行部署命令。

---

## 16. 推荐运维习惯

- 定期更新系统补丁
- 定期备份 `bot.db`
- 更新代码后先检查日志再对外使用
- 不要将 `.env` 提交到 Git 仓库
- VPS 仅部署该 Bot 时，可使用本文档的 root 部署方式
- 如果后续同一台 VPS 部署多个服务，建议改为独立用户运行
