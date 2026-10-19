"""Read original Studio SQLite and migrate to a NEW application directory.

No source writes. Preflight is the default; --apply is required for migration.
"""
import argparse
import copy
import hashlib
import json
import math
import shutil
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from store import Store, KINDS
from services import now


def stamp(value):
    return datetime.fromtimestamp(float(value or 0), timezone.utc).isoformat()


def read_json(value, default):
    return json.loads(value) if value else default


def key(value):
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def annotations(raw, image_id, classes):
    result = []
    for index, a in enumerate(read_json(raw, [])):
        if a['cls'] not in classes:
            raise ValueError('Unknown annotation class: '+a['cls'])
        group = 'original-'+key(f'{image_id}/{index}/{a.get("id", "")}')
        for component, polygon in enumerate(a.get('polys', [])):
            if len(polygon)<6 or len(polygon)%2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in polygon):
                raise ValueError('Malformed polygon: '+image_id)
            result.append(dict(id=group+'-'+str(component), group_id=group,
                original_id=a.get('id'), class_id=classes[a['cls']]['id'],
                points=[polygon[i:i+2] for i in range(0,len(polygon),2)],
                source='auto' if a.get('src') in ('auto','pred') else 'human',
                original_source=a.get('src'), **({'score':a['score']} if 'score' in a else {})))
    return result


def preflight(source, destination, model_db):
    source=Path(source).resolve(strict=True); dest=Path(destination).resolve()
    if dest.exists() or source==dest or source in dest.parents or dest in source.parents:
        raise ValueError('Choose a NEW destination separate from the original export')
    db=source/'cksgur_studio.db'
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':
            raise ValueError('Source database integrity check failed')
        tables={x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'images','batches','classes','versions','version_images'}<=tables:
            raise ValueError('Unrecognized original Studio schema')
        records={kind:[] for kind in KINDS}
        source_classes=[dict(x) for x in c.execute('SELECT * FROM classes ORDER BY ord')]
        if len({x['owner'] for x in source_classes})!=1:
            raise ValueError('Export must contain exactly one owner')
        records['classes']=[dict(id=str(i+1),name=x['name'],color=x['color'],
            normal=x['name'] in ('water','SerialNumber'),shortcut=str(i+1)) for i,x in enumerate(source_classes)]
        classes={x['name']:x for x in records['classes']}
        batch_map={}
        for row in c.execute('SELECT * FROM batches ORDER BY created'):
            x=dict(row); stage={'todo':'new','labeling':'labeling','review':'review','done':'done'}.get(x['stage'])
            if stage is None: raise ValueError('Unknown batch stage')
            item=dict(id='batch-'+key(x['owner']+'/'+x['name']),name=x['name'],stage=stage,
                      note=x['note'],created=stamp(x['created']),updated=stamp(x['updated']))
            records['batches'].append(item);batch_map[x['name']]=item['id']
        files={}; outside=0
        for row in c.execute('SELECT * FROM images ORDER BY created,id'):
            x=dict(row); name=Path(x['file']).name
            if name!=x['file'].replace('\\','/').split('/')[-1]:raise ValueError('Invalid filename')
            file=(source/'images'/name).resolve(strict=True)
            if file.parent!=(source/'images').resolve():raise ValueError('Image outside export')
            with file.open('rb') as f:
                sha1=hashlib.file_digest(f,'sha1').hexdigest()
                f.seek(0);sha256=hashlib.file_digest(f,'sha256').hexdigest()
            if x['sha1'] and sha1!=x['sha1']:raise ValueError('Source image hash mismatch: '+name)
            if x['width']<1 or x['height']<1:raise ValueError('Invalid image dimensions')
            files[name]=(file,sha256)
            batch_name=x['batch']
            if batch_name not in batch_map:
                if batch_name=='':
                    batch_name='(배치 없음)'
                if batch_name not in batch_map:
                    item=dict(id='batch-'+key(x['owner']+'/'+batch_name),name=batch_name or '(배치 없음)',stage='new',created=stamp(x['created']))
                    batch_map[batch_name]=item['id'];records['batches'].append(item)
            status='ambiguous' if x['ambiguous'] else 'reviewed' if x['reviewed'] else 'auto' if any(a.get('src') in ('auto','pred') for a in read_json(x['anns'],[])) else 'todo'
            split='' if x['split'] in ('none','',None) else x['split']
            if split not in ('','train','valid','test'):raise ValueError('Unknown split')
            anns=annotations(x['anns'],x['id'],classes)
            outside+=sum(any(px<0 or px>x['width'] or py<0 or py>x['height'] for px,py in a['points']) for a in anns)
            records['images'].append(dict(id=x['id'],name=x['name'],file=name,width=x['width'],height=x['height'],
                sha256=sha256,batch=batch_map[batch_name],sensor=x['sensor'].removeprefix('Sensor'),split=split,
                tags=read_json(x['tags'],[]),note=x['note'],status=status,annotations=anns,
                deleted=bool(x['deleted']),revision=1,created=stamp(x['created']),updated=stamp(x['updated']),
                original_reviewed=bool(x['reviewed']),original_ambiguous=bool(x['ambiguous']),
                original_review_source=x['review_src'],original_reviewed_by=x['reviewed_by'],
                original_batch=x['batch'],original_source=x['source'],shot_time=x['shot_time']))
        image_map={x['id']:x for x in records['images']}
        snapshots=defaultdict(list)
        for row in c.execute('SELECT * FROM version_images ORDER BY num,rowid'):
            x=dict(row)
            if x['image_id'] not in image_map:raise ValueError('Snapshot references missing image')
            current=image_map[x['image_id']]
            # Snapshot labels and split are independent of today's image/review/trash state.
            snap={k:current[k] for k in ('id','batch','sensor','sha256','created','updated','tags','note')}
            file=Path(x['file']).name
            if file not in files:raise ValueError('Missing snapshot file: '+file)
            snap.update(name=x['name'],file=file,sha256=files[file][1],width=x['width'],height=x['height'],split=x['split'],
                        annotations=annotations(x['anns'],x['image_id'],classes),status='todo',review_unknown=True,deleted=False,revision=1)
            snapshots[x['num']].append(snap)
        for row in c.execute('SELECT * FROM versions ORDER BY created,num'):
            x=dict(row); images=snapshots.pop(x['num'],[])
            counts=dict(Counter(i['split'] for i in images))
            expected=read_json(x['counts'],{}).get('splits')
            if expected and any(counts.get(k,0)!=expected.get(k,0) for k in set(counts)|set(expected)):
                raise ValueError('Version split count mismatch: '+str(x['num']))
            records['versions'].append(dict(id='source-v'+str(x['num']),name=x['name'],note=x['note'],
                created=stamp(x['created']),images=images,classes=records['classes'],rules=read_json(x['rule'],{}),
                counts=counts,original_number=x['num'],imported=True))
        if snapshots:raise ValueError('Snapshots reference missing version')
        archive={table:[dict(r) for r in c.execute('SELECT * FROM '+table)]
                 for table in ('history','preds','jobs') if table in tables}
    with closing(sqlite3.connect(Path(model_db).resolve(strict=True).as_uri()+'?mode=ro',uri=True)) as c:
        records['models']=[json.loads(r[0]) for r in c.execute("SELECT payload FROM studio_records WHERE kind='models'")]
    versions={v['id']:v for v in records['versions']}
    for m in records['models']:
        if [x['name'] for x in m['classes']]!=list(classes):raise ValueError('Model class order mismatch')
        for field in ('checkpoint','config'):
            if not Path(m[field]).is_file():raise ValueError('Missing model artifact')
        original=m.get('original_model_info',{}).get('trained_on')
        if original is not None:
            m['version_id']='source-v'+str(original)
            if m['version_id'] not in versions:raise ValueError('Missing model training version')
            m['version_name']=versions[m['version_id']]['name']
        m['evaluations']={('source-v'+k.split(':cksgur:v',1)[1] if ':cksgur:v' in k else k):v for k,v in m.get('evaluations',{}).items()}
    records['settings']=[dict(id='project_name',value='dxel Studio · 케이블')]
    records['events']=[dict(id='original-import',action='원본 DB 가져오기',detail=f'{len(image_map)}장 · {len(records["batches"])}개 배치',created=now())]
    summary=dict(images=len(image_map),visible=sum(not i['deleted'] for i in image_map.values()),
        trash=sum(i['deleted'] for i in image_map.values()),batches=len(records['batches']),
        stages=dict(Counter(b['stage'] for b in records['batches'])),
        statuses=dict(Counter(i['status'] for i in image_map.values() if not i['deleted'])),
        versions=len(records['versions']),models=len(records['models']),
        polygons=sum(len(i['annotations']) for i in image_map.values()),outside_polygons_preserved=outside,
        archive_counts={k:len(v) for k,v in archive.items()},destination=str(dest))
    return records,files,archive,dest,summary


def run(source,destination,model_db,apply=False):
    records,files,archive,dest,summary=preflight(source,destination,model_db)
    if not apply:return dict(summary,applied=False)
    staging=dest.with_name('.'+dest.name+'-importing')
    if staging.exists() or dest.exists():raise ValueError('Destination conflict')
    staging.mkdir(parents=True);(staging/'media').mkdir()
    for index,(name,(source_file,expected)) in enumerate(files.items()):
        target=staging/'media'/name
        shutil.copy2(source_file,target)
        with target.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=expected:raise ValueError('Copy verification failed')
        if (index+1)%1000==0:print('Copied',index+1,'/',len(files),flush=True)
    store=Store(staging/'studio.sqlite')
    with store.connection() as c:
        c.execute('DELETE FROM studio_records')
        for kind,items in records.items():
            c.executemany('INSERT INTO studio_records VALUES(?,?,?)',
                ((kind,i['id'],json.dumps(i,ensure_ascii=False,allow_nan=False)) for i in items))
        c.execute('CREATE TABLE original_archive(kind TEXT,row_num INTEGER,payload TEXT,PRIMARY KEY(kind,row_num))')
        for kind,items in archive.items():
            c.executemany('INSERT INTO original_archive VALUES(?,?,?)',
                ((kind,i,json.dumps(x,ensure_ascii=False,allow_nan=False)) for i,x in enumerate(items)))
    (staging/'import-report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    if staging.resolve().parent!=dest.parent or dest.exists():raise ValueError('Destination changed')
    staging.rename(dest)
    return dict(summary,applied=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source');p.add_argument('--destination',required=True);p.add_argument('--model-db',required=True);p.add_argument('--apply',action='store_true')
    args=p.parse_args()
    print(json.dumps(run(args.source,args.destination,args.model_db,args.apply),ensure_ascii=False,indent=2))
