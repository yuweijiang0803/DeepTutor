# 本地 MySQL 登录与查询指南

> DeepTutor 本地开发库。会话数据存 MySQL（`mixly` 库的 `dt_*` 表），默认同时保留 SQLite 兜底。

## 一、连接信息

| 项 | 值 |
|---|---|
| Host | `127.0.0.1` |
| Port | `13306` |
| User | `dt` |
| Password | `dtpass` |
| Database | `mixly` |

## 二、三种查看方式

### 方式 A：项目脚本（零安装，最快）

```bash
conda activate dt
cd /Users/heyuanlin/Documents/DeepTutor

python view_mysql.py              # 列出所有表
python view_mysql.py dt_messages  # 表结构 + 前 20 行
python view_mysql.py dt_messages 50  # 前 50 行
python view_mysql.py dt_messages 0   # 全部行
```

### 方式 B：GUI 工具（浏览最舒服）

装 **DBeaver**（免费跨平台）或 **TablePlus**（macOS 原生），按上面的连接信息新建连接，点表即可看结构 + 数据。

### 方式 C：mysql 命令行（需先装客户端）

```bash
conda activate mysql
conda install -c conda-forge mysql   # 补装客户端（server 包不带 mysql 命令）
mysql -h127.0.0.1 -P13306 -udt -pdtpass mixly
```

## 三、mysql 命令参数说明

```
mysql -h127.0.0.1 -P13306 -udt -pdtpass mixly
       └主机       └端口    └用户  └密码   └库名
```

| 参数 | 大小写 | 含义 |
|---|---|---|
| `-h` | 小写 | host，主机地址 |
| `-P` | **大写** | port，端口（小写 `-p` 是密码） |
| `-u` | 小写 | user，用户名 |
| `-p` | 小写 | password，密码，**后面直接跟不留空格**（`-pdtpass`） |
| （末尾） | — | 数据库名，连接后默认使用 |

> 正式环境建议 `mysql -h... -u... -p`（不带密码），安全提示输入，避免密码留在 shell 历史。

## 四、常用 SQL

```sql
SHOW TABLES;                                    -- 所有表
DESC dt_messages;                               -- 表结构
SELECT * FROM dt_messages LIMIT 10;             -- 查数据
SELECT id, role, LEFT(content,30), created_at
  FROM dt_messages
  WHERE session_id = 'unified_xxx'
  ORDER BY id;                                  -- 查某个会话的消息
SELECT session_id, COUNT(*) FROM dt_messages
  GROUP BY session_id;                          -- 每个会话的消息数
SELECT id, title, created_at FROM dt_sessions
  ORDER BY created_at DESC LIMIT 5;             -- 最近会话
EXIT;                                           -- 退出
```

## 五、4 张表速览

| 表 | 内容 |
|---|---|
| `dt_sessions` | 会话（id、user_id、标题、摘要、偏好） |
| `dt_messages` | 消息（role、content、事件、附件、元数据） |
| `dt_turns` | 回合（一次 agent 循环，状态 running/completed/failed） |
| `dt_turn_events` | 回合事件（流式输出、工具调用等，seq 递增） |

## 六、切换到线上 RDS（部署后）

DeepTutor 后端通过 `data/user/settings/mysql.json` 读连接信息（已被 .gitignore 忽略，不含在仓库里）。改这个文件指向线上 RDS 即可：

```json
{
  "version": 1,
  "enabled": true,
  "host": "rm-xxxx.mysql.rds.aliyuncs.com",
  "port": 3306,
  "user": "xxx",
  "password": "xxx",
  "database": "mixly"
}
```

改完重启后端生效。线上是 MySQL 8.x，表结构已兼容。
