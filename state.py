"""Confirmed local actions, persistent audit log, and the demo clock."""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from order_risk import STAGES, TODAY

ROOT = Path(__file__).resolve().parent
ZONE = ZoneInfo("Asia/Shanghai")


def wall_now():
    return datetime.now(ZONE)


class Store:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("FACTORY_DB", ROOT / "runtime" / "factory.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, kind TEXT, payload TEXT, created_at TEXT);
                CREATE TABLE IF NOT EXISTS watches (id TEXT PRIMARY KEY, payload TEXT, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, payload TEXT, created_at TEXT);
                CREATE TABLE IF NOT EXISTS briefings (day TEXT PRIMARY KEY, payload TEXT, created_at TEXT);
            """)
            db.execute("INSERT OR IGNORE INTO settings VALUES ('anchor_wall_date', ?)", (json.dumps(wall_now().date().isoformat()),))

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get_setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def today(self, now=None):
        now = now or wall_now()
        anchor = date.fromisoformat(self.get_setting("anchor_wall_date"))
        return TODAY + timedelta(days=(now.date()-anchor).days)

    def business_now(self, now=None):
        now = now or wall_now()
        return datetime.combine(self.today(now), now.timetz())

    def commit(self, proposal, *, confirmed=False):
        if not confirmed:
            raise ValueError("Explicit user confirmation is required.")
        kind, payload = proposal["kind"], proposal["payload"]
        if kind not in ACTION_KINDS:
            raise ValueError("Unknown action kind.")
        # Only the UI calls this method; the model has no commit tool.
        with self.connect() as db:
            if db.execute("SELECT 1 FROM actions WHERE id=?", (proposal["id"],)).fetchone():
                return False
            db.execute("INSERT INTO actions VALUES (?,?,?,?)", (proposal["id"], kind, json.dumps(payload, ensure_ascii=False), wall_now().isoformat()))
            if kind in ["watch_order", "watch_stage", "reminder"]:
                db.execute("INSERT INTO watches VALUES (?,?,'active')", (proposal["id"], json.dumps({"kind": kind, **payload}, ensure_ascii=False)))
            elif kind == "briefing_schedule":
                db.execute("INSERT OR REPLACE INTO settings VALUES ('briefing_schedule',?)", (json.dumps(payload),))
            elif kind == "cancel_watch":
                changed = db.execute("UPDATE watches SET status='cancelled' WHERE id=? AND status='active'", (payload["watch_id"],)).rowcount
                if not changed:
                    raise ValueError("This watch is no longer active.")
        return True

    def activity(self):
        with self.connect() as db:
            actions = [dict(row) for row in db.execute("SELECT * FROM actions ORDER BY created_at DESC LIMIT 100")]
            watches = [dict(row) for row in db.execute("SELECT * FROM watches ORDER BY rowid DESC")]
            alerts = [dict(row) for row in db.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 100")]
        for item in actions + watches + alerts:
            item["payload"] = json.loads(item["payload"])
        return {"actions": actions, "watches": watches, "alerts": alerts,
                "briefing_schedule": self.get_setting("briefing_schedule"),
                "worker": self.get_setting("worker_status")}

    def finish_watch(self, watch_id, payload=None):
        with self.connect() as db:
            changed = db.execute("UPDATE watches SET status=? WHERE id=? AND status='active'", ("fired" if payload else "resolved", watch_id)).rowcount
            if changed and payload:
                db.execute("INSERT OR IGNORE INTO alerts VALUES (?,?,?)", (watch_id, json.dumps(payload, ensure_ascii=False), wall_now().isoformat()))

    def briefing(self, day):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM briefings WHERE day=?", (str(day),)).fetchone()
        return json.loads(row[0]) if row else None

    def save_briefing(self, day, payload):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO briefings VALUES (?,?,?)", (str(day), json.dumps(payload, ensure_ascii=False), wall_now().isoformat()))


ACTION_KINDS = ["add_note", "save_draft", "watch_order", "watch_stage", "reminder", "briefing_schedule", "cancel_watch"]


def propose_action(factory, store, kind, order_id=None, stage=None, content=None, deadline=None,
                   schedule_time=None, enabled=True, watch_id=None):
    if kind not in ACTION_KINDS:
        raise ValueError("Choose a supported local action.")
    payload, sources = {}, []
    if kind in ["add_note", "save_draft", "watch_order"]:
        if not order_id:
            raise ValueError("An exact order ID is required; ask the manager to choose.")
        result = factory.trace_order(order_id)
        if result["facts"]["count"] != 1:
            raise ValueError("Order not found.")
        order = result["facts"]["orders"][0]
        payload["order_id"] = order["order_id"]
        sources += result["sources"]
        if kind == "watch_order":
            if order["status"] == "COMPLETE":
                raise ValueError("Completed orders do not need a movement watch.")
            payload["baseline"] = {field: order[field] for field in ["current_stage", "last_activity_date"]}
    if kind in ["add_note", "save_draft", "reminder"]:
        if not isinstance(content, str) or not content.strip() or len(content) > 2000:
            raise ValueError("Provide content between 1 and 2000 characters.")
        payload["content"] = content.strip()
    if kind == "watch_stage":
        if stage not in STAGES:
            raise ValueError("An exact production stage is required.")
        payload["stage"] = stage
    if kind in ["watch_order", "watch_stage", "reminder"]:
        if not deadline:
            raise ValueError("Provide an explicit deadline including time; ask if it is missing.")
        parsed = datetime.fromisoformat(deadline)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZONE)
        if parsed <= store.business_now():
            raise ValueError("The reminder/watch deadline must be in the future on the displayed simulation clock.")
        payload["deadline"] = parsed.isoformat()
    if kind == "briefing_schedule":
        if not isinstance(enabled, bool):
            raise ValueError("Enabled must be true or false.")
        if not schedule_time:
            raise ValueError("Specify the daily local time in HH:MM format.")
        datetime.strptime(schedule_time, "%H:%M")
        payload.update(time=schedule_time, enabled=enabled, timezone="Asia/Shanghai")
    if kind == "cancel_watch":
        if not any(w["id"] == watch_id and w["status"] == "active" for w in store.activity()["watches"]):
            raise ValueError("Active watch not found.")
        payload["watch_id"] = watch_id
    proposal = {"id": str(uuid.uuid4()), "kind": kind, "payload": payload,
                "effect": "Save locally after confirmation. No external messages, CSV edits, or capacity commitments."}
    return factory.pack({"proposal": proposal, "requires_confirmation": True, "committed": False}, sources)
