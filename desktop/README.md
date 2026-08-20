# DeepTutor 桌面壳（Electron，可行性验证 + 打包）

把 DeepTutor 的 **Web 前端**包成桌面应用，**不打包 Python 后端**。用于验证「前端能不能包成 PC 端、能不能读本地文件」，并产出可分发的安装包。

## 两种加载方式（自动选择）

1. **已构建 standalone**：若 `../web/.next/standalone/server.js` 存在，壳会在内部启动 Next 自带的服务，直接加载。无需额外服务器。
2. **外部 dev server**：否则加载 `http://127.0.0.1:3782`（即你手动 `npm run dev` 起的 web）。

## 本地运行（开发）

```bash
# 方式 A：直接用 dev server（最快看到效果，无需构建）
cd ../web && npm run dev          # 终端 1：起前端
cd desktop && npm install         # 终端 2：装 electron（首次）
npm start                        # 终端 2：打开桌面窗

# 方式 B：构建后完全打包（前端内嵌，不需要 dev server）
cd ../web && npm run build        # 构建 standalone
cd desktop && npm install
npm start                        # 壳内部起 standalone 服务并加载
```

## 打包成安装包（electron-builder）

```bash
cd desktop && npm install                       # 安装 electron + electron-builder
npm run dist:mac                                # 打 macOS dmg（arm64 + x64），自动内嵌 node
# npm run dist:win   打 Windows nsis（自动内嵌 node，无需用户装 node）
# npm run dist:linux 打 Linux AppImage
```

- `dist:*` 会自动依次：`bundle:node`（把当前 node 二进制拷进 `resources/`）→ `build:web`（构建前端并把 static/public 拷进 standalone）→ electron-builder。
- 产物在 `desktop/dist-electron/`。
- **内嵌 Node**：包里已带 node 二进制（`resources/node` 或 `node.exe`），所以发给**没装 node 的机器也能跑**（尤其是 Windows 用户）。`main.js` 自动优先用打包内的 node，回退到系统 node。
- **未签名**：没有开发者证书时打出的 dmg/exe 未签名，本机/内测可直接开（macOS 需「允许任何来源」或右键打开），广散或学校分发前需签名 + 公证（占位见 `electron-builder.yml`）。
- 配置见 `electron-builder.yml`（appId / 分类 / 各平台 target / 签名占位）。

## 本地文件读取（脚手架）

`main.js` 里已实现最小 IPC 桥：`window.dtDesktop.listDir / readFile / writeFile`。
当前 demo 范围：

- 读/列目录：限制在用户主目录（`os.homedir()`）
- 写文件：限制在应用数据目录（`app.getPath('userData')`）

生产化时：读目录应改为用户主动选择的文件夹（需明确同意），且绝不写到应用目录之外。

## 打包后 node 依赖说明

壳内部用 `node` 起 standalone 服务。现在打包时会自动把 node 二进制内嵌进 `resources`，所以发给**没有 node 的机器也能直接跑**（尤其 Windows 用户不需要自己装 node）。`main.js` 自动优先用打包内的 node，回退到系统 node（`DESKTOP_NODE_BIN` 可强制指定）。

> 注意：本壳不含 LLM 后端，界面能开，但发消息/调用 API 需另接后端（部署在你的服务器）。
