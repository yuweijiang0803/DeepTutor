# DeepTutor 项目全面分析

> 生成日期：2026-08-20 · 分析基于 git HEAD `v1.5.14` (7c6bcfae) 与源码静态探查

## 0. 项目概况

**DeepTutor: Lifelong Personalized Tutoring** — 香港大学数据科学团队（HKUDS）出品的「智能学习伴侣」。当前版本 **v1.5.14**（2026.8.19，代号 *Immersive Reading*），Apache 2.0，有 arXiv 论文（2604.26962）、Trendshift 排名、11 种语言文档。

它是一个 **agent-native** 的学习系统，围绕「两层插件模型」（单功能 Tools + 多阶段 Capabilities）组织，对外暴露三个入口：CLI、WebSocket API、Python SDK。

---

## 1. 规模与代码分布

| 目录 | 代码量 | 说明 |
|------|--------|------|
| `deeptutor/` | ~173K 行 Python | 核心运行时、工具、能力、服务 |
| `web/` | ~121K 行 TS/Next.js | 前端（React 19 + Next.js 16） |
| `tests/` | ~84K 行 | 约 399 个测试文件，覆盖极广 |
| `deeptutor_cli/` | ~5K 行 | Typer CLI 入口 |

合计 **约 38 万行**，1172 个 Python 文件。这是一个**体量很大、工程成熟度很高**的项目，迭代节奏极强（v1.4→v1.5 几乎每天一个 release）。

---

## 2. 整体架构（核心设计思想）

核心是一个 **两层插件模型**，三个入口收敛到同一运行时：

```
CLI (Typer)  │  WebSocket /api/v1/ws  │  Python SDK
      └──────────┬─────────────────────┘
          ChatOrchestrator  (runtime/orchestrator.py:36)
                 ├─ ToolRegistry        (Level 1: 单功能工具)
                 └─ CapabilityRegistry  (Level 2: 多阶段流水线能力)
                 └─ StreamBus 事件扇出 → 消费者
```

- **Level 1 Tools**：LLM 按需调用的单功能工具（brainstorm / web_search / paper_search / reason + 上下文自动挂载的 rag / memory / exec / github / cron 等）。
- **Level 2 Capabilities**：接管整轮的流水线能力（chat / mastery_path / deep_solve / deep_question / deep_research / visualize / math_animator）。
- 所有能力最终汇聚到 `emit_capability_result()`（`capabilities/_shared.py`），输出统一信封（响应 + `cost_summary`）。状态文案和 prompt 经 i18n（`prompts/{en,zh}/`）。

---

## 3. 核心运行时亮点

- **统一入口**：三个入口都调用 `ChatOrchestrator.handle(context)` → 解析 `active_capability`（默认 `chat`）→ 建每轮 `StreamBus` → 以 asyncio task 跑 `capability.run` → 扇出为 `AsyncIterator[StreamEvent]`。
- **单一 Agentic Loop**：`core/agentic/loop.py:173` 的 `run_agentic_loop` 是所有能力的公共引擎，通过 `LabelProtocol`（allowed/terminal/final/tool 标签）驱动，`labeled_step.py` 从流式输出首块解析 `LABEL` 前缀做路由。这是架构上最优雅的一点——一个循环复用给 7 种能力。
- **事件系统**：`StreamEvent`（16 种类型）+ `StreamBus`（`asyncio.Queue` 订阅、历史回放、`stage/content/tool_call/wait_for_input` 辅助方法）。
- **工具选择非 LLM 决定**：`compose_enabled_tools`（`agents/_shared/tool_composition.py:145`）基于 `ToolMountFlags`（有无 KB、附件、沙箱…）策略性地挂载，LLM 只通过 OpenAI function-calling schema「挑选」已挂载的工具；`can_use_native_tool_calling` 决定走原生还是文本回退。延迟工具用 `load_tools` 渐进披露。

---

## 4. 知识库 / RAG

`KnowledgeBaseManager`（`knowledge/manager.py`）管理，存储于 `data/knowledge_bases`（按用户隔离）。

- **KB 类型**（`kb_types.py`）：indexed（默认，chunk→embed→retrieve）、obsidian（实时 Markdown 目录）、linked（挂载 LlamaIndex/GraphRAG/LightRAG）、subagent、lightrag_server（HTTP `/query`）、ima（腾讯 IMA）。
- **RAG 后端**（`services/rag/factory.py`）：llamaindex（默认，本地向量+BM25）、pageindex、graphrag、lightrag、lightrag-server、ima。
- 这是一个**极其灵活但复杂**的检索层，外部 KB（LightRAG/IMA 服务器）信任外部 HTTP 端点。

---

## 5. 记忆系统（三层）

`services/memory/`：

- **L1 trace** — 各 surface 追加事件流；
- **L2 / L3 docs** — L2 单 surface，L3 跨 surface（最近/画像/范围/偏好）。`MemoryStore` 无状态，隔离靠 `paths.memory_root` 按 ContextVar 用户解析；
- **recall**（`recall.py`）— 只读快照时间戳，不载正文，用于高频路径；snapshot/consolidator 周期性合并 L1→L2。
- 最近提交大量围绕「home starter chips 由 L3 + 近期活动生成」「recall 跨 surface」——这是当前活跃方向。

---

## 6. 多用户与安全

- 默认**关闭** auth；开启时 JWT(HS256) + bcrypt，用户存 `data/system/auth/users.json`。**首个注册者自动成为 admin**（但仅是进程内锁，`identity.py` 已注明多 worker 并发可竞态，需外部存储）。
- **租户隔离**：`data/user`、`data/users/<uid>`、`data/partners/<id>`、`data/system` 分目录。`knowledge_access.py` 强制 `admin:kb:`/`user:kb:` 前缀；用户只见自己 KB + 管理员只读分配的。
- **Grants**：管理员按用户分配 model/KB/skill/partner/tool/mcp/cli_app/exec；**mcp_tools / cli_apps 默认拒绝**（第三方代码风险缓解）。
- **每 owner 密钥** `data/system/user-secrets`，刻意排除在沙箱挂载外。
- 风险点：auth off 时 single-user 静默变为 `local_admin`，多用户隔离回退到 admin workspace。

---

## 7. 入口与前端

- **CLI**（`deeptutor_cli/main.py`）：Typer，子命令 `run/chat/kb/skill/memory/plugin/config/session/notebook/provider/book/partner`。CLI 与 REPL **进程内直连运行时**，不走 HTTP/WS。
- **WebSocket**（`api/routers/unified_ws.py`，`/api/v1/ws`）：消息契约 `start_turn / subscribe_turn / submit_user_reply / regenerate / cancel_turn / user_input …`；auth 必须在 `ws.accept()` 前手写（`ws_require_auth`，FastAPI 依赖不作用于 WS）；`safe_send` 用 `default=str` 防止单个坏事件冻结 socket。
- **Python SDK**：`app/facade.py` 的 `DeepTutorApp` + `TurnRequest` 是三者共享桥。
- **前端**：`web/` 是 **Next.js 16 + React 19 + TS + Tailwind 3**，同源经 Next 中间件代理 `/api/*`、`/ws/*` 到后端（`proxy.ts`）。部署时因 Next public 变量内联，需 launcher 启动期打补丁（`_patch_packaged_web_placeholders`）。
- **Launcher**（`runtime/launcher.py:935`）：起后端 uvicorn + 前端（Node `server.js` 或 `next dev`），自动解端口冲突、健康探测、信号优雅关闭。

---

## 8. 合作伙伴 / IM

`partners/channels/` 自动发现（pkgutil + entry_point 插件）。内置 **15+ 通道**：matrix（带 E2E 选项）、feishu、weixin、dingtalk、wecom、telegram、discord、slack、msteams、email、whatsapp、zulip 等。伙伴是管理员隔离的「合成用户」，可带自己 persona/记忆/技能在对话中实时咨询。

---

## 9. 构建 / 部署

- **两个分发包**：`deeptutor`（全量，含打包的 Next 资源 `deeptutor_web`）、`deeptutor-cli`（仅 CLI，不发布 PyPI）。setuptools 构建，`requires-python>=3.11,<3.14`（faiss-cpu 缺 3.14 wheel）。
- **Extras** 镜像依赖组：cli/server/partners/matrix/math-animator/dev/all，外加 codebuddy/graphrag/rag-lightrag/parse\*。**注意 `all` 故意不含 codebuddy/graphrag/rag-lightrag**。
- **Docker**：`Dockerfile` 多阶段（node:22 → python:3.11-slim → production/development），supervisord 以非 root UID 1000 同时跑后端+前端；`Dockerfile.runner` 是最小**沙箱 sidecar**，只跑 `sandbox/runner/server.py` 执行不可信代码，与主体隔离。Compose 有 Podman(`compose.yaml`) 与 Docker(`docker-compose.yml`) 两套拓扑。GHCR 多平台 + SBOM + provenance。
- **CI**：tests(ruff + node + pytest 3.11–3.13 + 3.14 best-effort)、docker-release、pypi-release(**PyPI Trusted Publishing / OIDC 无 token**)、repo-hygiene。

---

## 10. 测试与质量

- 约 **399 测试文件**，覆盖 runtime/core/agents/capabilities/knowledge/multi_user/partners/cli/book/scripts/reading/utils。`conftest.py` 有强 autouse 守卫（防测试触碰真实密钥树、遗留迁移、CodeBuddy 登录）。
- **Lint 偏宽松**：ruff 仅 E/F/I + B006、max-complexity 10 且大量 ignore；mypy 宽松；bandit 多处 skip。pre-commit 配 ruff/prettier/detect-secrets(`.secrets.baseline` 377 行)/mypy。**pip-audit/safety 被禁用**（注释称 Windows 非 ASCII bug）。

---

## 11. 综合评价

### 优势

- 架构清晰优雅：两层插件 + 注册表 + 单一 agentic loop 复用，三入口收敛到 `DeepTutorApp` 门面。
- 工程纪律强：极广测试、OIDC 发布、SBOM/provenance、detect-secrets 基线、沙箱 sidecar 隔离、MCP/CLI 默认拒绝。
- 功能纵深惊人：RAG 多后端、三层记忆、15+ IM 通道、多用户租户隔离、Matplotlib/Manim 可视化、Book 生成、Codex OAuth。
- 迭代飞快、文档多语言完善。

### 风险 / 维护成本

1. **依赖膨胀**：基础 wheel 直接拉 anthropic、llama-index、faiss、PyMuPDF、mcp 等，镜像大、冷启动慢。
2. **双源真相**：`pyproject.toml` 与 `requirements/*.txt` 并存（靠注释「保持同步」缓解漂移）。
3. **脆弱 pins**：`pdfplumber<0.11.8`（避 mineru 冲突）、`<3.14` 上限带来近期 EOL 暴露。
4. **多用户注册竞态**：admin 晋升仅靠进程内锁，多 worker 不安全。
5. **auth 默认关**：单用户静默沦为 local-admin，隔离语义回退。
6. **lint 松弛 + 大代码面**：静态保障有限，长尾 bug 靠测试兜底。
7. **两套 compose 拓扑 + Next 占位符启动期打补丁**：运维复杂度偏高。

### 定位总结

一个由学术团队驱动、已具备产品级工程素养、但为追求广度而背负显著依赖与运维复杂度的「AI 学习 OS」。最值得借鉴的是它的**插件 / 事件 / 单一循环架构**；最需警惕的是**依赖与多用户安全模型的长期成本**。
