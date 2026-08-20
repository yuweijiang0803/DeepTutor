# DeepTutor ↔ XiaoZhi (manager-web) 打通设计

> 目标：学生单点登录 + 对话记录进小智 MySQL + 老师在小智看学情。
> 原则：**DeepTutor 存储层不改**（保持每用户 SQLite），打通逻辑全部落在小智侧 + 一个同步服务。

## 一、总体架构

```
┌─────────────────────────┐
│  PC 客户端 (DeepTutor)   │  登录小智拿 mix-token → token 换 DeepTutor token
└──────────┬──────────────┘
           │ DeepTutor API/WS
           ▼
┌─────────────────────────┐        校验 mix-token（共享密钥或调小智接口）
│  DeepTutor 后端 (uvicorn) │ ────────────────────────────────────────┐
│  · 每用户 SQLite (不动)    │                                         │
│  · SSO 中间件 (新增)       │                                         ▼
└──────────┬──────────────┘                                  ┌────────────────┐
           │ 同步服务（新增，定时）                              │ 小智 manager    │
           │ 读 SQLite → 灌 MySQL                              │ (aiohttp:8084) │
           ▼                                                 └───────┬────────┘
┌─────────────────────────┐  deeptutor_sessions / messages          │ 读写
│  小智 MySQL (mixly 库)    │ ◄───────────────────────────────────────┘
└─────────────────────────┘
```

## 二、账号打通（SSO）

### 现状
- 小智：JWT (HS256)，`core/utils/token.py`，payload = `{i:[user_id,role_id,role,clase,school], e:exp, v:1, sid}`
- DeepTutor：自己的 `users.json` + 自己的 token

### 打通方式（token 交换）

1. **PC 客户端先登录小智** → 拿到 `mix-token`（cookie 或 body 里的 `access_token`）
2. 客户端调 **DeepTutor 新增的登录接口**（如 `POST /api/v1/auth/xiaozhi-login`），把 `mix-token` 传过去
3. DeepTutor 校验 token，两种校验方式二选一：
   - **方式 A（简单）**：共享 JWT 密钥 —— DeepTutor 用小智的 `SECRET_KEY` + HS256 解码 `mix-token`。`payload.i[0]` = 小智 user_id，`i[2]` = role
   - **方式 B（安全，推荐生产）**：DeepTutor 调小智新增的 `GET /api/v1/verify-token` 接口验证，不共享密钥
4. 校验通过 → 在 `user_map` 表里找 `xz_user_id → dt_user_id`；没有就**自动创建 DeepTutor 用户**（用户名 `xz_<user_id>`，密码随机不可登录），并写入映射
5. 给客户端签发 **DeepTutor 自己的 token**，后续走 DeepTutor 正常认证

### 新增表（小智 MySQL）

```sql
-- 身份映射表（放小智库，两边都能读）
CREATE TABLE deeptutor_user_map (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  xz_user_id    BIGINT       NOT NULL,           -- 小智 users.id
  dt_user_id    VARCHAR(64)  NOT NULL,           -- DeepTutor 用户 id (u_xxx)
  dt_username   VARCHAR(64)  NOT NULL,
  role          VARCHAR(16)  DEFAULT 'student',  -- 镜像小智角色
  created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_xz (xz_user_id),
  UNIQUE KEY uk_dt (dt_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 三、对话记录进小智 MySQL（数据同库）

### 新增表（小智 MySQL，会话/消息镜像）

```sql
CREATE TABLE deeptutor_sessions (
  id           BIGINT PRIMARY KEY AUTO_INCREMENT,
  dt_session_id  VARCHAR(64)  NOT NULL,          -- DeepTutor 会话 id，幂等键
  xz_user_id     BIGINT       NOT NULL,
  title          VARCHAR(255) DEFAULT '',
  capability     VARCHAR(32)  DEFAULT 'chat',    -- chat / deep_solve / ...
  summary        TEXT,
  created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_dt_session (dt_session_id),
  KEY idx_user (xz_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE deeptutor_messages (
  id          BIGINT PRIMARY KEY AUTO_INCREMENT,
  dt_msg_id   VARCHAR(64)  NOT NULL,             -- DeepTutor 消息 id，幂等键
  dt_session_id VARCHAR(64) NOT NULL,
  xz_user_id    BIGINT      NOT NULL,
  role        VARCHAR(16)  NOT NULL,             -- user / assistant / ...
  content     MEDIUMTEXT,
  meta        JSON,                              -- 附件、token 数、时间戳等
  created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_dt_msg (dt_msg_id),
  KEY idx_session (dt_session_id),
  KEY idx_user_time (xz_user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> 加 `dt_session_id` / `dt_msg_id` 唯一键 → 同步可**幂等 upsert**，重复跑不产生脏数据。

## 四、同步服务

- 部署在小智侧（或单独容器），语言不限（Python 建议）
- **逻辑**：
  1. 遍历 `data/users/<dt_user_id>/user/chat_history.db`（每个 dt_user_id 对应一个 xz_user_id，查 `deeptutor_user_map`）
  2. 按 `updated_at` 增量读取新 sessions/messages
  3. `INSERT ... ON DUPLICATE KEY UPDATE` 灌进 `deeptutor_sessions` / `deeptutor_messages`
  4. 记录每用户 `last_sync_time`（放一张 `deeptutor_sync_state` 表），断点续传
- **触发**：cron 每 1-5 分钟一次；学生量小可每次全量扫（SQLite 很快）
- **删除同步**：DeepTutor 删会话时打标记，同步服务定期清理镜像（可选，先不做）

## 五、老师在小智看学情

- 小智新增只读 API（aiohttp router）：
  - `GET /api/teacher/deeptutor/sessions?student_id=&page=` —— 查某学生会话列表
  - `GET /api/teacher/deeptutor/sessions/{id}/messages` —— 查会话消息
  - 权限：`clase`(老师) / `school`(校长) / `admin` 可查自己班级学生的记录
- manager-web 加一个页面（或在现有「学情」页加 Tab）：选择学生 → 看会话列表 → 看对话详情
- 复用现有的角色/班级数据模型，不做新权限体系

## 六、落地步骤（建议顺序）

1. **先做 SSO**（最小闭环）：`deeptutor_user_map` 表 + DeepTutor 登录接口 + 客户端 token 交换 → 验证「学生小智登录后能进 DeepTutor」
2. **再做同步**：两张镜像表 + 同步服务 + `deeptutor_sync_state` → 验证「对话出现在小智 MySQL」
3. **最后做老师端**：查询 API + manager-web 页面 → 验证「老师能看到学生 AI 对话」

## 七、改动清单

| 侧 | 改动 |
|---|---|
| **DeepTutor（fork）** | 新增 1 个登录接口（token 校验 + 自动建用户）；其余不动 |
| **小智 manager** | 新增 4 张表 + 2 个接口（verify-token 可选、teacher 查询）+ 同步服务 |
| **manager-web** | 新增学情页/Tab（只读展示） |
| **PC 客户端** | 登录流程改为「先登小智 → token 交换进 DeepTutor」 |

## 八、安全注意

- **方式 A 共享密钥**：小智 SECRET_KEY 目前硬编码在仓库里，共享后务必：
  - 换成环境变量注入，且两端一致
  - 密钥泄露 = 能伪造两边身份，生产必须用**方式 B**（verify 接口）或专用服务 token
- DeepTutor 自动创建的用户密码随机、禁止直接登录，只能走 SSO 进
- 同步服务需要访问 DeepTutor 的 `data/` 目录（同机部署）或通过导出接口
