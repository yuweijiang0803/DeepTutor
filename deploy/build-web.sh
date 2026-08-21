#!/bin/bash
# 构建 DeepTutor 前端（Next standalone）并打包进 ./deeptutor-web（供服务器部署）
#
# 用法：
#   cd /Users/heyuanlin/Documents/DeepTutor
#   bash deploy/build-web.sh
#
# 产物：deeptutor-web/（自包含：server.js + node_modules + .next/static + public）
# 之后 rsync deeptutor-web 到服务器 /app/xzserver/deeptutor-web

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB="$ROOT/web"
OUT="$ROOT/deeptutor-web"

echo "[1/3] npm run build ..."
cd "$WEB"
npm run build

STANDALONE="$WEB/.next/standalone"
if [ ! -f "$STANDALONE/server.js" ]; then
    echo "错误: 未找到 $STANDALONE/server.js（检查 web/next.config.js 的 output 配置）" >&2
    exit 1
fi

echo "[2/3] 组装 deeptutor-web/ ..."
rm -rf "$OUT"
mkdir -p "$OUT"
cp -R "$STANDALONE/." "$OUT/"

# Next standalone 需要 .next/static 和 public 跟随（同 desktop 壳的做法）
if [ -d "$WEB/.next/static" ]; then
    mkdir -p "$OUT/.next"
    cp -R "$WEB/.next/static" "$OUT/.next/static"
fi
if [ -d "$WEB/public" ]; then
    cp -R "$WEB/public" "$OUT/public"
fi

echo "[3/3] 完成: $OUT"
du -sh "$OUT"
