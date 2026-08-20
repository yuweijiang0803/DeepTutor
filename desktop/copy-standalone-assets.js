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
