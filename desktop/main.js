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

// Minimal Electron shell for the DeepTutor web frontend.
// Loads the frontend two ways, in order of preference:
//   1. A built Next standalone server (web/.next/standalone/server.js) — fully packaged, no external server needed.
//   2. An external dev server URL (default http://127.0.0.1:3782) — for quick iteration.
// The Python LLM backend is NOT bundled; chat/API calls need a backend elsewhere.

const { app, BrowserWindow, ipcMain } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const net = require('net');

const WEB_DIR = path.join(__dirname, '..', 'web');
const STANDALONE = app.isPackaged
  ? path.join(process.resourcesPath, 'web-standalone')
  : path.join(WEB_DIR, '.next', 'standalone');
const PORT = Number(process.env.DESKTOP_PORT || 4782);
const EXTERNAL_URL = process.env.WEB_URL || 'http://127.0.0.1:3782';
// 默认后端：用户自己的服务器（数据存服务器）。前端 /api 请求由 proxy 转发
// 到这里。部署/分发时可把此值改成正式后端域名；用户可用环境变量
// DEEPTUTOR_API_BASE_URL 临时覆盖（如连本地后端调试）。
const DEFAULT_BACKEND_URL = 'https://tutor.hourofai.cn';
// Resolve the Node binary used to launch the standalone server.
//  1. explicit override (DESKTOP_NODE_BIN)
//  2. node bundled inside the package (works on machines with no system node)
//  3. bare 'node' — only safe in a terminal launch where PATH includes node;
//     a GUI-launched .app has a minimal PATH, so this can fail with ENOENT.
function resolveNodeBin() {
  if (process.env.DESKTOP_NODE_BIN && fs.existsSync(process.env.DESKTOP_NODE_BIN)) {
    return process.env.DESKTOP_NODE_BIN;
  }
  if (app.isPackaged) {
    const base = path.join(process.resourcesPath, 'node');
    // Windows 优先 node.exe（避免命中误打包进来的无扩展名 mac node）
    const cands =
      process.platform === 'win32'
        ? [`${base}.exe`, base]
        : [base, `${base}.exe`];
    for (const cand of cands) {
      if (fs.existsSync(cand)) return cand;
    }
  }
  return 'node';
}
const NODE_BIN = resolveNodeBin();
console.log(`[desktop] standalone server node: ${NODE_BIN}`);

let serverProc = null;

function startStandaloneServer() {
  const serverJs = path.join(STANDALONE, 'server.js');
  if (!fs.existsSync(serverJs)) return false;
  // 让 standalone 前端的 /api 请求默认连服务器（数据存服务器）；环境变量可覆盖。
  if (!process.env.DEEPTUTOR_API_BASE_URL) {
    process.env.DEEPTUTOR_API_BASE_URL = DEFAULT_BACKEND_URL;
  }
  serverProc = spawn(NODE_BIN, [serverJs], {
    cwd: STANDALONE,
    env: { ...process.env, PORT: String(PORT), HOSTNAME: '127.0.0.1', NODE_ENV: 'production' },
    stdio: 'inherit',
    // Windows 上隐藏 node.exe（控制台程序）的黑色终端窗口
    windowsHide: true,
  });
  serverProc.on('exit', (code) => console.log(`[web-standalone] exited ${code}`));
  return true;
}

function waitForPort(cb) {
  const sock = net.connect(PORT, '127.0.0.1');
  sock.on('connect', () => { sock.destroy(); cb(); });
  sock.on('error', () => { sock.destroy(); setTimeout(() => waitForPort(cb), 300); });
}

// --- 自动更新（electron-updater）---
// 仅打包后启用；开发模式跳过。更新源在 electron-builder.yml 的 publish。
// 平台差异：
//   • Windows/Linux：检测到新版自动下载 → 自动重启安装（nsis/AppImage 无需签名）。
//   • macOS：Squirrel.Mac 的自动替换安装要求有效 Developer ID 签名，未签名
//     （含 ad-hoc）会校验失败。所以 mac 只检测新版 → 弹窗引导用户去
//     更新页（https://tutor.hourofai.cn/updates/）手动下载 dmg 安装。
function setupAutoUpdater() {
  if (!app.isPackaged) return;
  try {
    // eslint-disable-next-line global-require
    const { autoUpdater } = require('electron-updater');
    const { dialog, shell } = require('electron');

    if (process.platform === 'darwin') {
      // mac：只检测 + 引导手动下载
      autoUpdater.autoDownload = false;
      autoUpdater.on('update-available', async (info) => {
        console.log('[auto-update] mac update available:', info && info.version);
        const { response } = await dialog.showMessageBox({
          type: 'info',
          title: '发现新版本',
          message: `发现新版本 ${info && info.version}，是否前往下载安装？`,
          detail: '下载页面：https://tutor.hourofai.cn/updates/',
          buttons: ['去下载', '稍后'],
          defaultId: 0,
          cancelId: 1,
        });
        if (response === 0) {
          // 带准确架构参数（浏览器 UA 无法区分 mac M1/Intel，process.arch 可靠）
          shell.openExternal(
            'https://tutor.hourofai.cn/updates/?arch=' + process.arch,
          );
        }
      });
    } else {
      // win/linux：自动下载并重启安装
      autoUpdater.autoDownload = true;
      autoUpdater.autoInstallOnAppQuit = false;
      autoUpdater.on('update-downloaded', () => {
        console.log('[auto-update] new version downloaded; installing…');
        autoUpdater.quitAndInstall();
      });
    }
    autoUpdater.on('error', (err) => {
      console.log('[auto-update] error:', err && err.message);
    });
    autoUpdater.on('update-not-available', () => console.log('[auto-update] up to date'));
    // 延迟检查，避免与首屏启动竞争
    setTimeout(() => autoUpdater.checkForUpdates().catch((e) => {
      console.log('[auto-update] check failed:', e && e.message);
    }), 5000);
  } catch (err) {
    console.log('[auto-update] disabled:', err && err.message);
  }
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  const usingStandalone = fs.existsSync(path.join(STANDALONE, 'server.js'));
  if (usingStandalone) {
    waitForPort(() => win.loadURL(`http://127.0.0.1:${PORT}`));
  } else {
    win.loadURL(EXTERNAL_URL);
  }
  return win;
}

// --- Local file access bridge (scaffold for the "read/write local files" goal) ---
// Demo scope: reads/listing limited to the user's home dir; writes limited to the app data dir.
// Production: tighten the read root to a user-chosen folder with explicit consent, and never write outside app data.
const READ_ROOT = os.homedir();
function safeResolve(root, p) {
  const resolved = path.resolve(root, p || '');
  if (resolved !== root && !resolved.startsWith(root + path.sep)) {
    throw new Error('path escapes allowed root');
  }
  return resolved;
}
ipcMain.handle('dt:listDir', async (_e, rel) => {
  const dir = safeResolve(READ_ROOT, rel);
  const entries = await fs.promises.readdir(dir, { withFileTypes: true });
  return entries.map((x) => ({ name: x.name, isDir: x.isDirectory() }));
});
ipcMain.handle('dt:readFile', async (_e, rel) => {
  const file = safeResolve(READ_ROOT, rel);
  return await fs.promises.readFile(file, 'utf8');
});
ipcMain.handle('dt:writeFile', async (_e, rel, content) => {
  const dir = app.getPath('userData');
  const file = safeResolve(dir, rel);
  await fs.promises.mkdir(path.dirname(file), { recursive: true });
  await fs.promises.writeFile(file, content);
  return file;
});

app.whenReady().then(() => {
  startStandaloneServer();
  createWindow();
  setupAutoUpdater();
});

app.on('window-all-closed', () => {
  if (serverProc) serverProc.kill();
  if (process.platform !== 'darwin') app.quit();
});
app.on('before-quit', () => { if (serverProc) serverProc.kill(); });
