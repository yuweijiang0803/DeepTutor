# DeepTutor 更新部署手册（日常更新）

> 适用：代码/配置有改动后，把最新版本部署到 xiaozhi 服务器。
> 首次部署见 `DEPLOY.md`；本文只讲「更新」。
>
> 命令中的 `<xiaozhi服务器>` 替换为实际服务器地址（如 `root@<ip>`）。

## 一、三个同步对象

| 对象 | 内容 | 同步命令 |
|---|---|---|
| `deeptutor` | DeepTutor 仓库代码（后端 + 根 Dockerfile） | `./sync.sh deeptutor` |
| `deeptutor-web` | 前端构建产物（`deeptutor-web/` 整目录） | `./sync.sh deeptutor-web` |
| `nginx` | docker-compose.yml + nginx 配置 | `./sync.sh nginx` |

> 在 `cd /Users/heyuanlin/Documents/guyuai/xiaozhi` 下执行。
> `deeptutor` 同步自动排除本地 `data/`、`deeptutor-web/`、`.next`、`desktop/`、`.DS_Store`；
> `deeptutor-web` 是整目录 `--delete` 同步（含 node_modules，前端镜像必需）。

## 二、按改动类型执行

### 1. 改了后端代码（deeptutor/、deeptutor_cli/ 等）

```bash
cd /Users/heyuanlin/Documents/guyuai/xiaozhi
./sync.sh deeptutor
ssh root@<xiaozhi服务器> "cd /app/xzserver && docker compose up -d --force-recreate deeptutor"
```

- 代码是 volume 挂载的，**无需重建镜像**，`force-recreate` 即生效
- 只有 `requirements.txt` / `pyproject.toml`（依赖）变了才需要加 `--build`

### 2. 改了前端代码（web/ 下任何文件）

```bash
cd /Users/heyuanlin/Documents/DeepTutor
bash deploy/build-web.sh          # 重新构建前端产物（约 30 秒）

cd /Users/heyuanlin/Documents/guyuai/xiaozhi
./sync.sh deeptutor-web           # 同步产物到服务器
ssh root@<xiaozhi服务器> "cd /app/xzserver && docker compose up -d --build deeptutor-web"
```

- 前端是打包进镜像的，必须 `--build` 重建
- 如果只改了 `deploy/build-web.sh` / `Dockerfile.web` 本身，同样走这条

### 3. 改了配置（compose / nginx / settings）

**compose 或 nginx 配置**（xiaozhi 仓库里改的）：
```bash
cd /Users/heyuanlin/Documents/guyuai/xiaozhi
./sync.sh nginx
ssh root@<xiaozhi服务器> "cd /app/xzserver && docker compose up -d --force-recreate deeptutor"
ssh root@<xiaozhi服务器> "cd /app/xzserver && docker compose exec nginx nginx -s reload"
```

**后端 settings（mysql.json / xiaozhi.json / auth.json 等）**——直接在服务器上改，不在 git：
```bash
ssh root@<xiaozhi服务器> "vi /app/xzserver/deeptutor-data/user/settings/mysql.json"
ssh root@<xiaozhi服务器> "cd /app/xzserver && docker compose up -d --force-recreate deeptutor"
```

## 三、全量更新（一次全部署）

```bash
cd /Users/heyuanlin/Documents/DeepTutor
bash deploy/build-web.sh          # 前端代码有改动才需要

cd /Users/heyuanlin/Documents/guyuai/xiaozhi
./sync.sh deeptutor               # 后端代码
./sync.sh deeptutor-web           # 前端产物
./sync.sh nginx                   # compose + nginx

ssh root@<xiaozhi服务器> "cd /app/xzserver && docker compose up -d --build deeptutor deeptutor-web"
ssh root@<xiaozhi服务器> "cd /app/xzserver && docker compose exec nginx nginx -s reload"
```

## 四、验证清单

```bash
# 1. 容器都在运行
ssh root@<xiaozhi服务器> "cd /app/xzserver && docker compose ps"

# 2. 后端正常（日志无报错，监听 8001）
ssh root@<xiaozhi服务器> "cd /app/xzserver && docker compose logs --tail 10 deeptutor"

# 3. 前端正常（Next.js Ready，监听 3782）
ssh root@<xiaozhi服务器> "cd /app/xzserver && docker compose logs --tail 5 deeptutor-web"

# 4. 整站链路（应 200/307）
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: tutor.hourofai.cn' \
  http://<xiaozhi服务器IP>/login

# 5. 浏览器打开 https://tutor.hourofai.cn 走一遍登录/使用
```

## 五、回滚

```bash
# 停掉 DeepTutor 相关容器（xiaozhi 不受影响）
ssh root@<xiaozhi服务器> "cd /app/xzserver && docker compose stop deeptutor deeptutor-web"
# 或彻底移除后重新构建
ssh root@<xiaozhi服务器> "cd /app/xzserver && docker compose rm -sf deeptutor deeptutor-web"
```

> 代码回滚：改回旧代码后重复「二.1 / 二.2」即可；数据（deeptutor-data）不受影响。

## 七、跟随上游（upstream）更新

DeepTutor 上游（`HKUDS/DeepTutor`）会持续发布新版本。本地在 `develop` 分支上有业务定制，需要定期合入上游更新。

### 1. 分支结构

```
upstream/dev   ← 只读，跟踪上游，fetch 用，绝不在上面改
    │  定期 merge（建议每个版本 / 每月）
    ▼
develop        ← 业务定制 + 上游更新（当前开发分支）
```

### 2. 合并流程

```bash
cd /Users/heyuanlin/Documents/DeepTutor

# ① 先提交/暂存本地未提交改动（merge 前必须工作树干净）
git add -A && git commit -m "wip: <当前改动说明>"

# ② 拉取上游更新
git fetch upstream

# ③ 备份当前分支（保护现场，冲突乱了可回退）
git branch backup-$(date +%Y%m%d)

# ④ 合并上游 dev
git merge upstream/dev
```

### 3. 冲突决策原则

| 情况 | 处理 |
|---|---|
| 本地业务文件（Dockerfile、deploy/、SSO/昵称相关）| **保留本地**（`git checkout --ours <文件>`）|
| 上游新功能/修复 | **保留上游** |
| 两边都改了同一段 | 手动合并，按"业务优先本地、功能优先上游"判断 |
| 上游只加了新文件 | 自动合并，直接保留 |

> 参考：Dockerfile 冲突时直接 `git checkout --ours Dockerfile`（本地部署版优先），因为官方一体化镜像方案本地不用。

### 4. 合并后验证（部署前必做）

```bash
# ① 后端语法检查（merge 引入的 Python 文件）
git diff <backup分支> HEAD --name-only -z -- '*.py' | grep -zv '^tests/' | xargs -0 python -m py_compile

# ② 前端构建
bash deploy/build-web.sh

# ③ 本地测试通过后再部署
./deploy/deploy.sh all
```

### 5. 注意事项

- **小步常合**：别攒很久才合并，每个版本/每月合并一次，冲突范围小、好处理
- **冲突会随定制深度增加**：本地改了上游高频文件（如 `auth.py`），上游每次改动都可能冲突，这是深度定制的固有成本
- **业务定制尽量收拢**：能放独立文件/目录的（如 `deploy/`）就独立，能走配置/扩展点实现的就别改核心文件，减少冲突面
- **合并不等于部署**：merge 只是代码合并，部署仍需走前面的更新流程（同步 + 重建 + 验证）

## 八、注意

- **nginx 的 tutor.hourofai.cn 段**：deeptutor-web 容器在跑时才能启用（proxy_pass 静态解析），容器停了会导致 nginx reload 失败——先保证 deeptutor-web 在跑再动 nginx。
- **敏感配置**（mysql.json / xiaozhi.json / auth.json）只在服务器 `deeptutor-data/`，不进 git，别同步回本地仓库。
- **`mix-token` SSO**：小智用户在小智平台（`*.hourofai.cn`）登录后，打开 tutor.hourofai.cn 自动登录；`mix-token` 24 小时过期。
