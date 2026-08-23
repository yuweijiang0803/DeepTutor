# 初中数学全局学科包设计（SUBJECT PACK）

> 定位：平台**预置**一套对齐课标的初中数学内容（全局共享，非 per-user），
> 学生学习时**引用**这套内容（而非 AI 自由生成），老师基于它布置、看学情。
>
> 与现有内容的关系：现有书籍/题库/知识点都是 **per-user**（个人产生），
> 学科包是**全局预置**（平台提供），两者互补，学科包是"教-学-评"的内容主干。

## 一、整体结构

```
初中数学学科包（dt_subject）
├── 七年级上册（grade）
│   ├── 第一章 有理数（dt_subject_module）
│   │   ├── 知识点：正负数、数轴、相反数、绝对值、有理数运算（dt_subject_kp）
│   │   │   ├── 类型：memory / procedure / concept（对接精通之路 KnowledgeType）
│   │   │   └── 题库：选择题/填空/计算，难度分级（dt_subject_question）
│   ├── 第二章 整式的加减
│   └── ……
├── 七年级下册
└── 八年级 / 九年级（后续扩展）
```

## 二、表结构（MySQL，mixly 库，`dt_` 前缀）

```sql
-- 学科包（一个学科一个包）
CREATE TABLE IF NOT EXISTS dt_subject (
  id          VARCHAR(64)  NOT NULL PRIMARY KEY,
  name        VARCHAR(255) NOT NULL,             -- 如「初中数学」
  grade       VARCHAR(64)  NOT NULL DEFAULT '',  -- 如「七年级上册」
  textbook    VARCHAR(64)  NOT NULL DEFAULT '',  -- 对齐教材：人教版等
  status      VARCHAR(16)  NOT NULL DEFAULT 'active',
  created_at  DOUBLE       NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 章节 / 单元（对齐教材，对应精通之路 LearningModule）
CREATE TABLE IF NOT EXISTS dt_subject_module (
  id            VARCHAR(64)  NOT NULL PRIMARY KEY,  -- 直接用作 LearningModule.id
  subject_id    VARCHAR(64)  NOT NULL,
  name          VARCHAR(255) NOT NULL,
  order_no      INT          NOT NULL DEFAULT 0,
  pass_threshold FLOAT       NOT NULL DEFAULT 0.7,
  KEY idx_module_subject (subject_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 知识点（对应精通之路 KnowledgePoint）
CREATE TABLE IF NOT EXISTS dt_subject_kp (
  id         VARCHAR(64)  NOT NULL PRIMARY KEY,    -- 直接用作 KnowledgePoint.id
  module_id  VARCHAR(64)  NOT NULL,
  name       VARCHAR(255) NOT NULL,
  kp_type    VARCHAR(16)  NOT NULL,                -- memory / procedure / concept / design
  order_no   INT          NOT NULL DEFAULT 0,
  KEY idx_kp_module (module_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 题库（每个知识点下积累题目）
CREATE TABLE IF NOT EXISTS dt_subject_question (
  id           VARCHAR(64)  NOT NULL PRIMARY KEY,
  kp_id        VARCHAR(64)  NOT NULL,
  question     MEDIUMTEXT   NOT NULL,              -- 支持 LaTeX
  q_type       VARCHAR(16)  NOT NULL,              -- choice / fill_in_blank / written
  options      MEDIUMTEXT,                         -- JSON {A:…, B:…}
  answer       MEDIUMTEXT   NOT NULL,
  explanation  MEDIUMTEXT,
  difficulty   VARCHAR(16)  NOT NULL DEFAULT 'medium',  -- easy / medium / hard
  created_by   VARCHAR(64)  NOT NULL DEFAULT '',   -- 预置='system'，老师/管理员添加填其 id
  created_at   DOUBLE       NOT NULL,
  KEY idx_question_kp (kp_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 班级订阅学科包（老师给班级启用哪个学科包）
CREATE TABLE IF NOT EXISTS dt_class_subject (
  clase_id    VARCHAR(64) NOT NULL,                -- 小智 clase.id
  subject_id  VARCHAR(64) NOT NULL,
  enabled_at  DOUBLE      NOT NULL,
  PRIMARY KEY (clase_id, subject_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 老师布置（关联学科包章节/知识点）
CREATE TABLE IF NOT EXISTS dt_assignment (
  id          VARCHAR(64)  NOT NULL PRIMARY KEY,
  clase_id    VARCHAR(64)  NOT NULL,
  teacher_id  VARCHAR(64)  NOT NULL,
  subject_id  VARCHAR(64)  NOT NULL DEFAULT '',
  module_id   VARCHAR(64)  NOT NULL DEFAULT '',    -- 布置某个章节
  title       VARCHAR(255) NOT NULL,
  description TEXT,
  due_at      DOUBLE       NULL,
  created_at  DOUBLE       NOT NULL,
  KEY idx_assign_class (clase_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 班级学情物化（按学科包知识点聚合，定期生成）
CREATE TABLE IF NOT EXISTS dt_class_report (
  clase_id     VARCHAR(64) NOT NULL,
  kp_id        VARCHAR(64) NOT NULL,               -- 学科包知识点
  total_students INT NOT NULL DEFAULT 0,
  mastered      INT NOT NULL DEFAULT 0,
  in_progress   INT NOT NULL DEFAULT 0,
  wrong_count   INT NOT NULL DEFAULT 0,
  updated_at    DOUBLE NOT NULL,
  PRIMARY KEY (clase_id, kp_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 三、与精通之路（mastery_path）对接

- 学生开始学某学科包时，**从 `dt_subject_module` / `dt_subject_kp` 生成精通之路**：
  - `LearningModule.id = dt_subject_module.id`
  - `KnowledgePoint.id = dt_subject_kp.id`
  - `KnowledgePoint.type = kp_type`
- 精通之路的知识点 id **直接复用学科包 kp_id** → 学情可精确按知识点聚合
- 不再需要 mastery_build 的 AI 自由生成（学科包预置）

## 四、老师带班闭环

```
1. 老师给班级启用学科包        → dt_class_subject
2. 老师布置某章节给班           → dt_assignment（关联 subject/module）
3. 学生开始学（精通之路用学科包）→ mastery 进度按 kp_id 记录
4. 学情聚合                    → dt_class_report（按班级 × 学科包知识点）
5. 老师看班级学情               → 掌握人数 / 进行中 / 错题数
```

权限链（复用已定班级层）：
- 老师只能给**自己 teacher_id 的班级**启用学科包 / 布置 / 看学情
- 学生只能用**自己所在班级启用**的学科包

## 五、与现有体系的关系

| 现有 | 学科包 |
|---|---|
| per-user 书籍 / 题库 / 知识点 | 保留（个人内容）|
| 精通之路（mastery）| 知识点 id 改用学科包 kp_id（预置）|
| 班级层（dt_class / roles）| 老师班级 + 学科包绑定（dt_class_subject）|
| 学情 | 按学科包知识点聚合（dt_class_report）|

## 六、实现路径

1. **阶段一：预置七年级上册内容** —— 建表 + 录入"有理数"一章的知识点图谱 + 首批题库
2. **阶段二：精通之路对接学科包** —— mastery 建路径从学科包生成
3. **阶段三：老师布置** —— dt_assignment + 班级订阅学科包
4. **阶段四：班级学情** —— 按学科包知识点聚合

## 七、待确认项

- **范围**：先做七年级上册（有理数起步）？还是直接铺七年级全册？
- **教材**：对齐人教版？
- **题库来源**：AI 出题审核入库，还是先导入现成初中数学题？
- **知识点图谱**：预置结构人工整理，还是 AI 辅助生成 + 人工校对？
