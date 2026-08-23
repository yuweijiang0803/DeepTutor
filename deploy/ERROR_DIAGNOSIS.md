# 模式二：错题诊断 + 查缺补漏实现方案（ERROR_DIAGNOSIS）

> 目标：从"错题整理"升级为"**错题 → 根源诊断 → 针对性补漏 → 掌握验证**"闭环。
> 是"学习顾问"（LEARNING_ADVISOR）模式二，也是家长价值的关键一环。

## 一、流程总览

```
学生错题本（notebook_entries）
   ↓ ① 一键"诊断薄弱点"
AI 根源诊断：分析错题 → 定位薄弱知识点 + 错因类型
   ↓ ② 诊断结果（存 error_diagnosis）
一键"开始补漏"
   ↓ ③ 补漏闭环（复用精通之路引擎）
AI 讲解薄弱点 → 变式题 → 作答 → 掌握验证（mastery）
   ↓ ④
补漏完成 → 学情/顾问报告消费
```

## 二、数据模型

### 2.1 错题数据（已有，notebook_entries）

已含：question / options / correct_answer / explanation / user_answer /
is_correct / bookmarked / ai_judgment / created_at —— 诊断的输入足够。

### 2.2 诊断记录（新增）

> 放哪：与错题本强关联，**放 per-user SQLite**（notebook_entries 同库）简单；
> 但顾问报告/班级学情需要跨用户聚合，**建议放 MySQL（mixly 库，dt_ 前缀）**。

```sql
CREATE TABLE IF NOT EXISTS dt_error_diagnosis (
  id          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id     VARCHAR(64)  NOT NULL,             -- DeepTutor user id
  kp_id       VARCHAR(64)  NOT NULL DEFAULT '',  -- 薄弱知识点（学科包 kp id，或知识点名）
  kp_name     VARCHAR(255) NOT NULL DEFAULT '',
  cause       VARCHAR(32)  NOT NULL DEFAULT '',  -- 错因：concept / procedure / careless / method / reading
  evidence    MEDIUMTEXT,                        -- 诊断依据（AI 对错题的分析）
  entry_ids   VARCHAR(512) NOT NULL DEFAULT '',  -- 关联错题 ids（逗号分隔）
  status      VARCHAR(16)  NOT NULL DEFAULT 'diagnosed',  -- diagnosed / remediating / mastered
  created_at  DOUBLE       NOT NULL,
  updated_at  DOUBLE       NOT NULL,
  KEY idx_diag_user (user_id, updated_at),
  KEY idx_diag_kp (kp_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 2.3 补漏 = 精通之路（复用已有）

- 薄弱知识点 → 用 `mastery_build` 建一段精通之路（或直接创建 path）
- 补漏进度/掌握度 = mastery 引擎已有数据，**不新增表**
- `dt_error_diagnosis.status` 记录补漏状态即可

## 三、根源诊断（AI 归因）

### 输入
- 错题集（question / user_answer / correct_answer / explanation）
- 学科包知识点图谱（dt_subject_kp，映射错题到知识点）

### 输出（结构化 JSON）
```json
{
  "kp_id": "math7_m1_kp4",
  "kp_name": "绝对值",
  "cause": "concept",
  "evidence": "3 道错题均涉及 |a| 与 -a 的关系混淆，且同类变式仍错",
  "suggestion": "先补绝对值几何意义，再做符号类变式题"
}
```

### 错因分类（影响补漏策略）
| cause | 含义 | 补漏策略 |
|---|---|---|
| `concept` | 概念不理解 | 讲解 + 概念辨析题 |
| `procedure` | 步骤/方法不会 | 步骤拆解 + 分步练习 |
| `careless` | 粗心（计算/符号）| 规范训练 + 检验习惯 |
| `method` | 思路/方法不当 | 方法引导 + 变式迁移 |
| `reading` | 审题不清 | 圈关键词 + 题意重述 |

## 四、补漏闭环（复用精通之路引擎）

```
薄弱知识点
  ↓ 建精通之路（mastery_build，知识点 = 诊断出的 kp）
AI 讲解（EXPLAIN）→ 变式题（mastery_quiz 出题）→ 作答（ask_user）
  ↓ mastery_grade 批改
达标 → 掌握验证 → dt_error_diagnosis.status = 'mastered'
未达标 → 继续打磨 / 换错因策略
```

- 变式题来源：学科包题库（dt_subject_question）+ AI 现场生成
- 补漏完成标准：mastery 门控通过（知识点 mastered）

## 五、前端（错题本加"诊断/补漏"）

`/space/questions`（已有错题本）新增：
1. **"诊断薄弱点"按钮**（错题集 → 触发诊断）
2. 诊断结果卡片：薄弱点 + 错因 + 证据 + 建议
3. **"开始补漏"按钮** → 跳精通之路补救（或弹窗内直接补）
4. 补漏后状态回显（已掌握 / 仍在补）

## 六、API（新增）

```
POST /api/v1/error-diagnosis/diagnose      → 对错题集做根源诊断，返回薄弱点
GET  /api/v1/error-diagnosis               → 诊断历史
POST /api/v1/error-diagnosis/{id}/remediate → 开始补漏（建精通之路）
GET  /api/v1/error-diagnosis/{id}          → 补漏状态/结果
```

## 七、与顾问报告衔接

`dt_error_diagnosis`（薄弱点 + 错因 + 补漏状态）+ mastery 掌握度 + 学习轨迹
→ 学习顾问报告的"薄弱诊断"部分的数据来源。

## 八、实现步骤

1. **数据层**：dt_error_diagnosis 建表 + CRUD API
2. **诊断 agent**：AI 归因（错题 → 知识点 + 错因），复用现有 LLM agent 机制
3. **补漏闭环**：诊断结果 → mastery_build 建路径 → 走精通之路
4. **前端**：错题本加"诊断/开始补漏"入口 + 结果展示
5. **衔接**：顾问报告消费诊断数据

## 九、待确认

- **诊断触发**：手动（学生点）还是自动（错题积累 N 道自动诊断）？
- **补漏范围**：一次补一个薄弱点，还是多个？
- **变式题**：优先学科包题库，还是 AI 现场生成 + 人工审核？
- **诊断记录存储**：MySQL（利于聚合/顾问报告）还是 per-user SQLite？
