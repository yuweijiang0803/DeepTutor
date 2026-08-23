# 学习数据 MySQL 迁移方案（错题 / 精通之路 / 诊断）

> 目标：把三个"学习数据"（错题、精通之路掌握度、诊断）统一到 MySQL（mixly 库，`dt_` 前缀），
> 支撑学习顾问报告与班级学情的**跨用户聚合**。
>
> 原则：**只切代码逻辑，不迁移历史数据**（旧 SQLite 数据忽略，新数据全进 MySQL）。

## 一、迁移范围

| 数据 | 现状 | 目标表 |
|---|---|---|
| 错题/题库（notebook_entries）| per-user SQLite | `dt_notebook_entries`（+ categories）|
| 精通之路（mastery）| per-user SQLite | `dt_mastery_*` |
| 诊断记录（新增）| — | `dt_error_diagnosis` |

## 二、表结构（DDL，mixly 库）

### 1. 错题 / 题库

```sql
CREATE TABLE IF NOT EXISTS dt_notebook_entries (
  id                      BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id                 VARCHAR(64)  NOT NULL,
  session_id              VARCHAR(64)  NOT NULL,
  turn_id                 VARCHAR(64)  NOT NULL DEFAULT '',
  question_id             VARCHAR(64)  NOT NULL,
  question                MEDIUMTEXT   NOT NULL,
  question_type           VARCHAR(16)  NOT NULL DEFAULT '',
  options_json            MEDIUMTEXT,
  correct_answer          MEDIUMTEXT,
  explanation             MEDIUMTEXT,
  difficulty              VARCHAR(16)  NOT NULL DEFAULT '',
  user_answer             MEDIUMTEXT,
  user_answer_images_json MEDIUMTEXT,
  is_correct              TINYINT      NOT NULL DEFAULT 0,
  bookmarked              TINYINT      NOT NULL DEFAULT 0,
  ai_judgment             MEDIUMTEXT,
  image_refs              MEDIUMTEXT,           -- 学生拍照上传的图片引用（JSON 数组）
  knowledge_point         VARCHAR(255) NOT NULL DEFAULT '',  -- 诊断/学情关联
  created_at              DOUBLE       NOT NULL,
  updated_at              DOUBLE       NOT NULL,
  KEY idx_entries_user (user_id, updated_at),
  KEY idx_entries_kp (knowledge_point)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_notebook_categories (
  id         BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id    VARCHAR(64)  NOT NULL,
  name       VARCHAR(100) NOT NULL,
  created_at DOUBLE       NOT NULL,
  UNIQUE KEY uk_cat_user (user_id, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_notebook_entry_categories (
  entry_id    BIGINT NOT NULL,
  category_id BIGINT NOT NULL,
  PRIMARY KEY (entry_id, category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 2. 精通之路（mastery）

> 现有 SQLite 数据以 JSON blob 为主（state_json / question_json / result_json），
> MySQL 用 MEDIUMTEXT 存，结构不变。

```sql
CREATE TABLE IF NOT EXISTS dt_mastery_paths (
  path_id     VARCHAR(64)  NOT NULL PRIMARY KEY,
  user_id     VARCHAR(64)  NOT NULL,
  state_json  MEDIUMTEXT   NOT NULL,
  revision    BIGINT       NOT NULL,
  created_at  DOUBLE       NOT NULL,
  updated_at  DOUBLE       NOT NULL,
  KEY idx_path_user (user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_mastery_path_sessions (
  path_id      VARCHAR(64) NOT NULL,
  session_id   VARCHAR(64) NOT NULL,
  owns_path    TINYINT     NOT NULL DEFAULT 0,
  created_at   DOUBLE      NOT NULL,
  last_seen_at DOUBLE      NOT NULL,
  PRIMARY KEY (path_id, session_id),
  KEY idx_ms_session (session_id, last_seen_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_mastery_interactions (
  interaction_id VARCHAR(64)  NOT NULL PRIMARY KEY,
  user_id        VARCHAR(64)  NOT NULL,
  path_id        VARCHAR(64)  NOT NULL,
  status         VARCHAR(16)  NOT NULL,
  question_json  MEDIUMTEXT   NOT NULL,
  session_id     VARCHAR(64)  NOT NULL DEFAULT '',
  turn_id        VARCHAR(64)  NOT NULL DEFAULT '',
  user_answer    MEDIUMTEXT   NOT NULL DEFAULT '',
  result_json    MEDIUMTEXT   NOT NULL,
  created_at     DOUBLE       NOT NULL,
  updated_at     DOUBLE       NOT NULL,
  KEY idx_mi_path (path_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_mastery_events (
  id           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id      VARCHAR(64)  NOT NULL,
  path_id      VARCHAR(64)  NOT NULL,
  revision     BIGINT       NOT NULL,
  event_type   VARCHAR(32)  NOT NULL,
  payload_json MEDIUMTEXT   NOT NULL,
  session_id   VARCHAR(64)  NOT NULL DEFAULT '',
  turn_id      VARCHAR(64)  NOT NULL DEFAULT '',
  created_at   DOUBLE       NOT NULL,
  KEY idx_me_path (path_id, revision, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 路径租约（并发控制）
CREATE TABLE IF NOT EXISTS dt_mastery_path_leases (
  path_id     VARCHAR(64) NOT NULL PRIMARY KEY,
  session_id  VARCHAR(64) NOT NULL,
  turn_id     VARCHAR(64) NOT NULL UNIQUE,
  acquired_at DOUBLE      NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 3. 诊断（见 ERROR_DIAGNOSIS.md）

`dt_error_diagnosis`（user_id, kp_id, kp_name, cause, evidence, entry_ids, status, created_at, updated_at）

## 三、迁移策略（只切代码，不迁历史）

1. **建 MySQL 表**（上述 DDL）
2. **改写入代码**：新错题 / mastery 交互 / 诊断 → 写 MySQL
3. **改读取代码**：前端 /space/questions、question_bank 工具、精通之路 → 读 MySQL
4. **旧 SQLite 数据**：不迁移，文件保留（不影响，新逻辑不读它）
5. **前端 / 接口不变**：后端换存储，接口响应结构保持

## 四、代码改造点

| 数据 | 现有代码 | 改造 |
|---|---|---|
| 错题写 | `mastery/tools.py` `_sync_mastery_attempt_to_question_bank`、`question_notebook` router | 改到 MySQL store |
| 错题读 | `question_notebook` router、`question_bank` 工具、前端 | 改到 MySQL store |
| mastery | `learning/storage.py` LearningStore（SQLite）| 换 MySQL 实现，保留接口签名 |
| 诊断 | 新 | 新增 MySQL 表 + CRUD |

**建议**：新增一个 `deeptutor/services/session/mysql_store.py` 扩展（或独立 `deeptutor/services/learning/mysql_store.py`），提供与现有接口一致的 store，切换时最小侵入。

## 五、实施步骤

1. **建表**：执行 DDL（三个数据 8 张表）
2. **错题 MySQL 化**：写 + 读改 MySQL（先做，因为错题是顾问/诊断基础）
3. **mastery MySQL 化**：LearningStore 换 MySQL 实现（保持接口）
4. **诊断**：建表 + API + 诊断 agent
5. **回归测试**：精通之路、错题本、出题功能验证（数据进 MySQL，接口不变）

## 六、风险与注意

| 风险 | 说明 |
|---|---|
| JSON blob 大小 | MEDIUMTEXT（16MB）足够（state_json 等）|
| 并发 | MySQL 事务/锁优于 SQLite 文件锁（mastery 租约机制保留）|
| 双写期间 | 切换是一次性的（代码切换后全走 MySQL，无双写窗口）|
| 图片引用 | `image_refs` 存附件引用（文件系统），MySQL 不存图本身 |
| 性能 | 加 user_id 索引；学情聚合按 user_id/kp 查询 |

## 七、待确认

- **mastery 是否保留 SQLite 兼容层**（开发/单机模式）还是彻底切 MySQL？
- **错题图片上传**是否与本次一起做（image_refs 字段预留，功能后加）？
