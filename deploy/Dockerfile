# DeepTutor 后端镜像（部署到 xiaozhi 同服务器的 Docker）
#
# 设计（镜像 xiaozhi/manager 的做法）：
#   - 依赖装进镜像；代码由 docker-compose volume 挂载（./deeptutor:/app）
#   - 改代码后：rsync 同步 + `docker compose up -d --force-recreate deeptutor`
#     即可生效，无需重建镜像
#   - 数据目录独立（DEEPTUTOR_HOME=/data，挂载 ./deeptutor-data），
#     避免 rsync --delete 误删数据
FROM python:3.12-slim

ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    DEEPTUTOR_HOME=/data \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) 先装依赖（层缓存：代码变更不重装依赖）
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
