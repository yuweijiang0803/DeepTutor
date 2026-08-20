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
