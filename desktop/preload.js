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

// Preload bridge: exposes a safe, scoped local-file API to the web frontend.
// The renderer accesses window.dtDesktop.*; calls are forwarded to main.js via IPC.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('dtDesktop', {
  listDir: (rel) => ipcRenderer.invoke('dt:listDir', rel),
  readFile: (rel) => ipcRenderer.invoke('dt:readFile', rel),
  writeFile: (rel, content) => ipcRenderer.invoke('dt:writeFile', rel, content),
});
