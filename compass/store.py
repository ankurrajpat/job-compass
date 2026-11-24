"""SQLite storage. No model-authored SQL. Every memory query is session-scoped."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone, timedelta
from .schemas import Preferences

class Store:
    def __init__(self, path: str, seed: str | None = None):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, payload TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
              CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, preferences TEXT NOT NULL, updated_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id,id);
              CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(id UNINDEXED, title, description, skills);
            ''')
        if seed and not self.jobs():
            self.upsert(json.loads(Path(seed).read_text()))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def upsert(self, jobs):
        # Transaction keeps jobs and full-text index aligned during updates.
        with self.connect() as db:
            for j in jobs:
                db.execute('INSERT INTO jobs VALUES(?,?,1) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,active=1', (j['id'], json.dumps(j)))
                db.execute('DELETE FROM jobs_fts WHERE id=?', (j['id'],))
                db.execute('INSERT INTO jobs_fts VALUES(?,?,?,?)', (j['id'],j['title'],j['description'],' '.join(j['skills'])))

    def jobs(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM jobs WHERE active=1 ORDER BY id')]

    def preferences(self, sid):
        with self.connect() as db:
            row = db.execute('SELECT preferences FROM sessions WHERE id=?',(sid,)).fetchone()
            return Preferences.model_validate_json(row[0]) if row else Preferences()

    def remember(self, sid, patch):
        p = self.preferences(sid).model_dump()
        p.update(patch.model_dump(exclude_none=True))
        p = Preferences.model_validate(p)
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET preferences=excluded.preferences,updated_at=excluded.updated_at', (sid,p.model_dump_json(),datetime.now(timezone.utc).isoformat()))
        return p.model_dump()

    def history(self, sid):
        with self.connect() as db:
            rows = db.execute('SELECT role,content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 10',(sid,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def log(self, sid, role, text):
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at',(sid,Preferences().model_dump_json(),datetime.now(timezone.utc).isoformat()))
            db.execute('INSERT INTO messages(session_id,role,content) VALUES(?,?,?)',(sid,role,text))
            db.execute('DELETE FROM messages WHERE session_id=? AND id NOT IN (SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 10)',(sid,sid))

    def clear(self, sid):
        with self.connect() as db:
            db.execute('DELETE FROM messages WHERE session_id=?',(sid,))
            db.execute('DELETE FROM sessions WHERE id=?',(sid,))

    def prune(self):
        cutoff = (datetime.now(timezone.utc)-timedelta(hours=24)).isoformat()
        with self.connect() as db:
            db.execute('DELETE FROM messages WHERE session_id IN (SELECT id FROM sessions WHERE updated_at < ?)',(cutoff,))
            db.execute('DELETE FROM sessions WHERE updated_at < ?',(cutoff,))
