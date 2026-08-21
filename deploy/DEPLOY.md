# DeepTutor 部署到 xiaozhi 服务器（Docker Compose + rsync + nginx）

> 目标服务器：`root@xiaozhi1.looosen.cn`，应用目录 `/app/xzserver`（与 xiaozhi 同一台）
> 原则：**完全独立** —— 只新增 deeptutor 后端容器、deeptutor-web 前端容器、nginx 域名段，
> 不碰 xiaozhi 任何现有服务；MySQL 只用自己的 `dt_*` 表和 `user.dt_user_id` 列。

## 一、新增/修改的文件

| 文件 | 放哪 | 说明 |
|---|---|---|
| `deploy/Dockerfile` | deeptutor 仓库 | 后端镜像（依赖装镜像，代码 volume 挂载） |
| `deploy/Dockerfile.web` | deeptutor 仓库 | 前端镜像（Next standalone） |
| `deploy/build-web.sh` | deeptutor 仓库 | 本地构建前端并打包 `deeptutor-web/` |
| `deploy/docker-compose.deeptutor.yml` | 追加进 xiaozhi 的 compose | 两个服务段 |
| `deploy/nginx.deeptutor.conf` | 追加进 xiaozhi 的 nginx.conf | tutor 域名段 |
| `sync.sh` | xiaozhi | 追加 `deeptutor` / `deeptutor-web` 同步项 |

## 二、首次部署步骤

### 1. 准备本地

```bash
# deeptutor 仓库
cd /Users/heyuanlin/Documents/DeepTutor
bash deploy/build-web.sh              # 产出 deeptutor-web/（自包含前端）

# xiaozhi 仓库：把 deploy 里的片段合入
#  - docker-compose.deeptutor.yml → docker-compose.yml services 下
#  - nginx.deeptutor.conf          → nginx/nginx.conf http 内
#  - sync.sh 追加 deeptutor、deeptutor-web 两个 case/默认项
```

### 2. 同步到服务器

```bash
cd /Users/heyuanlin/Documents/guyuai/xiaozhi
./sync.sh deeptutor        # deeptutor 代码
./sync.sh deeptutor-web    # 前端构建产物（rsync --delete 会清旧，需整目录）
./sync.sh nginx            # docker-compose.yml + nginx 配置
```

> sync.sh 需要先加上 `deeptutor|deeptutor-web) src="./$item" ;;` 分支。

### 3. 服务器构建并启动

```bash
ssh root@xiaozhi1.looosen.cn "cd /app/xzserver && docker compose up -d --build deeptutor deeptutor-web"
ssh root@xiaozhi1.looosen.cn "cd /app/xzserver && docker compose exec nginx nginx -s reload"
```

### 4. 服务器初始化配置（`/app/xzserver/deeptutor-data/`）

首次启动前，建好 `deeptutor-data/user/settings/` 下的配置文件：

```bash
# mysql.json —— 指向 RDS
#   { "enabled": true, "host": "rm-7xv9o4cd9r52zq033.mysql.rds.aliyuncs.com",
#     "port": 3306, "user": "xiaozhi", "password": "<config.yaml密码>", "database": "mixly" }
#
# xiaozhi.json —— SSO JWT 密钥（和小智 config.yaml 里 token SECRET 一致）
#   { "jwt_secret": "4SJehCMaaH4Qplc8" }
#
# auth.json —— 开启登录
#   { "enabled": true, ... }
```

```bash
ssh root@xiaozhi1.looosen.cn "mkdir -p /app/xzserver/deeptutor-data/user/settings"
# 把三个 json 写入后：
ssh root@xiaozhi1.looosen.cn "cd /app/xzserver && docker compose up -d --force-recreate deeptutor"
```

### 5. LLM key

后端起来后，进容器配置（或先本地 `deeptutor init` 后把 data/ 同步上去）：

```bash
ssh root@xiaozhi1.looosen.cn "cd /app/xzserver && docker compose exec deeptutor deeptutor init"
```

### 6. DNS + 验证

1. `tutor.hourofai.cn` 解析到服务器 IP
2. 浏览器打开 `http://tutor.hourofai.cn`
3. 注册/登录第一个 admin → 发对话
4. 验证 RDS：`mixly.dt_messages` 有记录
5. 小智老用户：前端登录页调 `xiaozhi-login` 能进（SSO，需前端入口）

## 三、日常更新

```bash
cd /Users/heyuanlin/Documents/guyuai/xiaozhi

# 后端代码更新
./restart.sh deeptutor       # rsync + docker compose up -d --force-recreate deeptutor

# 前端更新（先本地 build-web.sh，再同步 + 重建镜像）
bash /Users/heyuanlin/Documents/DeepTutor/deploy/build-web.sh
./sync.sh deeptutor-web
ssh root@xiaozhi1.looosen.cn "cd /app/xzserver && docker compose up -d --build deeptutor-web"
```

## 四、回滚

```bash
# 停掉 DeepTutor 相关容器（xiaozhi 不受影响）
ssh root@xiaozhi1.looosen.cn "cd /app/xzserver && docker compose stop deeptutor deeptutor-web"
# 或彻底移除
ssh root@xiaozhi1.looosen.cn "cd /app/xzserver && docker compose rm -sf deeptutor deeptutor-web"
```

## 五、安全注意

- RDS 白名单：服务器 IP 需放行（小智同机则已有）
- DeepTutor 的 MySQL 账号需对 `mixly.user` 表有 `SELECT + UPDATE` 权限（SSO 回填）
- `xiaozhi.json` 含 JWT 密钥，放 `deeptutor-data/`（已被 git 忽略），不进仓库
- 生产建议后续把 SSO 从「共享密钥」升级为「小智 verify-token 接口」
