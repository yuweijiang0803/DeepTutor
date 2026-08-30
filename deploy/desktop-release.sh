#!/bin/bash
# ============================================================
# DeepTutor 桌面端发版：打包 + 上传自动更新到服务器
#
# 用法：
#   bash deploy/desktop-release.sh mac    仅 mac
#   bash deploy/desktop-release.sh win    仅 win
#   bash deploy/desktop-release.sh linux  仅 linux
#   bash deploy/desktop-release.sh all    当前平台
#
# 产物上传到服务器 /app/xzserver/updates/（nginx /updates/ 静态目录），
# PC 端 electron-updater 从这里拉 latest*.yml + 安装包自动更新。
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_HOST="root@xiaozhi1.looosen.cn"
UPDATES_DIR="/app/xzserver/updates"
PLATFORM="${1:-all}"

cd "$ROOT/desktop"

case "$PLATFORM" in
  mac)     npm run dist:mac ;;
  win)     npm run dist:win ;;
  linux)   npm run dist:linux ;;
  all)     npm run dist ;;
  *)       echo "用法: bash deploy/desktop-release.sh [mac|win|linux|all]" >&2; exit 1 ;;
esac

echo "== 上传更新到 ${REMOTE_HOST}:${UPDATES_DIR} =="
ssh "$REMOTE_HOST" "mkdir -p $UPDATES_DIR"

# electron-updater 元数据（mac: latest-mac.yml / win: latest.yml / linux: latest-linux.yml）
scp dist-electron/latest*.yml "$REMOTE_HOST:$UPDATES_DIR/" 2>/dev/null || true
# 安装包
scp dist-electron/*.dmg "$REMOTE_HOST:$UPDATES_DIR/" 2>/dev/null || true
scp dist-electron/*.exe "$REMOTE_HOST:$UPDATES_DIR/" 2>/dev/null || true
scp dist-electron/*.AppImage "$REMOTE_HOST:$UPDATES_DIR/" 2>/dev/null || true

echo "== 服务器 updates 目录内容 =="
ssh "$REMOTE_HOST" "ls -la $UPDATES_DIR | tail -10"
echo "✅ 桌面端发版完成：PC 端会自动检测并更新（https://tutor.hourofai.cn/updates/）"
