"""一次性迁移脚本：per-user SQLite（chat_history.db / mastery.sqlite3）→ MySQL dt_* 表。

用法（在 deeptutor 容器内执行，能连 MySQL + 读数据文件）：
    docker compose exec -T deeptutor python -m deploy.migrate_to_mysql
  或直接把本文件放到容器里运行。

行为：
  - 遍历 data/users/<user_id>/ 下的 chat_history.db 和 mastery.sqlite3
  - 也迁移 admin 单用户目录 data/user/chat_history.db
  - 逐用户插入 MySQL dt_* 表（幂等：先删该用户旧数据再插入，可重复跑）
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from deeptutor.services.session.mysql_store import get_mysql_pool

USERS_ROOT = Path("/data/data/users")
ADMIN_DIR = Path("/data/data/user")
CHAT_HISTORY_NAME = "chat_history.db"
MASTERY_NAME = "mastery.sqlite3"


def _rows(conn: sqlite3.Connection, table: str):
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    for row in cur.fetchall():
        yield {cols[i]: row[i] for i in range(len(cols))}


async def _migrate_notebook(db_path: Path, user_id: str, pool) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        entries = list(_rows(conn, "notebook_entries"))
        cats = list(_rows(conn, "notebook_categories"))
        links = list(_rows(conn, "notebook_entry_categories"))
    except sqlite3.Error as exc:
        print(f"  [skip] {db_path.name}: {exc}")
        return
    finally:
        conn.close()

    async with pool.acquire() as c:
        async with c.cursor() as cur:
            # 幂等：删该用户旧数据
            await cur.execute("DELETE FROM dt_notebook_entry_categories WHERE entry_id IN (SELECT id FROM dt_notebook_entries WHERE user_id=%s)", (user_id,))
            await cur.execute("DELETE FROM dt_notebook_entries WHERE user_id=%s", (user_id,))
            await cur.execute("DELETE FROM dt_notebook_categories WHERE user_id=%s", (user_id,))
            for e in entries:
                await cur.execute(
                    """INSERT INTO dt_notebook_entries
                       (id, user_id, session_id, turn_id, question_id, question, question_type,
                        options_json, correct_answer, explanation, difficulty, user_answer,
                        user_answer_images_json, is_correct, bookmarked, followup_session_id,
                        ai_judgment, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE updated_at=VALUES(updated_at)""",
                    (e["id"], user_id, e["session_id"], e["turn_id"], e["question_id"], e["question"],
                     e["question_type"], e["options_json"], e["correct_answer"], e["explanation"],
                     e["difficulty"], e["user_answer"], e["user_answer_images_json"],
                     int(bool(e["is_correct"])), int(bool(e["bookmarked"])),
                     e.get("followup_session_id", ""), e.get("ai_judgment", ""),
                     e["created_at"], e["updated_at"]),
                )
            for c in cats:
                await cur.execute(
                    "INSERT INTO dt_notebook_categories (id, user_id, name, created_at) VALUES (%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE name=VALUES(name)",
                    (c["id"], user_id, c["name"], c["created_at"]),
                )
            for l in links:
                await cur.execute(
                    "INSERT IGNORE INTO dt_notebook_entry_categories (entry_id, category_id) VALUES (%s,%s)",
                    (l["entry_id"], l["category_id"]),
                )
        await c.commit()
    print(f"  ✓ notebook: {len(entries)} entries, {len(cats)} cats")


async def _migrate_mastery(db_path: Path, user_id: str, pool) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        paths = list(_rows(conn, "mastery_paths"))
        sessions = list(_rows(conn, "mastery_path_sessions"))
        interactions = list(_rows(conn, "mastery_interactions"))
        events = list(_rows(conn, "mastery_events"))
        leases = list(_rows(conn, "mastery_path_leases"))
    except sqlite3.Error as exc:
        print(f"  [skip] mastery: {exc}")
        return
    finally:
        conn.close()

    async with pool.acquire() as c:
        async with c.cursor() as cur:
            for p in paths:
                await cur.execute(
                    "INSERT INTO dt_mastery_paths (path_id, user_id, state_json, revision, created_at, updated_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE updated_at=VALUES(updated_at)",
                    (p["path_id"], user_id, p["state_json"], p["revision"], p["created_at"], p["updated_at"]),
                )
            for s in sessions:
                await cur.execute(
                    "INSERT IGNORE INTO dt_mastery_path_sessions (path_id, session_id, owns_path, created_at, last_seen_at) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (s["path_id"], s["session_id"], int(bool(s["owns_path"])), s["created_at"], s["last_seen_at"]),
                )
            for i in interactions:
                await cur.execute(
                    "INSERT INTO dt_mastery_interactions (interaction_id, user_id, path_id, status, question_json, "
                    "session_id, turn_id, user_answer, result_json, created_at, updated_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE updated_at=VALUES(updated_at)",
                    (i["interaction_id"], user_id, i["path_id"], i["status"], i["question_json"],
                     i.get("session_id", ""), i.get("turn_id", ""), i.get("user_answer", ""),
                     i.get("result_json", "{}"), i["created_at"], i["updated_at"]),
                )
            for e in events:
                await cur.execute(
                    "INSERT INTO dt_mastery_events (user_id, path_id, revision, event_type, payload_json, "
                    "session_id, turn_id, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (user_id, e["path_id"], e["revision"], e["event_type"], e["payload_json"],
                     e.get("session_id", ""), e.get("turn_id", ""), e["created_at"]),
                )
            for l in leases:
                await cur.execute(
                    "INSERT IGNORE INTO dt_mastery_path_leases (path_id, session_id, turn_id, acquired_at) "
                    "VALUES (%s,%s,%s,%s)",
                    (l["path_id"], l["session_id"], l["turn_id"], l["acquired_at"]),
                )
        await c.commit()
    print(f"  ✓ mastery: {len(paths)} paths, {len(interactions)} interactions")


async def main() -> None:
    pool = await get_mysql_pool()
    print("开始迁移 → MySQL")

    # admin 单用户目录
    admin_db = ADMIN_DIR / CHAT_HISTORY_NAME
    if admin_db.exists():
        print(f"[admin] {admin_db}")
        await _migrate_notebook(admin_db, "local-admin", pool)
        admin_mastery = ADMIN_DIR / "workspace" / "learning" / MASTERY_NAME
        if admin_mastery.exists():
            await _migrate_mastery(admin_mastery, "local-admin", pool)

    # 多用户目录
    if USERS_ROOT.exists():
        for user_dir in sorted(USERS_ROOT.iterdir()):
            if not user_dir.is_dir():
                continue
            user_id = user_dir.name
            chat = user_dir / "user" / CHAT_HISTORY_NAME
            if chat.exists():
                print(f"[{user_id}] {chat}")
                await _migrate_notebook(chat, user_id, pool)
            mastery = user_dir / "user" / "workspace" / "learning" / MASTERY_NAME
            if mastery.exists():
                print(f"[{user_id}] {mastery}")
                await _migrate_mastery(mastery, user_id, pool)

    print("迁移完成")


if __name__ == "__main__":
    asyncio.run(main())
