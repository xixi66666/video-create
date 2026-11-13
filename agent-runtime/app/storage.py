"""运行与事件分离存储；业务产物采纳仍由 Java 工作区负责。"""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class QueueFull(Exception):
    """待处理运行达到限制。"""


class Store:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root / "runs.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, payload TEXT NOT NULL,
          status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          deleted_at TEXT, decision TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL, kind TEXT NOT NULL, role TEXT NOT NULL,
          data TEXT NOT NULL, at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_events_run ON events(run_id,seq);
        CREATE TABLE IF NOT EXISTS artifacts(run_id TEXT NOT NULL, version INTEGER NOT NULL,
          kind TEXT NOT NULL, content TEXT NOT NULL, at TEXT NOT NULL,
          PRIMARY KEY(run_id,version,kind));
        """)
        self.db.commit()

    def create(self, run_id, payload, max_pending=None, created_event=None):
        with self.lock, self.db:
            old = self.db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
            encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            if old:
                if old[0] != encoded:
                    raise ValueError("幂等键已用于不同请求")
                return False
            if max_pending is not None:
                count = self.db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('QUEUED','RUNNING')").fetchone()[0]
                if count >= max_pending:
                    raise QueueFull("运行队列已满，请稍后再试")
            self.db.execute("INSERT INTO runs(id,payload,status,created_at,updated_at) VALUES(?,?,?,?,?)",
                            (run_id, encoded, "QUEUED", now(), now()))
            if created_event is not None:
                self.db.execute("INSERT INTO events(run_id,kind,role,data,at) VALUES(?,?,?,?,?)",
                                (run_id, "RUN_CREATED", "SYSTEM", json.dumps(created_event, ensure_ascii=False), now()))
            return True

    def event(self, run_id, kind, role="SYSTEM", **data):
        with self.lock, self.db:
            self.db.execute("INSERT INTO events(run_id,kind,role,data,at) VALUES(?,?,?,?,?)",
                            (run_id, kind, role, json.dumps(data, ensure_ascii=False), now()))

    def status(self, run_id, status, error=None):
        with self.lock, self.db:
            # 取消是终态，迟到的模型结果不能重新激活任务。
            result = self.db.execute("UPDATE runs SET status=?,error=?,updated_at=? WHERE id=? AND status!='CANCELLED'",
                                     (status, error, now(), run_id))
            return result.rowcount == 1

    def transition(self, run_id, status, kind, error=None, **data):
        """状态及其事件同事务提交，取消后不追加误导性的成功或等待事件。"""
        with self.lock, self.db:
            result = self.db.execute("UPDATE runs SET status=?,error=?,updated_at=? WHERE id=? AND status!='CANCELLED'",
                                     (status, error, now(), run_id))
            if result.rowcount != 1:
                return False
            self.db.execute("INSERT INTO events(run_id,kind,role,data,at) VALUES(?,?,?,?,?)",
                            (run_id, kind, "SYSTEM", json.dumps(data, ensure_ascii=False), now()))
            return True

    def claim_decision(self, run_id, value):
        with self.lock, self.db:
            row = self.db.execute("SELECT status,decision FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row["decision"] is not None:
                return "SAME" if row["decision"] == value else "CONFLICT"
            if row["status"] != "WAITING_ACCEPTANCE":
                return "INVALID"
            self.db.execute("UPDATE runs SET decision=?,updated_at=? WHERE id=?", (value, now(), run_id))
            return "RECORDED"

    def cancel(self, run_id):
        with self.lock, self.db:
            row = self.db.execute("SELECT status,decision FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row["status"] == "CANCELLED":
                return True  # 重投取消是幂等操作，不重复记录事件。
            if row["status"] not in {"QUEUED", "RUNNING", "WAITING_ACCEPTANCE"} or row["decision"] is not None:
                return False
            self.db.execute("UPDATE runs SET status='CANCELLED',error=NULL,updated_at=? WHERE id=?", (now(), run_id))
            self.db.execute("INSERT INTO events(run_id,kind,role,data,at) VALUES(?,?,?,?,?)",
                            (run_id, "CANCELLED", "SYSTEM", "{}", now()))
            return True

    def artifact(self, run_id, version, kind, value):
        with self.lock, self.db:
            self.db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?)",
                            (run_id, version, kind, json.dumps(value, ensure_ascii=False), now()))

    def get(self, run_id):
        with self.lock:
            row = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            result = dict(row)
            result["payload"] = json.loads(result["payload"])
            result["artifacts"] = [dict(r) | {"content": json.loads(r["content"])} for r in
                                   self.db.execute("SELECT * FROM artifacts WHERE run_id=? ORDER BY version,kind", (run_id,))]
            return result

    def events(self, run_id, after=0):
        with self.lock:
            return [dict(r) | {"data": json.loads(r["data"])} for r in self.db.execute(
                "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 500", (run_id, after))]

    def count_events(self, run_id, kind):
        """统计完整事件集；展示接口的分页不能用于预算控制。"""
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM events WHERE run_id=? AND kind=?", (run_id, kind)).fetchone()[0]

    def reserve_model_call(self, run_id, role, limit):
        """在同一事务检查运行状态、调用上限并记录预留，取消与预留按事务顺序生效。"""
        with self.lock, self.db:
            row = self.db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row["status"] != "RUNNING":
                return "NOT_RUNNING"
            count = self.db.execute("SELECT COUNT(*) FROM events WHERE run_id=? AND kind='MODEL_STARTED'", (run_id,)).fetchone()[0]
            if count >= limit:
                return "LIMIT"
            self.db.execute("INSERT INTO events(run_id,kind,role,data,at) VALUES(?,?,?,?,?)",
                            (run_id, "MODEL_STARTED", role, json.dumps({"call": count + 1}), now()))
            return "RESERVED"

    def list(self):
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT id,status,created_at,updated_at,deleted_at,error FROM runs ORDER BY created_at DESC LIMIT 200")]

    def recoverable(self):
        """恢复工作不受展示列表的 200 条截断影响。"""
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT id,status,decision FROM runs WHERE status IN ('QUEUED','RUNNING') "
                "OR (status='WAITING_ACCEPTANCE' AND decision IS NOT NULL) ORDER BY created_at")]

    def recover(self):
        """不自动重试可能已经计费的调用。等待人工采纳的 checkpoint 可安全保留。"""
        for run in self.recoverable():
            if run["status"] == "RUNNING":
                self.transition(run["id"], "UNKNOWN", "RECOVERY_UNKNOWN",
                                error="进程中断：调用结果未知，请人工核对后另建运行。")

    def delete(self, run_id, deleted):
        with self.lock, self.db:
            self.db.execute("UPDATE runs SET deleted_at=? WHERE id=?", (now() if deleted else None, run_id))
