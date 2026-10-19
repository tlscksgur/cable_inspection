"""Preflight and import this application's portable JSON backup into a NEW directory.

Original dxel databases require a schema mapping after inspection; they are never
guessed or opened for writing by this command.
"""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from services import Studio, uid
from store import KINDS, Store


def preflight(backup, source_media, destination):
    backup=Path(backup).resolve(strict=True); source=Path(source_media).resolve(strict=True); dest=Path(destination).resolve()
    if dest.exists(): raise ValueError('대상 폴더가 이미 있습니다. 새로운 폴더를 지정하세요.')
    if not source.is_dir(): raise ValueError('원본 media 폴더가 필요합니다')
    document=json.loads(backup.read_text(encoding='utf-8-sig'))
    if document.get('format')!='dxel-studio-rebuild' or document.get('schema_version')!=1:
        raise ValueError('이 앱의 JSON 백업이 아닙니다. 원본 DB는 스키마 확인 후 변환해야 합니다.')
    records=document['records']; files={}
    if set(records)!=set(KINDS): raise ValueError('백업의 테이블 구성이 올바르지 않습니다')
    for kind,items in records.items():
        if not isinstance(items,list) or len({x['id'] for x in items})!=len(items): raise ValueError('중복 ID 또는 데이터 형식 오류')
        for x in items:
            if not isinstance(x['id'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]+',x['id']): raise ValueError('유효하지 않은 ID')
    classes={c['id'] for c in records['classes']}; batches={b['id'] for b in records['batches']}
    def image(x,version_classes):
        if x['file']!=Path(x['file']).name or '/' in x['file'] or '\\' in x['file']: raise ValueError('사진 경로가 올바르지 않습니다')
        if x['width']<1 or x['height']<1: raise ValueError('이미지 크기 오류')
        for a in x['annotations']:
            if a['class_id'] not in version_classes or len(a['points'])<3: raise ValueError('라벨 참조 오류')
            if any(len(p)!=2 or not 0<=p[0]<=x['width'] or not 0<=p[1]<=x['height'] for p in a['points']): raise ValueError('사진 범위를 벗어난 라벨')
        path=(source/x['file']).resolve(strict=True)
        if path.parent!=source: raise ValueError('media 범위를 벗어난 사진')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if x.get('sha256') and digest!=x['sha256']: raise ValueError('원본 사진 해시 불일치: '+x['name'])
        files[x['file']]=(path,digest)
    for x in records['images']:
        if x['batch'] not in batches: raise ValueError('배치 참조 오류')
        image(x,classes)
    for v in records['versions']:
        cls={c['id'] for c in v['classes']}
        for x in v['images']: image(x,cls)
    return records,files,dest


def run(backup,source_media,destination,apply=False):
    records,files,dest=preflight(backup,source_media,destination)
    result=dict(preflight='passed',apply=apply,destination=str(dest),images=len(records['images']),files=len(files),versions=len(records['versions']))
    if not apply: return result
    # All source files and final destinations were validated before any copying.
    staging=dest.with_name('.'+dest.name+'-importing-'+uid()).resolve()
    if staging.parent!=dest.parent or dest.exists(): raise ValueError('대상 경로가 변경되었습니다')
    staging.mkdir(parents=True); (staging/'media').mkdir()
    for name,(source,digest) in files.items():
        target=staging/'media'/name
        if target.exists(): raise ValueError('대상 파일 충돌')
        shutil.copy2(source,target)
        if hashlib.sha256(target.read_bytes()).hexdigest()!=digest: raise ValueError('복사 검증 실패')
    store=Store(staging/'studio.sqlite')
    with store.connection() as c:
        c.execute('DELETE FROM studio_records')
        for kind,items in records.items():
            for x in items:
                if kind=='jobs' and x.get('status') in ('running','queued'): x={**x,'status':'interrupted','message':'가져온 작업입니다. 실행 상태는 복원하지 않습니다.'}
                c.execute('INSERT INTO studio_records VALUES(?,?,?)',(kind,x['id'],json.dumps(x,ensure_ascii=False,allow_nan=False)))
    # Both resolved paths stay under the explicitly selected destination parent.
    if staging.resolve().parent!=dest.parent or dest.exists(): raise ValueError('가져오기 대상이 변경되었습니다')
    staging.rename(dest)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description='백업과 원본 사진을 보존하며 새 저장소로 가져옵니다. 기본은 검사만 수행합니다.')
    p.add_argument('backup');p.add_argument('--source-media',required=True);p.add_argument('--destination',required=True);p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    try: print(json.dumps(run(a.backup,a.source_media,a.destination,a.apply),ensure_ascii=False,indent=2))
    except (ValueError,KeyError,OSError) as e:p.exit(1,str(e)+'\n')
