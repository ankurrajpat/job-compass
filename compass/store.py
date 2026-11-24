"""SQLite storage. No model-authored SQL. Every memory query is session-scoped."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
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
              CREATE TABLE IF NOT EXISTS vectors(id TEXT PRIMARY KEY, text_hash TEXT NOT NULL, model TEXT NOT NULL, vec BLOB NOT NULL);
              CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            cols={r[1] for r in db.execute('PRAGMA table_info(jobs)')}
            for name,ddl in (('source',"TEXT NOT NULL DEFAULT ''"),('content_hash',"TEXT NOT NULL DEFAULT ''"),('first_seen',"TEXT NOT NULL DEFAULT ''"),('last_seen',"TEXT NOT NULL DEFAULT ''"),('closed_at',"TEXT")):
                if name not in cols: db.execute(f'ALTER TABLE jobs ADD COLUMN {name} {ddl}')
            db.execute('CREATE INDEX IF NOT EXISTS jobs_source ON jobs(source,active)')
        if seed and not self.jobs():
            self.upsert(json.loads(Path(seed).read_text()))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ---- catalog -------------------------------------------------------------------------
    @staticmethod
    def _hash(job):
        return hashlib.sha1(json.dumps(job, sort_keys=True).encode()).hexdigest()

    def _upsert(self, db, jobs, today):
        stats = {'added': 0, 'updated': 0, 'unchanged': 0, 'reopened': 0}
        for j in jobs:
            h = self._hash(j)
            row = db.execute('SELECT rowid, content_hash, active FROM jobs WHERE id=?', (j['id'],)).fetchone()
            skills = ' '.join(j['skills'])
            if row is None:
                cur = db.execute('INSERT INTO jobs(id,payload,active,source,content_hash,first_seen,last_seen) VALUES(?,?,1,?,?,?,?)',
                                 (j['id'], json.dumps(j), j.get('source', ''), h, today, today))
                db.execute('INSERT INTO jobs_fts(rowid,id,title,description,skills) VALUES(?,?,?,?,?)', (cur.lastrowid, j['id'], j['title'], j['description'], skills))
                stats['added'] += 1
            elif row['content_hash'] == h and row['active']:
                db.execute('UPDATE jobs SET last_seen=? WHERE id=?', (today, j['id']))
                stats['unchanged'] += 1
            else:
                was_active = bool(row['active'])
                db.execute('UPDATE jobs SET payload=?,active=1,source=?,content_hash=?,last_seen=?,closed_at=NULL WHERE id=?', (json.dumps(j), j.get('source', ''), h, today, j['id']))
                db.execute('DELETE FROM jobs_fts WHERE rowid=?', (row['rowid'],))
                db.execute('INSERT INTO jobs_fts(rowid,id,title,description,skills) VALUES(?,?,?,?,?)', (row['rowid'], j['id'], j['title'], j['description'], skills))
                stats['updated' if was_active else 'reopened'] += 1
        return stats

    def _bump(self, db):
        db.execute("INSERT INTO meta VALUES('version','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")

    def version(self):
        with self.connect() as db:
            r = db.execute("SELECT value FROM meta WHERE key='version'").fetchone()
            return int(r[0]) if r else 0

    def upsert(self, jobs):
        """Insert or update. Rows omitted from `jobs` are left alone (use sync() for a full board)."""
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        with self.connect() as db:
            stats = self._upsert(db, jobs, today)
            if stats['added'] or stats['updated'] or stats['reopened']: self._bump(db)
        return stats

    def sync(self, source, jobs):
        """Make `source` match `jobs` exactly, in one transaction: add new, update changed,
        and mark roles that disappeared from the source as closed (kept for audit, not searchable).
        Only call this after a fully successful fetch of that source."""
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        ids = {j['id'] for j in jobs}
        with self.connect() as db:
            stats = self._upsert(db, jobs, today)
            gone = [r for r in db.execute('SELECT rowid,id FROM jobs WHERE source=? AND active=1', (source,)) if r['id'] not in ids]
            for r in gone:
                db.execute('UPDATE jobs SET active=0, closed_at=? WHERE id=?', (today, r['id']))
                db.execute('DELETE FROM jobs_fts WHERE rowid=?', (r['rowid'],))
            stats['closed'] = len(gone)
            if stats['added'] or stats['updated'] or stats['reopened'] or gone: self._bump(db)
        return stats

    def jobs(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM jobs WHERE active=1 ORDER BY id')]

    def counts(self):
        with self.connect() as db:
            a, c = db.execute('SELECT sum(active=1), sum(active=0) FROM jobs').fetchone()
            v = db.execute('SELECT count(*) FROM vectors v JOIN jobs j ON j.id=v.id WHERE j.active=1').fetchone()[0]
            return {'active': a or 0, 'closed': c or 0, 'embedded_active': v}

    def meta(self, key, default=None):
        with self.connect() as db:
            r = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            return json.loads(r[0]) if r else default

    def set_meta(self, key, value):
        with self.connect() as db:
            db.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))

    # ---- vectors (incremental re-embedding) ---------------------------------------------
    def vectors(self, model):
        with self.connect() as db:
            return {r[0]: (r[1], np.frombuffer(r[2], dtype=np.float32)) for r in db.execute('SELECT id,text_hash,vec FROM vectors WHERE model=?', (model,))}

    def put_vectors(self, model, items):
        with self.connect() as db:
            db.executemany('INSERT INTO vectors VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET text_hash=excluded.text_hash,model=excluded.model,vec=excluded.vec',
                           [(i, h, model, np.asarray(v, dtype=np.float32).tobytes()) for i, h, v in items])

    def drop_inactive_vectors(self):
        with self.connect() as db:
            return db.execute('DELETE FROM vectors WHERE id IN (SELECT id FROM jobs WHERE active=0)').rowcount

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
