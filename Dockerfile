# DeepTutor 后端镜像（部署到 xiaozhi 同服务器的 Docker）
#
# 设计（镜像 xiaozhi/manager 的做法）：
#   - 依赖装进镜像；代码由 docker-compose volume 挂载（./deeptutor:/app）
#   - 改代码后：rsync 同步 + `docker compose up -d --force-recreate deeptutor`
#     即可生效，无需重建镜像
#   - 数据目录独立（DEEPTUTOR_HOME=/data，挂载 ./deeptutor-data），
#     避免 rsync --delete 误删数据
#
# 阶段：
#   - base（默认，部署用）          —— 纯后端，`deeptutor serve`
#   - development（docker-compose.dev.yml 用）—— 加 Node + 前端依赖，uvicorn --reload + next dev
FROM python:3.12-slim AS base

ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    DEEPTUTOR_HOME=/data \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) 先装依赖（层缓存：代码变更不重装依赖）
# requirements.txt 通过 `-r requirements/…` 引用分文件，必须连同目录一起拷
COPY requirements/ ./requirements/
COPY requirements.txt ./
RUN pip install --no-cache-dir setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# 2) 装包本身（editable 指向 /app；运行时 /app 被挂载代码覆盖，仍是同一份）
COPY . .
RUN pip install --no-cache-dir -e ".[cli]" --no-build-isolation

# 3) MySQL 驱动（L2 会话存储 + XiaoZhi SSO 需要）
RUN pip install --no-cache-dir aiomysql pymysql cryptography

EXPOSE 8001

CMD ["deeptutor", "serve"]

# ============================================
# Stage 2: Development (docker-compose.dev.yml)
# ============================================
# 在 base 之上补 Node 与前端依赖：docker-compose.dev.yml 覆盖 `target:
# development` 并挂载源码热重载。下一阶段 default 构建到最后阶段，所以
# docker-compose.yml 的 deeptutor 服务必须显式 `target: base`。
FROM base AS development

# 从 Debian 版 node 镜像拷贝 Node（与 python:3.12-slim 同为 glibc）
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version && npm --version

# 前端依赖（package.json 是 COPY . . 带来的；node_modules 在 dev 阶段装）
RUN cd /app/web && npm ci --legacy-peer-deps

# 开发启动脚本：后端 uvicorn --reload + 前端 next dev（web/scripts/dev.mjs）
RUN cat > /app/start-dev.sh <<'EOF'
#!/bin/bash
set -e

BACKEND_PORT=${BACKEND_PORT:-8001}
FRONTEND_PORT=${FRONTEND_PORT:-3782}

python -m uvicorn deeptutor.api.main:app \
    --host 0.0.0.0 \
    --port "${BACKEND_PORT}" \
    --reload \
    --no-access-log \
    --reload-exclude "web/*" \
    --reload-exclude "data/*" &
BACKEND_PID=$!

cd /app/web
node scripts/dev.mjs -H 0.0.0.0 -p "${FRONTEND_PORT}"

kill "$BACKEND_PID" 2>/dev/null || true
EOF
RUN sed -i 's/\r$//' /app/start-dev.sh && chmod +x /app/start-dev.sh

CMD ["/app/start-dev.sh"]
