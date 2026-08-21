"""本地查看 MySQL 表结构和内容（零依赖，用 dt 环境里的 pymysql）。

用法（需先 conda activate dt）：
    python view_mysql.py                # 列出所有表
    python view_mysql.py dt_messages    # 查看某表结构 + 前 20 行
    python view_mysql.py dt_messages 50 # 查看前 50 行
    python view_mysql.py dt_messages 0  # 查看全部行

连接参数默认指向本地开发库（127.0.0.1:13306, dt/dtpass, mixly），
可用环境变量覆盖：MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DB
"""
import os
import sys

import pymysql

HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
PORT = int(os.environ.get("MYSQL_PORT", "13306"))
USER = os.environ.get("MYSQL_USER", "dt")
PASSWORD = os.environ.get("MYSQL_PASSWORD", "dtpass")
DB = os.environ.get("MYSQL_DB", "mixly")


def main():
    conn = pymysql.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD, database=DB,
        cursorclass=pymysql.cursors.DictCursor,
    )
    cur = conn.cursor()

    if len(sys.argv) < 2:
        cur.execute("SHOW TABLES")
        tables = [list(r.values())[0] for r in cur.fetchall()]
        print(f"数据库 {DB} 共 {len(tables)} 张表:")
        for t in tables:
            print(f"  - {t}")
        conn.close()
        return

    table = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    print(f"=== 表 {table} 结构 ===")
    cur.execute(f"SHOW CREATE TABLE `{table}`")
    row = cur.fetchone()
    print(row["Create Table"] if row else f"(表 {table} 不存在)")

    print(f"\n=== 数据（前 {limit if limit else '全部'} 行）===")
    cur.execute(f"SELECT COUNT(*) AS c FROM `{table}`")
    print(f"总行数: {cur.fetchone()['c']}")
    if limit != 0:
        cur.execute(f"SELECT * FROM `{table}` LIMIT {limit}")
    else:
        cur.execute(f"SELECT * FROM `{table}`")
    rows = cur.fetchall()
    if not rows:
        print("(空)")
        conn.close()
        return
    cols = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows[:50])) for c in cols}
    header = " | ".join(c.ljust(widths[c]) for c in cols)
    print(header)
    print("-" * len(header))
    for r in rows:
        print(" | ".join(str(r[c]).ljust(widths[c]) for c in cols))
    conn.close()


if __name__ == "__main__":
    main()
