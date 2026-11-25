import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.business import DomainIssue

SCHEMA = '''CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, report TEXT NOT NULL, created TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', revision INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', reviewed TEXT,
    decisions TEXT NOT NULL DEFAULT '{}'
);'''

MATERIALS = '''CREATE TABLE IF NOT EXISTS materials (
    case_key TEXT NOT NULL, seq INTEGER NOT NULL, run_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
    PRIMARY KEY (case_key, run_id)
);'''


def decode(row):
    result = dict(row)
    result['report'] = json.loads(result['report'])
    result['decisions'] = json.loads(result.get('decisions') or '{}')
    return result


class Store:
    def __init__(self, path):
        self.path = Path(path)

    def _open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute(SCHEMA)
        db.execute(MATERIALS)
        columns = {item['name'] for item in db.execute('PRAGMA table_info(runs)')}
        if 'decisions' not in columns:
            try:
                db.execute("ALTER TABLE runs ADD COLUMN decisions TEXT NOT NULL DEFAULT '{}'")
            except sqlite3.OperationalError:
                # 并发启动时另一连接可能已完成迁移，确认后再继续。
                columns = {item['name'] for item in db.execute('PRAGMA table_info(runs)')}
                if 'decisions' not in columns:
                    raise
        return db

    @contextmanager
    def connect(self):
        with closing(self._open()) as db, db:
            yield db

    @contextmanager
    def transaction(self):
        """BEGIN IMMEDIATE 让签发与材料更正在写锁内串行。"""
        with closing(self._open()) as db:
            db.isolation_level = None
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
            except BaseException:
                db.execute('ROLLBACK')
                raise
            else:
                db.execute('COMMIT')

    def register(self, run_id, report):
        with self.transaction() as db:
            db.execute('INSERT INTO runs(id,report,created) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING',
                       (run_id, json.dumps(report, ensure_ascii=False), report['manifest']['created']))
            seq = db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM materials').fetchone()[0]
            for case, fingerprint in report.get('materials', {}).items():
                db.execute('INSERT OR IGNORE INTO materials(case_key,seq,run_id,fingerprint) VALUES (?,?,?,?)',
                           (case, seq, run_id, fingerprint))
        return self.load(run_id)

    def load(self, run_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise DomainIssue('RUN_NOT_FOUND')
        return decode(row)

    def list(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                'SELECT id,created,status,revision,note FROM runs ORDER BY created DESC,id LIMIT 50')]

    def superseded(self, db, run_id, cases):
        """已生效的新版材料优先级更高：旧批次不能按旧材料签发。"""
        for case in cases:
            current = db.execute(
                'SELECT m.run_id,m.fingerprint,m.seq FROM materials m '
                'WHERE m.case_key=? ORDER BY m.seq DESC LIMIT 1', (case,)).fetchone()
            if current is None or current['run_id'] == run_id:
                continue
            old = db.execute('SELECT seq,fingerprint FROM materials WHERE case_key=? AND run_id=?',
                             (case, run_id)).fetchone()
            if old is not None and old['seq'] < current['seq'] and old['fingerprint'] != current['fingerprint']:
                return True
        return False

    def decide(self, run_id, revision, policy, now):
        """在写锁内按最新状态判定并写入，返回更新后的批次。"""
        with self.transaction() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
            if row is None:
                raise DomainIssue('RUN_NOT_FOUND')
            current = decode(row)
            if current['revision'] != revision:
                raise DomainIssue('STALE_REVIEW')
            if current['status'] == 'APPROVED':
                raise DomainIssue('RUN_FINALIZED')
            status, decisions, note = policy(db, current)
            cursor = db.execute(
                'UPDATE runs SET status=?,note=?,reviewed=?,revision=revision+1,decisions=? '
                'WHERE id=? AND revision=?',
                (status, note, now, json.dumps(decisions, ensure_ascii=False), run_id, revision))
            if cursor.rowcount != 1:
                raise DomainIssue('STALE_REVIEW')
        return self.load(run_id)
