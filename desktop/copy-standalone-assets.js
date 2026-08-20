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

// Copies Next build artifacts into the standalone server dir so it is self-contained.
// The standalone server (web/.next/standalone/server.js) needs .next/static and public
// alongside it. `next build` only emits them under .next/static and public, so we copy.
const fs = require('fs');
const path = require('path');

const webRoot = path.resolve(__dirname, '..', 'web');
const standalone = path.join(webRoot, '.next', 'standalone');

function cpSync(src, dest) {
  if (!fs.existsSync(src)) return;
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.cpSync(src, dest, { recursive: true });
}

cpSync(path.join(webRoot, '.next', 'static'), path.join(standalone, '.next', 'static'));
cpSync(path.join(webRoot, 'public'), path.join(standalone, 'public'));
console.log('[copy-standalone-assets] static + public copied into .next/standalone');
