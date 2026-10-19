"""python inspect_db.py ORIGINAL.sqlite -- read-only schema inspection."""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='원본 SQLite DB 구조만 읽습니다. 데이터를 수정하지 않습니다.')
    p.add_argument('database')
    a = p.parse_args()
    path = Path(a.database).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as c:
        rows = c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    print(json.dumps(dict(file=path.name, tables=[dict(name=n,sql=s) for n,s in rows]),ensure_ascii=False,indent=2))
