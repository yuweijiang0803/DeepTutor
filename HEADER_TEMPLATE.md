# Apache-2.0 文件头模板（DeepTutor Fork）

本 fork 基于 DeepTutor（Apache-2.0，HKU Data Intelligence Lab）二次开发。
按 Apache-2.0 §4.b：**任何被修改过的文件必须在文件头显著标注"已被修改"**。

## 一、标准 Apache-2.0 许可头（每个源文件都应带）

### Python（`#` 注释）

```python
# Copyright 2026 yuweijiang0803
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
```

### JavaScript / TypeScript（`//` 注释）

```js
/**
 * Copyright 2026 yuweijiang0803
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
```

### HTML / Vue 模板（`<!-- -->` 注释）

```html
<!--
  Copyright 2026 yuweijiang0803

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->
```

### YAML / SCSS / CSS（`#` 或 `/* */` 注释）

```yaml
# Copyright 2026 yuweijiang0803
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
```

## 二、修改标记（Apache-2.0 §4.b 要求的「突出声明」）

**被修改过的 DeepTutor 文件**，在 Apache 头之上/之下加这一段。格式建议：

### Python

```python
# Modified from DeepTutor (Apache-2.0, https://github.com/HKUDS/DeepTutor).
# Original copyright: 2025 Data Intelligence Lab, The University of Hong Kong.
# This file was modified by yuweijiang0803 for the K12 teaching-engine fork.
# See git history and NOTICE for details.
```

### JavaScript / TypeScript

```js
/**
 * Modified from DeepTutor (Apache-2.0, https://github.com/HKUDS/DeepTutor).
 * Original copyright: 2025 Data Intelligence Lab, The University of Hong Kong.
 * This file was modified by yuweijiang0803 for the K12 teaching-engine fork.
 * See git history and NOTICE for details.
 */
```

### 何时需要加修改标记

| 情况 | 要不要加 |
|------|---------|
| 改动了上游 DeepTutor 的文件 | **必须加**（§4.b） |
| 新建文件（不基于上游代码） | 不加修改标记，但建议带 Apache 许可头 |
| 复制上游文件但完全重写 | 建议加，保险起见 |

## 三、检查清单（每次改上游文件后）

1. 文件头保留/添加 Apache-2.0 许可头
2. 加一行 `Modified from DeepTutor ...` 标记
3. 保留仓库根目录 `LICENSE`（Apache-2.0）和 `NOTICE`
4. 新品牌（产品名/logo）不含 "DeepTutor"、"HKU" 字样
