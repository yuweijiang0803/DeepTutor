# 整页拍照错题提取方案（PAGE_CAPTURE）

> 目标：学生拍一张练习册**整页照片**（含多道题、批改痕迹、几何配图），
> 系统自动识别每题区域 → **裁剪每题小图（含题目配图）** → 判错 → 用户确认 → 逐题入库。
>
> 几何题配套图是题目的一部分，必须保留在每题小图里，不能只存文本转录。

## 一、流程总览

```
学生上传整页照片
   ↓ ① 上传（复用附件机制，整页原图存 AttachmentStore）
前端预览整页图
   ↓ ② 调整页分析 API
视觉 LLM 分析 → 输出结构化 JSON（每题：题号 / 区域 bbox / 判错 / 题目文本）
   ↓ ③ 前端渲染：整页图上叠加每题"识别框" + 判错标记
用户确认/修正（勾选错题、微调识别框、修正题目文本）
   ↓ ④ 前端按 bbox 用 canvas 裁剪每题小图 → 上传小图
后端逐题入库（notebook_entries：题目文本 + 裁剪小图引用 + 判错 + 知识点/错因）
```

## 二、区域检测（视觉 LLM 输出 bbox）

### 2.1 一次调用输出全部题目

整页图给视觉 LLM，Prompt 要求输出：

```json
{
  "questions": [
    {
      "number": 1,
      "bbox": [0.12, 0.15, 0.48, 0.38],
      "is_wrong": true,
      "text": "如图，在△ABC中，AB=AC…",
      "has_figure": true
    }
  ]
}
```

- `bbox`：**归一化坐标** `[x, y, w, h]`（0-1，相对整页），前端按实际尺寸渲染
- `bbox` 必须**包含题目的配套图**（几何图形通常紧挨题目，Prompt 明确要求框住题干+配图）
- `is_wrong`：LLM 识别批改痕迹（红叉/订正）判断，**仅供参考，需用户确认**
- `text`：题目文本转录（用于检索/分析；小图保留原样）

### 2.2 精度风险与缓解

LLM 输出的 bbox 可能偏差（±2-5%），几何配图可能被切边。缓解：

1. **前端可微调**：识别框渲染后用户可拖拽/缩放（关键保障）
2. **裁剪留白**：按 bbox 裁剪时四周扩展 2%（避免切到文字/图形边缘）
3. **归一化坐标**：与整页实际像素解耦，缩放不失真

## 三、裁剪（前端 canvas）

- **前端裁剪**（不是后端）：用户确认时实时预览裁剪效果，所见即所得
- 用 `<canvas>` 按 bbox（+2% 留白）从整页图裁剪 → `toBlob` 生成每题小图
- 裁剪小图上传 → AttachmentStore → 得到每题小图的附件引用

## 四、判错 + 用户确认

| 步骤 | 说明 |
|---|---|
| LLM 判错 | 识别红叉/订正痕迹，标 `is_wrong`（不 100% 可靠） |
| 用户确认 | 前端每题显示小图 + "错题"勾选框（默认按 LLM 判断） |
| 修正 | 用户可调整勾选、微调识别框、编辑题目文本 |

**LLM 判错仅是预填，用户确认是入库依据。**

## 五、数据存储

### 5.1 整页原图

- 附件机制存 `AttachmentStore`（现有 `/api/attachments/...`）
- 前端消息里作为图片附件

### 5.2 每题错题记录（复用 notebook_entries）

| 字段 | 内容 |
|---|---|
| `question` | 题目文本（LLM 转录，用户可改） |
| `is_correct` | 0（错题）|
| `user_answer_images_json` | **裁剪小图引用**（每题小图） |
| `question_type` | 几何/计算/应用等（LLM 判断） |
| `ai_judgment` | 错因初判（LLM 生成，后续诊断精修） |
| `knowledge_point` | 知识点（MySQL 有字段；SQLite 需加列，见 §七） |

裁剪小图引用格式（沿用现有 images 记录）：
```json
[{"id": "img_xxx", "url": "/api/attachments/{session}/{id}/xxx.png", "session_id": "…"}]
```

## 六、API 设计

### 6.1 整页分析

```
POST /api/v1/question-notebook/analyze-page
  body: { image_attachment_id, session_id }
  → { questions: [{number, bbox, is_wrong, text, has_figure, question_type}] }
```

实现：取整页图 → 视觉 LLM（豆包视觉）→ 结构化 JSON → 校验/规整 bbox。

### 6.2 裁剪小图上传

- 复用现有附件上传 API（`POST /api/attachments/...`），前端裁剪后上传每题小图

### 6.3 批量入库

- 复用 `POST /entries/upsert`（逐题），前端确认后循环调用
- 每题：question + user_answer_images_json（小图引用）+ is_correct=0

## 七、数据模型改动

- **SQLite `notebook_entries` 加 `knowledge_point` 列**（MySQL `dt_notebook_entries` 已有）
- 迁移：`ALTER TABLE notebook_entries ADD COLUMN knowledge_point VARCHAR(255) DEFAULT ''`
- `upsert_notebook_entries` 写入 `knowledge_point`

## 八、前端交互

```
/space/questions 或 聊天对话框
  ├─ "拍照提取错题" 按钮 → 上传整页照片
  ├─ 预览整页 + 每题识别框（LLM 输出）→ 用户微调框
  ├─ 每题卡片：裁剪小图预览 + "错题"勾选 + 题目文本编辑
  └─ "确认入库" → 裁剪上传 → 逐题 upsert → 跳转错题本
```

组件：
- `PageCaptureModal`（上传 + 整页预览 + 识别框微调 + 每题确认）
- `CropCanvas`（按 bbox 裁剪）
- 后端 `analyze-page` 端点 + LLM prompt

## 九、实施阶段

| 阶段 | 内容 |
|---|---|
| **P0** | 整页分析 API + LLM prompt（输出题号/bbox/判错/文本）+ 前端上传预览 + 识别框展示 |
| **P1** | 前端裁剪小图（canvas）+ 每题确认入库 + `knowledge_point` 列 |
| **P2** | 识别框微调（拖拽/缩放）+ 错因初判（ai_judgment）+ 知识点自动标注 |

## 十、风险

1. **LLM bbox 精度**：最不可控环节 → 前端微调框是必须的兜底
2. **判错可靠性**：红叉/批改痕迹识别不稳 → 用户确认步骤不可省
3. **几何配图被切**：裁剪留白 + 用户微调解决
4. **图片上传体积**：整页图可能较大 → 前端压缩后上传

## 十一、一句话总结

**拍整页 → 视觉 LLM 一次识别出每题（题号/区域/判错）→ 前端显示识别框供微调 → canvas 裁剪每题小图（含几何配图）→ 用户确认判错 → 逐题入库。**
核心保障：**前端可微调识别框 + 裁剪留白**，解决 LLM 区域精度问题。
