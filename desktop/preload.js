// Preload bridge: exposes a safe, scoped local-file API to the web frontend.
// The renderer accesses window.dtDesktop.*; calls are forwarded to main.js via IPC.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('dtDesktop', {
  listDir: (rel) => ipcRenderer.invoke('dt:listDir', rel),
  readFile: (rel) => ipcRenderer.invoke('dt:readFile', rel),
  writeFile: (rel, content) => ipcRenderer.invoke('dt:writeFile', rel, content),
});
