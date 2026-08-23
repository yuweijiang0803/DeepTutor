# DeepTutor 班级层设计（复用小智组织 + AI 学习层）

> 定位：面向**学校 / 教培机构**，老师带班教学生，需要班级共享教材、AI 学习与班级学情。
>
> **核心决策**：不重复建设学校/班级/账号体系——**复用现有小智（manager-web）组织**，
> DeepTutor 只补"AI 学习"相关的一层：班级共享知识库、学情聚合、身份切换。

## 一、组织数据来源（小智已有，DeepTutor 只读）

小智 `mixly` 库已经具备完整的多租户组织体系，DeepTutor 直接读取，不新建组织表：

| 表 | 作用 |
|---|---|
| `school` | 学校（多租户）|
| `clase` | 班级（属于某个 school）|
| `roles` | 用户-学校-班级-角色（一个用户可多行 = 多身份）|
| `user` | 账号（登录复用小智账号密码）|

**关键**：一个账号在小智可有多个身份（如同时是 A 校老师 + B 校学生），manager-web 支持切换当前身份。

## 二、分工

| 事情 | 在哪做 |
|---|---|
| 账号 / 学校 / 班级 / 老师学生角色 / 作业 / 题库 | **manager-web**（小智已有）|
| 登录 | 复用（小智账号密码，已实现）|
| 精通之路 / 出题 / 讲解 | DeepTutor（引擎，已有）|
| **身份切换** | DeepTutor（新）|
| **班级共享教材（AI 知识库）** | DeepTutor（新：老师给班级挂教材）|
| **班级学情聚合** | DeepTutor（新：掌握度 / 错题按班级汇总）|

## 三、身份切换机制（DeepTutor 侧）

> 由于 SSO 只携带 `user_id`，DeepTutor 必须自己确定"当前身份"（哪个学校/班级/角色），
> 才能决定功能（老师端 / 学生端）与数据范围（哪个班级的教材、学情）。

### 3.1 数据模型

DeepTutor 侧为每个用户记录"当前身份"（per-user 记忆，存在 `users.json`）：

```json
// users.json 中 user 记录追加字段
{
  "username": "xz_7",
  "role": "user",
  "nickname": "余伟江",
  "active_role": {
    "school_id": 3,
    "clase_id": 12,
    "role": "teacher",
    "updated_at": 1787385600.0
  }
}
```

> 前端也可用 localStorage 记忆，服务端字段作为权威（跨设备一致）。

### 3.2 身份相关 API（DeepTutor 新增）

```
GET  /api/v1/roles                  → 该用户的所有身份（查小智 roles 表）
GET  /api/v1/roles/active           → 当前身份（无则返回默认）
POST /api/v1/roles/active           → 切换当前身份 { school_id, clase_id, role }
```

身份来源查询（小智 `roles` 表）：

```sql
SELECT school, clase, role, expired_at
FROM roles
WHERE user_id = <mixly.user.id>
  AND (expired_at IS NULL OR expired_at > NOW());
```

### 3.3 前端交互

- 登录后，头像/顶部菜单显示当前身份（如"七年级数学1班 · 老师"）
- 点击可切换（下拉列出所有身份，类似 manager-web）
- 切换后 DeepTutor 按新身份刷新：班级教材、学情范围、功能入口

### 3.4 按身份决定的功能与数据

| 当前身份 role | DeepTutor 表现 |
|---|---|
| `teacher` | 老师端：给班级挂 AI 教材、布置作业（关联班级 KB）、看班级学情 |
| `student` | 学生端：用班级共享教材（RAG）、学习、看自己进度/错题 |
| `admin`（school 管理）| 全校/全班视图 |

班级决定数据范围：当前身份的 `clase_id` → 该班级的共享知识库与学情。

> **取舍**：manager-web 与 DeepTutor 是两套身份记忆，互不同步。用户各自切换。
> 若后续要一致，可在 SSO 时把小智当前身份一并携带（增强方案）。

## 四、DeepTutor 新增的表/目录

### 4.1 班级共享知识库（文件系统 + 映射表）

教材文档存文件系统，映射关系存 MySQL（复用现有 `mixly` 库，`dt_` 前缀）：

```sql
-- 班级共享知识库映射
CREATE TABLE IF NOT EXISTS dt_class_kb (
  clase_id   VARCHAR(64)  NOT NULL,             -- 复用小智 clase.id
  kb_name    VARCHAR(255) NOT NULL,             -- data/classes/<clase_id>/knowledge_bases/<kb_name>
  owner_id   VARCHAR(64)  NOT NULL,             -- 挂载老师（mixly.user.id）
  created_at DOUBLE       NOT NULL,
  PRIMARY KEY (clase_id, kb_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

访问权限：当前身份的 `clase_id` 匹配该班学生/老师才可读（只读）。

### 4.2 班级学情物化表

学习数据仍在 per-user（mastery.sqlite3 / notebook_entries），班级学情按需聚合，定期物化：

```sql
CREATE TABLE IF NOT EXISTS dt_class_report (
  clase_id         VARCHAR(64) NOT NULL,
  knowledge_point  VARCHAR(255) NOT NULL,      -- 知识点（对齐精通之路）
  total_students   INT NOT NULL DEFAULT 0,
  mastered         INT NOT NULL DEFAULT 0,
  in_progress      INT NOT NULL DEFAULT 0,
  wrong_count      INT NOT NULL DEFAULT 0,
  updated_at       DOUBLE NOT NULL,
  PRIMARY KEY (clase_id, knowledge_point)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

聚合逻辑：按 `roles`（clase 成员）→ 汇总各学生 mastery 进度 / 错题。

## 五、与 DeepTutor 现有体系的关系

| 现有 | 班级层 |
|---|---|
| `users.json` | 追加 `active_role` 字段（当前身份）|
| `PathService` / scope | 新增 `class` scope（读班级 KB 时只读）|
| 个人知识库 | 不变（per-user），班级 KB 是额外共享只读层 |
| 学习进度 / 题库 | 不变（per-user），班级层只聚合 |
| 登录 / 账号 | 不变（复用小智账号）|

## 六、实现路径

1. **阶段一：身份切换** —— 查 `roles` 列身份、切换、记忆；按身份控制前端功能入口
2. **阶段二：班级知识库** —— 老师挂教材到班级 KB，学生 RAG 可用
3. **阶段三：班级学情** —— 按班级成员聚合掌握度/错题，生成班级报告

## 七、待确认项

- **身份记忆**：服务端 `users.json` 权威，还是前端 localStorage？（建议服务端，跨设备一致）
- **SSO 携带身份**：是否需要 manager-web 当前身份与 DeepTutor 同步（增强，非必须）
- **老师建班**：在 manager-web 建（推荐），DeepTutor 不做建班
