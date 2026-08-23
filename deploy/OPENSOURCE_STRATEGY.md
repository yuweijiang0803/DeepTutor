# 开源版 / 商业版双仓库策略（OPENSOURCE STRATEGY）

> 目标：DeepTutor 既保留开源价值（可贡献 upstream、他人可用），
> 又承载商业场景（xiaozhi 打通、班级、学习顾问）。
> 方案：**两个仓库**（公开开源 + 私有商业），商业以开源为基础定期同步。

## 一、开源边界

| 部分 | 归属 | 说明 |
|---|---|---|
| 核心引擎（精通之路、错题、出题、诊断）| **开源** | 通用学习引擎，对所有人有价值 |
| 通用修复（数学渲染、mastery 交互）| **开源** | 适合贡献回 upstream |
| MySQL 存储（错题/精通之路）| **开源（可选）** | 默认 SQLite，配 `mysql.json` 才启用；已有工厂支持 |
| 学科包结构（dt_subject_* 表）| **开源（内容留空）** | 结构可开源，具体题目内容可商业 |
| xiaozhi 打通（SSO、roles 身份、班级层）| **商业** | 与具体平台耦合 |
| 部署配置（服务器地址、密钥）| **商业 / 不入 git** | `.env` 管理 |

## 二、仓库结构

```
开源仓库（public）                   商业仓库（private）
基于 upstream 改进的单机版            = 开源 + 商业增强
├── 核心引擎 / 通用修复               ├── xiaozhi SSO / 身份 / 班级层
├── MySQL 作为可选配置（默认 SQLite）   ├── MySQL 默认开启
├── 无 xiaozhi 集成                    ├── 商业增强（学科包内容、学习顾问）
├── 可贡献 upstream                   ├── 敏感配置（.env，不入 git）
└── 远程备份 ✓                        └── 远程备份 ✓
       ↑ 定期同步通用改进（merge / cherry-pick）
```

- 开源是"上游"，商业是"下游"
- 通用改进 → 进开源；商业定制 → 留私有
- 两边各有一个远程仓库，均有备份

## 三、拆分步骤（从当前混合 develop 出发）

1. **当前 develop 保留** = 商业版基础（含 xiaozhi 集成）
2. **另开开源线**：
   - `git checkout -b opensource upstream/dev`（或从当前 develop 剥离 xiaozhi 层）
   - **cherry-pick 通用改进**：数学渲染、mastery 交互修复、错题/精通之路（作为可选 MySQL）
   - **移除 xiaozhi 专属**：SSO（auth.py 的 xiaozhi-login）、roles 身份、班级层（或配置开关关闭）
3. **商业仓库**：以当前 develop 为基础，独立私有远程
4. **敏感信息**：xiaozhi 密钥、服务器地址、mysql.json 密码 → `.env` / 服务器配置，gitignore

## 四、同步机制（商业拉开源改进）

```bash
# 在商业仓库中，把开源仓库作为 remote 添加
git remote add opensource <开源仓库URL>

# 定期拉取开源改进
git fetch opensource
git merge opensource/main      # 或 cherry-pick 具体 commit
```

- 通用改进（引擎、修复）在开源改 → 商业 merge 进来
- 商业增强只在商业仓库改，不进开源

## 五、安全与备份

1. **敏感信息绝不提交**：xiaozhi 密钥、服务器地址、MySQL 密码 → `.env`（gitignore）。两个仓库都不提交真实密钥（私有仓库也可能被误公开/泄露）
2. **备份**：开源公开仓库、商业私有仓库均为远程备份
3. **推送安全**：推送前确认当前分支，避免商业增强误推开源

## 六、落地清单

- [ ] 拆分开源线（cherry-pick 通用改进，去掉 xiaozhi 层）
- [ ] 建开源公开仓库（推送 opensource 分支）
- [ ] 建商业私有仓库（推送当前 develop）
- [ ] 敏感信息迁移到 .env（清理历史 commit 中的密钥，可考虑 git-filter-repo）
- [ ] 商业仓库添加 opensource remote，验证 merge 同步
- [ ] 更新部署文档（开源版按 UPDATE.md 单机 SQLite；商业版按 MYSQL_MIGRATION.md + xiaozhi 集成）

## 七、注意事项

- **历史 commit 中的密钥**：如果之前提交过 xiaozhi 密钥，开源前需清理（`git-filter-repo` 重写历史），否则密钥仍在 git 历史里
- **MySQL 开源化**：保持 `get_session_store()` / `get_learning_store()` 工厂的"默认 SQLite、可选 MySQL"——开源版不配 mysql.json 即单机可用
- **学科包内容**：结构可开源，具体题目/答案内容留在商业（避免内容被直接拿走）
