# 本地启动 DeepTutor（Web 端）

> 已验证可用的本地运行方式。环境：macOS，conda `dt` 环境（Python 3.12.13），Node v24（nvm）。
> DeepTutor 要求 `Python >=3.11,<3.14`；系统自带 3.9.6 太旧、conda base 3.14.6 太新，故用独立 `dt` 环境。

## 1. 准备环境（只需一次）

```bash
# 建 Python 3.12 环境（conda 默认频道需先接受 ToS）
source /Users/heyuanlin/miniconda3/etc/profile.d/conda.sh
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
conda create -n dt python=3.12 -y

# 装 DeepTutor（CLI 依赖即可跑后端+前端；已装可跳过）
conda activate dt
cd /Users/heyuanlin/Documents/DeepTutor
pip install -e ".[cli]"

# 装前端依赖（Next.js，已装可跳过）
cd web && npm install
```

## 2. 启动（推荐：前后端分开，便于单独重启）

开两个终端：

```bash
# 终端 1 — 后端（需 dt 环境）
source /Users/heyuanlin/miniconda3/etc/profile.d/conda.sh && conda activate dt
cd /Users/heyuanlin/Documents/DeepTutor
deeptutor serve                      # uvicorn，端口读 system.json → 8001

# 终端 2 — 前端（只需 Node，v24 已在 PATH，不用 conda）
cd /Users/heyuanlin/Documents/DeepTutor/web
npm run dev                          # 默认端口 3000
# 或显式保持与 launcher 约定一致：npm run dev -- --port 3782
```

浏览器打开：
- 前端 `http://localhost:3000`（或 `http://localhost:3782`）
- 后端 `http://localhost:8001`

> 前端端口与后端独立：`web/proxy.ts` 把 `/api`、`/ws` 代理到 `next_public_api_base`，
> 该项在 `data/user/settings/system.json` 中为空 → 默认指向 `http://localhost:8001`。
> 所以前端换端口（3000/3782）不影响连后端。不写 `--port` 时 `next dev` 默认 3000。

## 3. 一键启动（两端一起，含健康检查）

```bash
source /Users/heyuanlin/miniconda3/etc/profile.d/conda.sh && conda activate dt
cd /Users/heyuanlin/Documents/DeepTutor
deeptutor start --dev                # 后端(:8001) + 前端(:3782) 一起拉起
```
`--dev` 走 Next dev server（自动 `npm install`）；不带 `--dev` 则需先 `npm run build`（更慢）。

## 4. 配置 LLM（对话可用前必须）

界面能打开，但没 key 发消息会报错。二选一：
- 命令行：`deeptutor init` → 选 DeepSeek(OpenAI兼容) → 粘贴 `sk-...`
- 界面内：**Settings → 添加 Provider**（DeepSeek / 通义 / GLM 均可）

推荐 DeepSeek（国产、便宜、有推理模型、原生支持）。

## 5. 停止

```bash
for p in 3782 8001; do lsof -ti tcp:$p 2>/dev/null | xargs -r kill -9; done
```

## 6. 注意事项

- 当前 **auth 默认关闭、单用户模式**：打开即用、无需登录 —— 仅限本地验证，**不可对外暴露**（未成年人产品上线前必须打开 auth + 硬化多用户安全）。
- `deeptutor start --dev` 是长驻进程，`Ctrl+C` 会连同后端一起停。
- 配置/端口在 `data/user/settings/system.json`（`backend_port` / `frontend_port` / `next_public_api_base` 等，改动后重启生效）。

## 7. 打包成 PC 桌面端（Electron 壳，可选）

把 Web 前端包成桌面应用（**不打包 Python 后端**），分发给别人当 PC 客户端用。
详细见 `desktop/README.md`，要点：

```bash
cd /Users/heyuanlin/Documents/DeepTutor/desktop
npm install
npm run dist:mac      # 打 macOS dmg（arm64+x64），自动内嵌 node，无需用户装 node
# npm run dist:win    # 打 Windows nsis
# npm run dist:linux  # 打 Linux AppImage
```

- 产物在 `desktop/dist-electron/`。包内已带 node，发给没装 node 的机器也能跑。
- **未签名**：本机/内测可直接开；广散或学校分发前需签名+公证（占位见 `desktop/electron-builder.yml`）。
- ⚠️ 壳只含前端，**不含 LLM 后端**：发出去的客户端界面能开，但对话需另接你服务器上的后端。学生使用记录也需由该后端落库（本地单用户模式不存）。


