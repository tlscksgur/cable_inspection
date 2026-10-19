"""Isolated application storage. Never opens an unrecognized DB for writing."""
import json
import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path

KINDS = ('images', 'batches', 'classes', 'versions', 'models', 'jobs', 'events', 'settings')
DEFAULT_CLASSES = [
    ('bulge', '#e87542'), ('dent', '#a280db'), ('scratch', '#d7a53e'),
    ('contamination', '#d9677f'), ('blueLine', '#448fda'), ('water', '#35a9ad'),
    ('SerialNumber', '#72916d'), ('cut', '#8e6c56'),
]


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size:
            uri = self.path.as_uri() + '?mode=ro'
            with closing(sqlite3.connect(uri, uri=True)) as c:
                tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'studio_meta', 'studio_records'} <= tables:
                    raise ValueError('알 수 없는 DB입니다. 원본 DB를 덮어쓰지 않습니다. inspect_db.py로 먼저 확인하세요.')
                row = c.execute("SELECT value FROM studio_meta WHERE key='schema_version'").fetchone()
                if not row or row[0] != '1':
                    raise ValueError('지원하지 않는 DB 스키마 버전입니다.')
        with self.connection() as c:
            c.execute('CREATE TABLE IF NOT EXISTS studio_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS studio_records(kind TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(kind,id))')
            c.execute("INSERT OR IGNORE INTO studio_meta VALUES('schema_version','1')")
        if not self.all('classes'):
            self.put_many('classes', [dict(id=str(i+1), name=n, color=color, normal=n in ('water', 'SerialNumber'), shortcut=str(i+1)) for i,(n,color) in enumerate(DEFAULT_CLASSES)])

    @contextmanager
    def connection(self):
        c = sqlite3.connect(self.path, timeout=30)
        try:
            c.execute('PRAGMA foreign_keys=ON')
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def all(self, kind):
        with self.connection() as c:
            return [json.loads(r[0]) for r in c.execute('SELECT payload FROM studio_records WHERE kind=? ORDER BY rowid',(kind,))]

    def get(self, kind, key):
        with self.connection() as c:
            row = c.execute('SELECT payload FROM studio_records WHERE kind=? AND id=?',(kind,str(key))).fetchone()
        if row is None:
            raise KeyError(f'{kind}: 항목을 찾을 수 없습니다')
        return json.loads(row[0])

    def put(self, kind, item):
        self.put_many(kind, [item])
        return item

    def summaries(self, kind, excluded):
        paths=['$.'+name for name in excluded]
        placeholders=','.join('?' for _ in paths)
        with self.connection() as c:
            return [json.loads(row[0]) for row in c.execute(
                f'SELECT json_remove(payload,{placeholders}) FROM studio_records WHERE kind=? ORDER BY rowid',
                (*paths,kind))]

    def put_many(self, kind, items):
        if kind not in KINDS:
            raise ValueError('지원하지 않는 종류')
        with self.connection() as c:
            c.executemany('INSERT INTO studio_records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload',[(kind,str(x['id']),json.dumps(x,ensure_ascii=False,allow_nan=False)) for x in items])

    def backup(self):
        with self.connection() as c:
            records = {kind: [] for kind in KINDS}
            for kind, payload in c.execute('SELECT kind,payload FROM studio_records ORDER BY rowid'):
                records[kind].append(json.loads(payload))
        return dict(format='dxel-studio-rebuild', schema_version=1, records=records)

