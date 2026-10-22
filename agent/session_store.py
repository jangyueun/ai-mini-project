"""SQLite에 완료된 대화와 구조화한 조사 맥락을 함께 저장한다."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "session.db"


class SqliteSessionStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            "thread_id TEXT, role TEXT, content TEXT, created TEXT)"
        )
        # 이전 DB를 지우지 않고 메타데이터 열만 추가한다.
        if "metadata" not in {r[1] for r in self.conn.execute("PRAGMA table_info(messages)")}:
            self.conn.execute("ALTER TABLE messages ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS conversation_context (thread_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.conn.commit()

    def load(self, thread_id: str) -> list[dict]:
        return [{"role": r["role"], "content": r["content"]} for r in self.messages(thread_id, limit=20)]

    def messages(self, thread_id: str, limit: int = 200) -> list[dict]:
        rows = self.conn.execute(
            "SELECT rowid, role, content, created, metadata FROM messages "
            "WHERE thread_id=? ORDER BY rowid DESC LIMIT ?", (thread_id, limit)
        ).fetchall()
        return [{"id": r[0], "role": r[1], "content": r[2], "created": r[3],
                 "metadata": json.loads(r[4])} for r in reversed(rows)]

    def context(self, thread_id: str) -> dict:
        row = self.conn.execute("SELECT data FROM conversation_context WHERE thread_id=?", (thread_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def append(self, thread_id: str, role: str, content: str) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO messages(thread_id,role,content,created) VALUES(?,?,?,?)",
                              (thread_id, role, content, datetime.now(timezone.utc).isoformat()))

    def save_turn(self, thread_id: str, query: str, result: dict) -> None:
        """사용자·최종 답변·대상 맥락을 한 트랜잭션으로 저장. 실패 초안은 저장하지 않는다."""
        context = self.context(thread_id)
        if "pending_context" in result:
            context["pending"] = result["pending_context"]
        targets = list(dict.fromkeys(
            c["data"]["system_name"] for c in result.get("collected", [])
            if c["source"] == "monitoring" and c["data"].get("status") != "unknown"
        ))
        if targets:
            context.update(last_targets=targets, pending=None)
        metadata = {"events": result.get("events", []), "prompt": result.get("last_prompt"),
                    "targets": targets, "route": result.get("route"),
                    "validation_status": result.get("validation_status"),
                    "validation_issues": result.get("validation_issues", [])}
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.executemany("INSERT INTO messages(thread_id,role,content,created,metadata) VALUES(?,?,?,?,?)", [
                (thread_id, "user", query, now, "{}"),
                (thread_id, "assistant", result["final"], now, json.dumps(metadata, ensure_ascii=False)),
            ])
            self.conn.execute("INSERT INTO conversation_context(thread_id,data) VALUES(?,?) "
                              "ON CONFLICT(thread_id) DO UPDATE SET data=excluded.data",
                              (thread_id, json.dumps(context, ensure_ascii=False)))

    def clear(self, thread_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM messages WHERE thread_id=?", (thread_id,))
            self.conn.execute("DELETE FROM conversation_context WHERE thread_id=?", (thread_id,))

    def close(self) -> None:
        self.conn.close()
