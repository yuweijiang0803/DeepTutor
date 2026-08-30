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

// Copies the Node binary that runs this script into desktop/resources/ so the
// packaged Electron app can launch the Next standalone server on machines that
// do NOT have Node installed (e.g. most Windows users).
//
// The copied binary keeps its platform-native name (node on macOS/Linux,
// node.exe on Windows) so main.js can find it. Run this BEFORE electron-builder
// (it is wired into the dist:* npm scripts).

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const resourcesDir = path.join(__dirname, 'resources');
fs.mkdirSync(resourcesDir, { recursive: true });

// 跨平台构建：在 mac/Linux 上构建 Windows 版时，本机 node 是 mac/linux 二进制，
// 复制过去 Windows 无法运行。所以 --win 时改为下载 Windows x64 node.exe。
if (process.argv.includes('--win')) {
  // 清理之前复制进来的本机（mac/linux）node，避免它被一并打包进 win 包
  for (const f of ['node', 'node.exe']) {
    const p = path.join(resourcesDir, f);
    if (fs.existsSync(p)) {
      fs.rmSync(p, { force: true });
      console.log(`[bundle-node] removed ${p}`);
    }
  }
  const ver = process.versions.node;
  const url = `https://nodejs.org/dist/v${ver}/win-x64/node.exe`;
  const dest = path.join(resourcesDir, 'node.exe');
  console.log(`[bundle-node] downloading Windows node.exe v${ver} ...`);
  (async () => {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`download failed: HTTP ${res.status} ${url}`);
    const buf = Buffer.from(await res.arrayBuffer());
    fs.writeFileSync(dest, buf);
    fs.chmodSync(dest, 0o755);
    console.log(`[bundle-node] saved ${dest} (${(buf.length / 1024 / 1024).toFixed(1)} MB)`);
  })().catch((e) => {
    console.error('[bundle-node] ERROR downloading Windows node:', e.message);
    process.exit(1);
  });
  return;
}

// process.execPath is the node binary running this script.
const src = process.execPath;
const dest = path.join(resourcesDir, path.basename(src));

fs.copyFileSync(src, dest);
// Ensure executable bit (matters on macOS/Linux).
fs.chmodSync(dest, 0o755);

// Sanity: confirm the copied binary actually runs and reports a version.
let version = '';
try {
  version = execFileSync(dest, ['--version']).toString().trim();
} catch (e) {
  console.error('[bundle-node] WARNING: copied binary did not run:', e.message);
}
console.log(`[bundle-node] copied ${src} -> ${dest} ${version}`);
