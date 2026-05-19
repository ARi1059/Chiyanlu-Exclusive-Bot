# 报销规则说明

> 本文档面向运营人员、管理员与超管。内容根据当前代码（截至 2026-05-18）整理。所有规则以代码实际行为为准；模糊或未明确处标注 **"需产品确认"**。

---

## 一、报销系统定位

报销系统将符合条件的**评价 / 报告**自动转为待审核的报销申请，由超级管理员二次审核后由人工 / 客服线下发放权益。

⚠️ **报销涉及真实金钱权益**，所有规则应以**频道公告 + 后台配置**为准。代码内的规则（金额映射、积分门槛、周限、月池）随时可能由超管在后台调整。运营人员应：

- 不擅自承诺审批结果
- 不公开后台配置细节（如月池余额）
- 不通过群组私聊承诺金额
- 所有发放必须留痕

---

## 二、报销申请来源

### 2.1 字段

`teacher_reviews.request_reimbursement` 是一个 INTEGER：

| 取值 | 含义 |
|---|---|
| `0` | 用户未申请 / 不合格 |
| `1` | 用户明确勾选了「申请报销」（功能 ON 状态下） |
| `2` | 用户合格但功能 OFF —— 静默录入名单（queued） |

### 2.2 触发流程

1. 用户在写评价的卡片 FSM 中点 [✅ 提交]
2. 系统检查 [资格](#四报销资格) 决定 `request_reimbursement` 值
3. **不在此时**创建 `reimbursements` 记录
4. 评价进入审核队列，超管点 [✅ 通过] 时**才**创建 `reimbursements` 记录（status = pending 或 queued）

**关键：报销记录的唯一创建入口在 `rreview_admin.py` 评价审核通过时。代码没有其它创建报销的路径。**

---

## 三、报销状态

`reimbursements.status` 共 5 个枚举值（DB CHECK 约束）：

| 状态 | 中文 | 写入时机 |
|---|---|---|
| `pending` | ⏳ 待审核 | 用户勾选申请 + 评价过审 + 功能 ON |
| `approved` | ✅ 已通过 | 超管在「💰 报销审核」点 [✅ 通过] 且周/月配额校验通过 |
| `rejected` | ❌ 已驳回 | 超管在「💰 报销审核」点 [❌ 驳回] 并填写原因 |
| `queued` | 📋 已录入名单（待启用） | 用户合格 + **功能 OFF** + 评价过审；admin 可后续手动激活转 pending |
| `cancelled` | 🚫 已取消 | ⚠️ 当前代码无任何写入点 |

> **需产品确认：** `cancelled` 状态在 DDL 中保留但**代码全无写入路径**（既无 admin 取消按钮，也无 user 取消接口）。是预留位 / 计划中功能 / 还是只能手工 SQL？目前 cancelled 仅作为可选 UI 状态文案展示，实际不会出现。

---

## 四、报销资格

### 4.1 提交评价时的资格校验（决定 `request_reimbursement` 取值）

校验顺序：

1. **必须有评价**：报销绑定 review，无评价不会询问
2. **必须通过必关订阅校验**（继承评价提交的前置条件）：用户必须已加入 `required_subscriptions` 中全部 active 频道/群组
3. **老师价位 > 0**：`compute_reimbursement_amount(teacher.price) > 0`（金额规则见 [§五](#五报销金额)）
4. **积分门槛**：`user.total_points >= reimbursement_min_points`（**默认 5**，可在后台 config 调整）
5. **功能开关**：`reimbursement_feature_enabled == "1"`

校验结果：

| 1 + 2 + 3 + 4 | 5 (功能开关) | 用户体验 | request_reimbursement |
|---|---|---|---|
| ❌ 任一不满足 | 任意 | 不弹询问，直接进入确认页 | `0` |
| ✅ 全部满足 | OFF | 不弹询问，静默录入 | `2` |
| ✅ 全部满足 | ON | 弹「💰 是否申请本次报销 X 元？」 | `1` 或 `0`（看用户选择） |

### 4.2 评价审核通过时的二次校验（决定是否真的创建 reimbursement）

超管点 [✅ 通过] 时再次重算：

1. 实时 `compute_reimbursement_amount(teacher.price)`
2. 实时读 `reimbursement_min_points`
3. **使用审批后的新积分余额**（含本次评价加分）
4. 仅当 `amount > 0 AND new_total_points >= min_pts` 时才真正写入 `reimbursements` 表

⚠️ **审批阶段不校验周限制和月池**。周/月校验只在超管点 [✅ 通过] 报销那一刻进行（见 [§九](#九审核流程)）。

> **需产品确认：** `reimbursement_feature_enabled` 配置项默认值（即 DB 中未设置时）按代码逻辑视为非 `"1"` → 默认 OFF → 默认走 queued 路径。这是否符合产品预期？运营首次部署时若未在后台启用，所有合格用户都会落入 queued，不进入审核队列。

---

## 五、报销金额

由 `compute_reimbursement_amount(teacher.price)` 计算。规则：

1. 取老师的 `price` 字段（字符串，如 `"800P"` / `"1000P"`）
2. 提取所有数字字符拼接（去除 P / 中文 / 空格 等）
3. 整除以 100 得 `hundreds`
4. 按下表映射金额：

| price 显示档位（hundreds） | 报销金额 |
|---|---|
| 0（无数字 / 解析为 0） | 0 元（不可申请） |
| 1 ~ 8 | **100 元** |
| 9 | **150 元** |
| 10 及以上 | **200 元** |

### 示例

| 老师 price | hundreds | 报销金额 |
|---|---|---|
| `"500P"` | 5 | 100 元 |
| `"800P"` | 8 | 100 元 |
| `"900P"` | 9 | 150 元 |
| `"1000P"` | 10 | 200 元 |
| `"2500P"` | 25 | 200 元 |
| `"P"` / `"免费"` / 空 | 0 | 不可申请 |

⚠️ **金额由老师 price 决定，不由用户评分 / 评价类型决定。** 同一老师所有用户的报销额度一致。

⚠️ **如果运营修改了老师 price**，后续新发起的报销金额会按新值计算；**已 pending 的报销金额已固定，不随老师 price 变化重算**（amount 字段在创建时即落库）。

---

## 六、每周限制

### 6.1 默认规则

**每用户每 ISO 周最多 1 次 approved 报销**（硬编码）。

- 统计字段：`reimbursements.week_key`，格式 `YYYY-Www`，如 `"2026-W20"`
- 周以 ISO 标准：周一为第 1 天，跨年时归属去年最后一周或新年第 1 周
- 时区按 `config.timezone`（默认 Asia/Shanghai）

> **需产品确认：** 周限制目前是代码硬编码 `>= 1`，不走 config。若运营需要调整（如改成 2 次 / 周），需修改代码。是否需要纳入 config 配置项？

### 6.2 reset voucher（额外审批券）

`reimbursement_resets` 表用于记录"额外审批券"。语义：

- **每张 voucher = 一次性"跳过本次周校验"**
- **不是** "+1 永久额度"
- **不是** "把当周已批数归零"
- 一名用户可同时持有多张 voucher（多次重置 = 多张）

### 6.3 voucher 操作流程

- **发放**：超管在某条报销的详情页点 [🔄 重置该用户本周] 二次确认后，调 `grant_reimbursement_reset(user_id, admin_id)`，写一条 `consumed=0` 的记录
- **消耗**：下次该用户**任何一次** approved 操作时，若 `week_used >= 1`，系统自动取**最早一张** 未消耗 voucher 标记 `consumed=1, consumed_at, consumed_reimb_id`
- **审计**：发放写 `admin_audit_logs(action="reimburse_reset")`

### 6.4 运营注意

- 发放 voucher 等于"对该用户解锁一次本周额外审批"，请慎重
- voucher 永久有效，不过期；如发放后用户长期不申请，可能积压
- 不存在批量发放 / 批量回收 UI，所有发放需逐次操作

---

## 七、月度报销池

### 7.1 配置

- 配置项：`reimbursement_monthly_pool`（写入 `bot_config` 表）
- 单位：元
- **默认值**：未设置 / 解析失败 → `pool = 0` → **不限**
- 入口：超管在「⚙️ 系统设置」→「💰 报销池设置」中输入数字保存

### 7.2 统计

- 统计字段：`reimbursements.month_key`，格式 `YYYY-MM`，如 `"2026-05"`
- 时区按 `config.timezone`
- 统计基数：**当月所有 status=approved 的 reimbursements 的 amount 求和**（全局池，所有用户共享）

### 7.3 校验时机

**仅在超管点 [✅ 通过] 时校验**。流程：

1. 读 `pool`，若 `pool <= 0` 视为不限 → 直接放行
2. 否则计算 `month_used = SUM(amount)` 当月已批准的报销
3. 若 `month_used + 本次申请 amount > pool` → 弹「⚠️ 本月池余额 X 元，不足以批准本次 Y 元」并**阻止本次审批**（记录仍为 pending）

### 7.4 注意

- 月池**不阻止用户提交申请**，只阻止超管审批通过
- 月池不足时**没有自动排队 / 自动顺延到下月**逻辑，pending 记录就停在那里，需要超管主动延后处理或驳回
- 用户主页「🧾 我的报销」可见当月池余额（信息透明），运营若希望对用户隐藏可在后续版本控制显示

> **需产品确认：** 月底未批的 pending 记录跨月时如何处理？目前代码无自动结转。

---

## 八、queued 状态

### 8.1 触发场景

`request_reimbursement = 2` 时（用户合格 + 功能 OFF），评价审核通过时 reimbursement 落库为 `status='queued'`。

含义：**"此用户原本符合报销资格，但活动当时未对外开放报销功能，先录入名单留底"**。

### 8.2 用户侧体现

- 用户提交评价时**不会弹询问**（静默录入）
- 评价通过通知中**不提及**报销（避免暗示用户可申请）
- 用户「🧾 我的报销」明细页会看到「📋 已录入名单（待启用）」状态

### 8.3 后续处理

超管在「💰 报销审核」→「📋 报销名单」查看 queued 记录（按 `created_at ASC` 排序，每页 10 条），可对单条点 [⚡ 激活] 转 `pending`，进入正常审批队列。

⚠️ **激活操作不会重新校验资格**：
- 不重算 amount
- 不重读积分余额
- 不检查 `reimbursement_feature_enabled` 当前状态

这是有意设计："只要曾经合格，就保留名单上的资格"。运营如不希望此行为应在激活前人工核对。

### 8.4 运营注意

- queued 是"名单留底"机制；若运营决定从此不再补发，可让 queued 永久停留不激活
- 不存在「批量激活」按钮，所有激活逐条进行
- queued 状态不计入周限 / 月池统计

> **需产品确认：** queued 记录若长期不激活，是否应有过期清理策略？目前代码无清理逻辑。

---

## 九、审核流程

### 9.1 入口

`/admin` →「💰 报销审核」（仅超管可见，普通管理员无权限）。两个子页：

- **[👀 待审核]**：按 `created_at ASC` 显示最早一条 pending，逐条审批
- **[📋 报销名单]**：分页查看 queued 列表（每页 10 条）

### 9.2 详情页内容

每条 pending 详情显示：
- 报销编号 `#id`
- 用户（半匿名 `*****6789`，鉴于隐私）
- 老师名 + 老师 price + 计算所得 amount
- 关联 review_id + 评价证据照片预览
- `week_key` + 本周已批数 `X/1`
- `month_key` + 本月已用池金额
- 当前持有的 reset voucher 数量

### 9.3 通过流程

点 [✅ 通过] 后：
1. 校验状态必须为 `pending`，否则拒绝
2. 校验月池（见 [§七](#七月度报销池)），失败显示 alert 中止
3. 校验周限（见 [§六](#六每周限制)），失败：
   - 用户**无** voucher → 显示 alert，提示「本周已批过」
   - 用户**有** voucher → 继续，事后消耗
4. `UPDATE ... SET status='approved', decided_at=NOW, decided_by=admin_id`
5. 若用了 voucher，标记消耗
6. 写 `admin_audit_logs(action="reimburse_approve")`
7. 私聊通知用户「✅ 你的报销申请 #X 已通过」（含金额、客服联系提示）
8. 推下一条

### 9.4 驳回流程

点 [❌ 驳回] 后进入 `ReimburseRejectStates.waiting_reason` FSM：

- 要求输入驳回原因
- **必填，不可为空，≤ 200 字**
- 写入 `reject_reason` 字段
- 通知用户「❌ 你的报销申请 #X 未通过」+ 原因

### 9.5 reset voucher 重置

详情页 [🔄 重置该用户本周] → 二次确认 → 发放 voucher（见 [§六](#六每周限制)）。

### 9.6 激活 queued

「📋 报销名单」分页 → 点单条 [⚡ 激活] → 状态 `queued → pending`，写 `admin_audit_logs(action="reimburse_activate")`，**不通知用户**（用户下次看「🧾 我的报销」会自然看到状态变化）。

### 9.7 审计标签

| action | 含义 | 关键 detail |
|---|---|---|
| `reimburse_approve` | 通过报销 | user_id / amount / week_key / month_key / reset_consumed |
| `reimburse_reject` | 驳回报销 | user_id / reason |
| `reimburse_reset` | 重置周配额 | user_id / voucher_id |
| `reimburse_activate` | 激活 queued | user_id / amount |
| `reimburse_created` | （联动）评价通过时自动创建 | review_id / amount / status |
| `reimburse_queued` | （联动）功能 OFF 时静默录入 | review_id / amount |

---

## 十、用户侧展示

### 10.1 入口

用户私聊主菜单「🧾 我的报销」（callback `user:reimburse`）。

### 10.2 总览页内容

- 本周已通过：`X/1 笔`
- 本月已通过总额：`X 元`（池 N 元 / 池不限）
- 累计申请：`X 笔`
- **最近 5 笔**：编号、老师、金额、状态；驳回的额外显示原因前 30 字
- 提示文案：「💡 提交评价时若满足积分门槛 + 老师价位 > 0，可勾选申请报销」

### 10.3 明细分页

callback `user:reimburse:list[:page]`，每页 10 条，按 `created_at DESC` 排，显示完整驳回原因。

### 10.4 用户能否取消 pending

**否**。用户无任何取消 / 修改报销的 UI。所有操作权在超管侧。

---

## 十一、驳回与申诉

### 11.1 驳回后用户的可见信息

- 私聊收到「❌ 你的报销申请 #X 未通过」+ 完整原因
- 「🧾 我的报销」中状态变为 ❌ 已驳回，原因永久可见

### 11.2 用户申诉应提供的材料

如用户认为驳回有误，应在客服群组 / 私聊提供：

1. **报销编号 `#X`**（在「我的报销」中可见）
2. **关联评价 / 报告编号**（review_id）
3. **约课截图 + 现场手势照** 原图（原图比 Telegram 压缩后清晰）
4. **与老师的相关聊天记录截图**（如时间确认）
5. **申诉说明**：明确异议点是金额、资格、还是审核误判
6. **预期处理结果**：希望复核 / 补审 / 部分批 / 不接受驳回

### 11.3 运营受理流程建议

1. 在审计日志中按 user_id 查到驳回操作的超管 + 原因
2. 与该超管核对决策依据
3. 如确属误驳：超管可在「⚖️ 手动加扣分」补偿用户积分（视情况），并在 `admin_audit_logs` 留备注；目前代码**不支持**将已 rejected 的记录复原为 pending（一旦驳回即终态）
4. 如属用户理解偏差：耐心解释规则
5. 重要：**不要承诺"下次一定批"**——审批权限在超管，运营人员不可替超管承诺

> **需产品确认：** 是否需要补充"已驳回报销重新审核"功能？目前 rejected 是终态，唯一补救途径是补偿积分。

### 11.4 申诉时限建议

代码无时限。运营建议：申诉应在驳回后 **30 天内**提出，时间越久越难还原决策依据（评价证据照片可能已失效）。

> **需产品确认：** 是否对申诉受理设定明确有效期？

---

## 十二、运营注意事项

### 12.1 与频道公告同步

- 频道公告中提及的"参与条件 / 报销金额 / 周限制 / 月池"必须与后台配置一致
- 后台调整 `reimbursement_min_points` / `reimbursement_monthly_pool` 时应**同步更新公告**
- 不要在公告中承诺代码未实现的功能（如"已驳回可申诉重审"）

### 12.2 月池定期核对

- 月初核对 `reimbursement_monthly_pool` 配置值是否与运营计划一致
- 月中关注「我的报销」总览页显示的「本月已通过总额」，避免月底突然耗尽
- 月池耗尽期间：所有合格报销停留在 pending，**主动通知用户延后审批**

### 12.3 审核前检查清单

超管批准每条报销前应确认：

- [ ] 评价已通过审核（status=approved）
- [ ] 评价证据照片真实有效（约课截图 + 现场手势）
- [ ] 老师 price 字段未被恶意篡改
- [ ] 用户积分余额满足门槛
- [ ] 本周该用户未超额 / 已发 voucher
- [ ] 本月池足够覆盖本次金额
- [ ] 用户未在黑名单 / 异常行为标记

### 12.4 ⛔ 不直接改数据库

资金相关数据严禁直接 UPDATE `reimbursements` 表：
- 会绕过审计
- 会导致 `users.total_points` 与积分流水不一致（如手动改 amount 但不补积分）
- 会丢失 `decided_at` / `decided_by` / `reject_reason` 等关键追溯信息

### 12.5 ⛔ 不绕开 UI 发放

线下转账 / 微信转账 / 红包 等真实权益发放必须**对应** approved 报销记录。运营禁止线下发放但 Bot 中不写记录，会导致：
- 财务对不上
- 月池统计失真
- 用户重复申请同一笔被拒后投诉

### 12.6 备份频率

- `update.sh` 在每次更新前自动备份（含 reimbursements 表）
- 强烈建议另设 crontab 每日 3:30 调用 `scripts/backup.sh` 做 WAL-safe 备份 → 见 [`DEPLOYMENT.md` §14.4](DEPLOYMENT.md)
- 资金相关数据丢失等于真实赔付风险，备份不可省

### 12.7 通知失败

`notified_at` 字段当前**不写入**（`mark_reimbursement_notified` 函数已定义但无调用方）。即所有用户都"显示已通知"。

⚠️ **如果 send_message 失败**（用户屏蔽 bot / 未启动 bot），代码仅记 warning，用户不会收到任何通知，但报销状态已变更。运营建议：

- 用户突然消失（屏蔽 bot）的 pending 报销，运营可主动通过其它渠道告知结果
- 大量批量审批后留意 journalctl 中的「send_message 失败」warning

> **需产品确认：** 是否需要在 send_message 成功后调用 `mark_reimbursement_notified` 以便追溯？目前是死字段。

---

## 十三、报销专用必关频道 / 群组（2026-05 新增）

### 13.1 定位与边界

- **与全局必关订阅独立**：项目原有"必关频道/群组"（`required_subscriptions` 表 + `admin:subreq:*` callback）服务于**写评价入口**校验；本节描述的"报销专用必关"是**独立**配置，**仅影响报销准入**。
- **不强制**：未配置任何报销必关项时，报销流程**不强制订阅检查**，与改造前行为一致。
- **不影响**：用户浏览老师 / 搜索 / 收藏 / 最近看过 / 评价提交主流程（除"勾选申请报销"那一步外）/ 抽奖 / 签到等流程**完全不受影响**。

### 13.2 数据存储

复用 `config` 表，独立 key：

| 配置 key | 值格式 |
| --- | --- |
| `reimbursement_required_chats` | JSON array of `{chat_id, chat_type, display_name, invite_link, enabled}` |

不新增表 / 不新增 schema 迁移。空 key / JSON 解析失败时安全返回空列表（=不拦截）。

### 13.3 后台配置入口

| 路径 | callback | 权限 |
| --- | --- | --- |
| `/admin` → ⚙️ 系统配置 → ⚙️ 系统设置 → 💰 报销必关设置 | `system:reimburse_subreq` | **仅超管** |

子动作：
- `system:reimburse_subreq:add` — 添加（3 步 FSM + 二次确认）
- `system:reimburse_subreq:delete:<idx>` — 删除询问
- `system:reimburse_subreq:confirm_delete:<idx>` — 删除二次确认
- `system:reimburse_subreq:add_confirm` — 添加最终确认

添加流程：输入 `chat_id` → bot 调 `precheck_required_chat` 校验 → 输入展示名（≤60 字符）→ 输入邀请链接（必须 `https://t.me/` 开头）→ 确认页 → 写入 config + `log_admin_audit(action="reimburse_subreq_add")`。

删除流程：列表点击 → 二次确认 → 删除 + `log_admin_audit(action="reimburse_subreq_remove")`。

**所有写操作必须写 `admin_audit_logs`**。

### 13.4 用户准入校验触发点

仅在用户**勾选「✅ 申请报销」**时触发——具体两个 callback：
- `review:reimburse_yes`（`bot/handlers/review_submit.py:cb_review_reimburse_yes`）
- `card:reimburse:yes`（`bot/handlers/review_card.py:cb_card_reimburse_yes`）

判定逻辑：`bot/utils/reimburse_subreq.check_user_subscribed_for_reimburse(bot, user_id)`
- 遍历 `enabled=True` 的项
- 对每项调 `bot.get_chat_member(chat_id, user_id)`
- 已加入判定：`status ∈ {member, administrator, creator}`
- bot API 抛异常的项：跳过 + warning，**不计入** missing（容错与全局 subreq 一致）

### 13.5 用户拦截页

未通过时，把消息 edit 为：

```
💰 报销资格校验

申请报销前，请先加入以下频道 / 群组：
1. 频道 A
2. 群组 B

完成后点击下方按钮重新检查。
```

按钮组（含 `invite_link` 的项渲染 `📢 加入：{display_name}` URL 按钮）：
- `📢 加入：{name}` → URL（用户加入入口）
- `✅ 我已加入，重新检查` → `reimburse:subreq:recheck:<context>`
- `⬅️ 返回` → `reimburse:subreq:back:<context>`（视为"不申请报销"，继续进入评价确认页）

其中 `<context>` 为 `submit`（评价 FSM 主路径）或 `card`（卡片 FSM 路径），保证 recheck/back 回到正确的 FSM 状态。

### 13.6 隔离性保证

| 触发场景 | 是否触发报销 subreq 校验 |
| --- | --- |
| 用户浏览老师 / `teacher:view` | 否 |
| 搜索 / 条件筛选 / 热门 / 今日 | 否 |
| 收藏 / 最近看过 / 我的记录 | 否 |
| 评价提交（不勾选申请报销） | 否 |
| **评价提交（勾选 ✅ 申请报销）** | **是** |
| 抽奖参与 / 开奖 | 否 |
| 签到 | 否 |
| 全局必关订阅检查（写评价入口） | 不变，与本节无关 |

### 13.7 安全 / 兼容性

- 不修改 `compute_reimbursement_amount` / 积分发放 / 抽奖逻辑。
- 不修改 `required_subscriptions` 表与 `subreq_admin.py` handler。
- 不新增 schema migration。
- callback `reimburse:subreq:*` 与既有 `reimburse:enter` / `reimburse:approve:*` / `reimburse:reject:*` / `reimburse:queued:*` / `reimburse:reset:*` 等命名空间独立，不冲突。
- 既有报销审核 / queued 名单 / reset voucher 流程**完全未受影响**。

### 13.8 运营提示

- **空配置时**，旧逻辑保留：所有用户都能继续勾选申请报销。如果运营希望"立刻关闭报销准入要求"，把配置清空即可（删除所有项）。
- **配置错误时**（如 bot 无权访问 chat / chat_id 无效），添加步骤会被 `precheck_required_chat` 拒绝，不会写入 config。
- **bot 失去管理员**时，相关项的 `bot.get_chat_member` 调用可能失败 → 被跳过（按容错策略），导致用户被放行。此时建议配合定期 health check 监控 bot 自身的频道权限状态。

---

## 十四、相关文档

- 积分规则（积分门槛 / 审计）：[`POLICY-points.md`](POLICY-points.md)
- 抽奖规则：[`POLICY-lottery.md`](POLICY-lottery.md)
- 部署与备份：[`DEPLOYMENT.md`](DEPLOYMENT.md)
- 稳定化审查：[`STABILITY-AUDIT-2026-05-18.md`](STABILITY-AUDIT-2026-05-18.md)
