#!/bin/bash
# ============================================================
# DeepTutor 一键部署脚本（部署到 xiaozhi 服务器）
#
# 用法：
#   bash deploy/deploy.sh backend    仅部署后端（同步代码 + 重启容器）
#   bash deploy/deploy.sh frontend   仅部署前端（构建 + 同步 + 重建镜像）
#   bash deploy/deploy.sh all        前后端一起部署（默认）
#
# 说明：
#   - 服务器地址、同步逻辑直接复用 xiaozhi 仓库的脚本
#     （sync.sh / restart.sh，服务器配置在其中，保持一致）
#   - xiaozhi 仓库默认在 ../guyuai/xiaozhi（相对 DeepTutor 仓库）
#
# 示例：
#   bash deploy/deploy.sh backend
#   bash deploy/deploy.sh all
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
XIAOZHI="${XIAOZHI_REPO:-$(cd "$ROOT/../guyuai/xiaozhi" && pwd)}"

if [ ! -f "$XIAOZHI/restart.sh" ] || [ ! -f "$XIAOZHI/sync.sh" ]; then
    echo "错误：未找到 xiaozhi 仓库的 restart.sh / sync.sh（当前 XIAOZHI_REPO=$XIAOZHI）" >&2
    exit 1
fi

# 服务器地址从 xiaozhi 的 restart.sh 读取（唯一事实来源，避免重复配置）
REMOTE_HOST="$(grep -m1 '^remote_host=' "$XIAOZHI/restart.sh" | sed 's/^remote_host="\{0,1\}//; s/"\{0,1\}$//')"
if [ -z "$REMOTE_HOST" ]; then
    echo "错误：无法从 $XIAOZHI/restart.sh 读取 remote_host" >&2
    exit 1
fi

deploy_backend() {
    echo "== [1/1] 同步后端代码 + 重启容器（复用 restart.sh deeptutor）=="
    (cd "$XIAOZHI" && ./restart.sh deeptutor)
    echo "✅ 后端部署完成（$REMOTE_HOST）"
}

deploy_frontend() {
    echo "== [1/4] 构建前端（build-web.sh）=="
    bash "$ROOT/deploy/build-web.sh"
    echo "== [2/4] 同步前端产物 =="
    (cd "$XIAOZHI" && ./sync.sh deeptutor-web)
    echo "== [3/4] 重建前端容器（前端在镜像内，必须 --build）=="
    ssh "$REMOTE_HOST" "cd /app/xzserver && docker compose up -d --build deeptutor-web"
    echo "== [4/4] reload nginx（容器重建后 IP 变化，刷新 upstream 解析）=="
    ssh "$REMOTE_HOST" "cd /app/xzserver && docker compose exec nginx nginx -s reload"
    echo "✅ 前端部署完成（$REMOTE_HOST）"
}

MODE="${1:-all}"
case "$MODE" in
    backend)
        deploy_backend
        ;;
    frontend)
        deploy_frontend
        ;;
    all)
        deploy_backend
        deploy_frontend
        ;;
    *)
        echo "用法: bash deploy/deploy.sh [backend|frontend|all]" >&2
        exit 1
        ;;
esac
