import hashlib
import io
import json
import math
import re
import shutil
import time
import uuid
import zipfile
from copy import deepcopy
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def uid():
    return uuid.uuid4().hex[:16]


def now():
    return datetime.now(timezone.utc).isoformat()


def integer(v, low, high):
    if isinstance(v, bool) or int(v) != float(v) or not low <= int(v) <= high:
        raise ValueError(f'{low}~{high} 범위의 정수가 필요합니다')
    return int(v)


class Studio:
    def __init__(self, store, data):
        self.store = store
        self.data = Path(data).resolve()
        (self.data/'media').mkdir(parents=True, exist_ok=True)

    def event(self, action, detail=''):
        self.store.put('events', dict(id=uid(), action=action, detail=detail, created=now()))

    def state(self, compact=False):
        result = {k:self.store.all(k) for k in ('images','batches','classes','models','jobs')}
        if compact:
            fields=('id','name','file','width','height','batch','sensor','split','tags','note','status','deleted','revision','created','updated','shot_time')
            result['images']=[dict({k:x[k] for k in fields if k in x},
                annotations=[dict(class_id=a['class_id']) for a in x.get('annotations',[])],
                _summary=True) for x in result['images']]
        result['versions'] = self.store.summaries('versions', ('images','classes'))
        result['events'] = self.store.all('events')[-40:][::-1]
        result['settings'] = {x['id']:x.get('value') for x in self.store.all('settings')}
        return result

    def model_for_use(self, key):
        model = self.store.get('models', key)
        if model.get('deleted'):
            raise ValueError('휴지통에 있는 모델입니다. 복원한 뒤 사용하세요.')
        return model

    def update_model(self, key, body):
        if not body or set(body)-{'name', 'active', 'deleted'}:
            raise ValueError('지원하지 않는 모델 변경')
        for flag in ('active', 'deleted'):
            if flag in body and not isinstance(body[flag], bool):
                raise ValueError('모델 상태는 참/거짓으로 지정하세요')
        models = self.store.all('models')
        model = next((m for m in models if m['id']==key), None)
        if model is None:
            raise KeyError('모델을 찾을 수 없습니다')
        was_deleted = bool(model.get('deleted'))
        deleting = body.get('deleted', was_deleted)
        if deleting and (body.get('active') or 'name' in body):
            raise ValueError('휴지통의 모델은 복원한 뒤 변경하세요')
        if deleting and not was_deleted:
            for job in self.store.all('jobs'):
                spec = job.get('spec', {})
                if job['status'] in ('running', 'queued') and (spec.get('model', {}).get('id')==key or spec.get('checkpoint')==model['checkpoint']):
                    raise ValueError('이 모델을 사용하는 작업이 있습니다. 작업을 마친 뒤 삭제하세요.')
        if 'name' in body:
            model['name'] = str(body['name']).strip()[:160]
            if not model['name']:
                raise ValueError('이름을 입력하세요')
        if 'deleted' in body:
            model.update(deleted=deleting, deleted_at=now() if deleting else None)
            if deleting or was_deleted:
                model['active'] = False
        if body.get('active'):
            if deleting:
                raise ValueError('휴지통에 있는 모델은 사용할 수 없습니다')
            for item in models:
                item['active'] = item['id']==key and not item.get('deleted')
        elif 'active' in body:
            model['active'] = False
        self.store.put_many('models', models)
        if deleting != was_deleted:
            self.event('모델 휴지통 이동' if deleting else '모델 복원', model['name'])
        return model

    def upload(self, content, name, meta):
        name = Path(name.replace('\\','/')).name[:240]
        ext = Path(name).suffix.lower()
        if ext not in ('.jpg','.jpeg','.png','.webp','.bmp'):
            raise ValueError('JPG, PNG, WEBP, BMP 사진을 선택하세요')
        if not content or len(content)>80*1024*1024:
            raise ValueError('파일은 80MB 이하여야 합니다')
        # Require a matching magic number. Uploaded HTML/SVG is never served.
        valid = ((ext in ('.jpg','.jpeg') and content.startswith(b'\xff\xd8\xff')) or
                 (ext=='.png' and content.startswith(b'\x89PNG\r\n\x1a\n')) or
                 (ext=='.webp' and content[:4]==b'RIFF' and content[8:12]==b'WEBP') or
                 (ext=='.bmp' and content[:2]==b'BM'))
        if not valid:
            raise ValueError('확장자와 사진 내용이 일치하지 않습니다')
        w,h=integer(meta.get('width',0),1,100000),integer(meta.get('height',0),1,100000)
        digest=hashlib.sha256(content).hexdigest()
        for x in self.store.all('images'):
            if not meta.get('allow_duplicates') and (x.get('sha256')==digest or x['name']==name):
                return dict(skipped=True, name=name)
        batch = str(meta.get('batch','')).strip() or ('업로드 '+datetime.now().strftime('%m/%d %H:%M'))
        b = next((x for x in self.store.all('batches') if x['name']==batch), None)
        if not b:
            b=self.store.put('batches',dict(id=uid(), name=batch, stage='new', created=now()))
        split=meta.get('split','')
        if split not in ('','train','valid','test'):
            raise ValueError('잘못된 분할')
        image_id=uid()
        path=self.data/'media'/(image_id+ext)
        path.write_bytes(content)
        sensor=re.search(r'Sensor([A-Z])',name,re.I)
        tags=[str(t).strip()[:80] for t in meta.get('tags',[]) if str(t).strip()]
        item=dict(id=image_id,name=name,file=path.name,width=w,height=h,sha256=digest,
                  batch=b['id'],sensor=sensor[1].upper() if sensor else '',split=split,
                  tags=tags,note='',status='todo',annotations=[],deleted=False,revision=1,created=now(),updated=now())
        self.store.put('images',item)
        self.event('사진 추가',name)
        return item

    def validate_annotations(self, annotations, image, originals=None):
        if not isinstance(annotations,list) or len(annotations)>10000:
            raise ValueError('라벨 형식이 올바르지 않습니다')
        classes={c['id'] for c in self.store.all('classes')}
        existing={a['id']:a for a in (originals or [])}
        out=[]
        for a in annotations:
            if a.get('class_id') not in classes:
                raise ValueError('등록된 클래스를 선택하세요')
            points=a.get('points',[])
            old=existing.get(a.get('id'))
            if old and old['class_id']==a['class_id'] and old['points']==points:
                # Preserve unchanged imported polygons, including original boundary
                # overhang. Newly drawn/edited coordinates still require bounds checks.
                out.append(deepcopy(old))
                continue
            if not isinstance(points,list) or not 3<=len(points)<=20000:
                raise ValueError('폴리곤에는 3개 이상의 점이 필요합니다')
            clean=[]
            for p in points:
                if len(p)!=2 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in p):
                    raise ValueError('좌표가 올바르지 않습니다')
                if not (0<=p[0]<=image['width'] and 0<=p[1]<=image['height']):
                    raise ValueError('이미지 범위를 벗어난 라벨입니다')
                clean.append([round(float(p[0]),3),round(float(p[1]),3)])
            area=abs(sum(clean[i][0]*clean[(i+1)%len(clean)][1]-clean[(i+1)%len(clean)][0]*clean[i][1] for i in range(len(clean))))/2
            if area<1:
                raise ValueError('폴리곤 면적이 너무 작습니다')
            out.append(dict(id=str(a.get('id') or uid())[:80],class_id=a['class_id'],points=clean,source=a.get('source','human')))
            if old and old.get('group_id'):
                out[-1]['group_id']=old['group_id']
        return out

    def update_image(self, key, body):
        x=self.store.get('images',key)
        if body.get('revision')!=x['revision']:
            raise ValueError('다른 창에서 수정되었습니다. 새로고침 후 다시 저장하세요.')
        for k in ('note','tags','split','status','batch','deleted'):
            if k in body: x[k]=body[k]
        if x['split'] not in ('','train','valid','test') or x['status'] not in ('todo','reviewed','ambiguous','auto','ai_reviewed'):
            raise ValueError('잘못된 상태 또는 분할')
        self.store.get('batches',x['batch'])
        if not isinstance(x['note'],str) or len(x['note'])>10000 or not isinstance(x['tags'],list) or any(not isinstance(t,str) for t in x['tags']):
            raise ValueError('메모 또는 태그 형식 오류')
        if 'annotations' in body:
            x['annotations']=self.validate_annotations(body['annotations'],x,x['annotations'])
            # A changed label must be explicitly reviewed again, unless saved as reviewed together.
            if 'status' not in body: x['status']='todo'
        x['revision']+=1
        x['updated']=now()
        self.store.put('images',x)
        self.event('사진 수정',x['name'])
        return x

    def bulk(self, body):
        ids=body.get('ids',[])
        if not ids or len(ids)>20000 or len(ids)!=len(set(ids)):
            raise ValueError('사진을 선택하세요')
        fields=body.get('changes',{})
        if not fields or set(fields)-{'status','split','batch','deleted','tags'}:
            raise ValueError('지원하지 않는 일괄 작업')
        if 'status' in fields and fields['status'] not in ('todo','reviewed','ambiguous','auto','ai_reviewed'): raise ValueError('잘못된 상태')
        if 'split' in fields and fields['split'] not in ('','train','valid','test'): raise ValueError('잘못된 분할')
        if 'batch' in fields: self.store.get('batches',fields['batch'])
        if 'deleted' in fields and not isinstance(fields['deleted'],bool): raise ValueError('잘못된 휴지통 값')
        if 'tags' in fields and (not isinstance(fields['tags'],list) or any(not isinstance(t,str) for t in fields['tags'])): raise ValueError('잘못된 태그')
        items=[self.store.get('images',key) for key in ids]
        for x in items:
            x.update(fields,revision=x['revision']+1,updated=now())
        self.store.put_many('images',items)
        self.event('일괄 수정',f'{len(items)}장')
        return dict(count=len(items))

    def save_batch(self, body):
        b=self.store.get('batches',body['id']) if body.get('id') else dict(id=uid(),created=now())
        b.update(name=str(body.get('name',b.get('name',''))).strip()[:200],stage=body.get('stage',b.get('stage','new')))
        if not b['name'] or b['stage'] not in ('new','labeling','review','done'): raise ValueError('배치 이름과 단계를 확인하세요')
        self.store.put('batches',b)
        self.event('배치 변경',b['name'])
        return b

    def merge_batches(self, body):
        target=body['target']; self.store.get('batches',target)
        sources=set(body['sources'])-{target}
        for key in sources: self.store.get('batches',key)
        changed=[]
        for x in self.store.all('images'):
            if x['batch'] in sources:
                x.update(batch=target,revision=x['revision']+1,updated=now()); changed.append(x)
        self.store.put_many('images',changed)
        self.event('배치 합치기',f'{len(changed)}장 이동')
        return dict(count=len(changed))

    def save_class(self, body):
        name=str(body.get('name','')).strip()[:80]
        color=body.get('color','#6881ab')
        if not name or not re.fullmatch(r'#[0-9a-fA-F]{6}',color): raise ValueError('클래스 이름과 색상을 확인하세요')
        if any(c['name']==name and c['id']!=body.get('id') for c in self.store.all('classes')): raise ValueError('같은 클래스 이름이 있습니다')
        item=dict(id=body.get('id') or uid(),name=name,color=color,normal=bool(body.get('normal')),shortcut=str(body.get('shortcut',''))[:1])
        self.store.put('classes',item)
        self.event('클래스 저장',name)
        return item

    def split(self, body, apply=False):
        train,valid,test=[integer(body.get(k,v),0,100) for k,v in [('train',70),('valid',20),('test',10)]]
        if train+valid+test!=100: raise ValueError('분할 비율의 합은 100이어야 합니다')
        gap=integer(body.get('gap',10),0,86400)
        scope=body.get('scope','done'); batches={b['id']:b for b in self.store.all('batches')}
        images=[x for x in self.store.all('images') if not x['deleted'] and (scope=='all' or not x['split']) and (scope!='done' or batches[x['batch']]['stage']=='done')]
        # Adjacent original captures stay together, even across upload batches.
        def capture(x):
            m=re.search(r'(20\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{3})',x['name'])
            if m:
                try: return datetime(*map(int,m.groups()[:6])).timestamp()+int(m[7])/1000
                except ValueError: pass
            return None
        groups=[]; last={}
        for x in sorted(images,key=lambda x:(x.get('sensor',''),capture(x) or 0,x['name'])):
            stamp=capture(x); sensor=x.get('sensor','')
            if stamp is not None and sensor in last and stamp-last[sensor][0]<=gap:
                group=last[sensor][1]
            else:
                group=[]; groups.append(group)
            group.append(x)
            if stamp is not None: last[sensor]=(stamp,group)
        assignment=[]; counts=Counter()
        for group in groups:
            n=int(hashlib.sha256(('|'.join(sorted(x['sha256'] for x in group))+'|seed:42').encode()).hexdigest()[:12],16)%10000/100
            dest='train' if n<train else 'valid' if n<train+valid else 'test'
            for x in group:
                assignment.append((x,dest)); counts[dest]+=1
        fingerprint=hashlib.sha256(json.dumps([(x['id'],x['revision'],dest) for x,dest in assignment]).encode()).hexdigest()
        if apply:
            if body.get('fingerprint')!=fingerprint: raise ValueError('사진 또는 설정이 바뀌었습니다. 미리 보기를 다시 실행하세요.')
            for x,dest in assignment: x.update(split=dest,revision=x['revision']+1,updated=now())
            self.store.put_many('images',[x for x,_ in assignment]); self.event('자동 분할',str(dict(counts)))
        return dict(counts={k:counts[k] for k in ('train','valid','test')},groups=len(groups),total=len(images),fingerprint=fingerprint,applied=apply)

    def version_selection(self, body):
        """One selection policy for preview and commit; never silently drop pending data."""
        batches={b['id']:b for b in self.store.all('batches')}
        selected=body.get('train_batches') or []
        if not isinstance(selected,list) or any(not isinstance(k,str) or k not in batches or batches[k]['stage']!='done' for k in selected):
            raise ValueError('train에는 완료 배치만 선택할 수 있습니다. 보드를 확인하고 새로고침하세요.')
        images=[];pending=[];excluded=Counter();pending_batches=Counter()
        for x in self.store.all('images'):
            if x['deleted']:excluded['deleted']+=1;continue
            if batches.get(x['batch'],{}).get('stage')!='done':excluded['not_done']+=1;continue
            if body.get('exclude_ambiguous',True) and x['status']=='ambiguous':excluded['ambiguous']+=1;continue
            if body.get('reviewed_only') and x['status']!='reviewed':excluded['not_reviewed']+=1;continue
            if x['status'] in ('auto','ai_reviewed'):excluded['automatic_label']+=1;continue
            if not body.get('include_background',True) and not x['annotations']:excluded['background']+=1;continue
            if selected and x['split'] in ('','train') and x['batch'] not in selected:excluded['unselected_batch']+=1;continue
            if not x['split']:
                pending.append(x);pending_batches[x['batch']]+=1;continue
            images.append(x)
        report=dict(counts={k:sum(x['split']==k for x in images) for k in ('train','valid','test')},
                    pending_count=len(pending),pending_batches=[dict(id=k,name=batches[k]['name'],count=n) for k,n in pending_batches.items()],
                    excluded=dict(excluded))
        return images,batches,selected,report

    def preview_version(self, body):
        return self.version_selection(body)[3]

    def create_version(self, body):
        images,batches,selected,report=self.version_selection(body)
        if report['pending_count']:
            names=', '.join(b['name']+' '+str(b['count'])+'장' for b in report['pending_batches'])
            raise ValueError('완료 배치에 미분할 사진 '+str(report['pending_count'])+'장이 있습니다 ('+names+'). 자동 분할의 미리 보기 → 분할 적용 후 버전을 만드세요. 새 사진을 제외한 버전은 만들지 않았습니다.')
        if not images: raise ValueError('조건에 맞는 분할된 사진이 없습니다')
        versions=self.store.all('versions')
        name=str(body.get('name','')).strip() or f'v{len(versions)+1}'
        if any(v['name']==name for v in versions): raise ValueError('이미 있는 버전 이름입니다')
        rules={**body,'done_only':True,'train_batches':selected,'resolved_train_batches':sorted({x['batch'] for x in images if x['split']=='train'})}
        snapshot=[dict(id=k,name=batches[k]['name'],stage='done',counts=dict(Counter(x['split'] for x in images if x['batch']==k))) for k in sorted({x['batch'] for x in images})]
        version=dict(id=uid(),name=name[:100],note=str(body.get('note',''))[:1000],created=now(),images=images,classes=self.store.all('classes'),rules=rules,batch_snapshot=snapshot,counts=dict(Counter(x['split'] for x in images)),selection_audit=report)
        self.store.put('versions',version); self.event('버전 고정',version['name'])
        return version

    def coco(self, version, split=None):
        classes=version['classes']; class_ids={c['id']:i+1 for i,c in enumerate(classes)}
        result=dict(images=[],annotations=[],categories=[dict(id=i+1,name=c['name'],supercategory='normal' if c.get('normal') else 'defect') for i,c in enumerate(classes)])
        for i,x in enumerate(version['images'],1):
            if split and x['split']!=split: continue
            result['images'].append(dict(id=i,file_name=x['file'],original_name=x['name'],width=x['width'],height=x['height'],split=x['split']))
            groups={}
            for a in x['annotations']:
                groups.setdefault((a['class_id'],a.get('group_id') or a['id']),[]).append(a['points'])
            for (class_id,_),polygons in groups.items():
                xs=[p[0] for pts in polygons for p in pts];ys=[p[1] for pts in polygons for p in pts]
                area=sum(abs(sum(pts[j][0]*pts[(j+1)%len(pts)][1]-pts[(j+1)%len(pts)][0]*pts[j][1] for j in range(len(pts))))/2 for pts in polygons)
                result['annotations'].append(dict(id=len(result['annotations'])+1,image_id=i,category_id=class_ids[class_id],segmentation=[[z for p in pts for z in p] for pts in polygons],bbox=[min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys)],area=area,iscrowd=0))
        return result

    def export_version(self, key, fmt='coco', include_images=False):
        v=self.store.get('versions',key)
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('version.json',json.dumps(v,ensure_ascii=False,indent=2))
            for split in ('train','valid','test'):
                if fmt=='coco': z.writestr(f'{split}.json',json.dumps(self.coco(v,split),ensure_ascii=False))
                else:
                    cls={c['id']:i for i,c in enumerate(v['classes'])}
                    for x in v['images']:
                        if x['split']!=split: continue
                        lines=[str(cls[a['class_id']])+' '+' '.join(str(round(p[j]/x['width' if j==0 else 'height'],6)) for p in a['points'] for j in (0,1)) for a in x['annotations']]
                        z.writestr(f'labels/{split}/{Path(x["file"]).stem}.txt','\n'.join(lines))
            if fmt=='yolo':
                z.writestr('data.yaml','path: .\ntrain: images/train\nval: images/valid\ntest: images/test\nnames:\n'+''.join(f'  {i}: {json.dumps(c["name"])}\n' for i,c in enumerate(v['classes'])))
            if include_images:
                for x in v['images']:
                    path=self.media(x['file'])
                    z.write(path,('images/'+x['split']+'/' if fmt=='yolo' else 'images/')+x['file'])
        return buf.getvalue(),v['name']+'-'+fmt+'.zip'

    def media(self, name):
        p=(self.data/'media'/name).resolve()
        if p.parent!=self.data/'media' or not p.is_file(): raise KeyError('사진 파일 없음')
        return p

    def materialize(self, version, dest):
        dest=Path(dest); (dest/'images').mkdir(parents=True,exist_ok=True)
        for x in version['images']:
            shutil.copy2(self.media(x['file']),dest/'images'/x['file'])
        for split in ('train','valid','test'):
            (dest/f'{split}.json').write_text(json.dumps(self.coco(version,split),ensure_ascii=False),encoding='utf-8')

    def demo(self):
        if self.store.all('images'): return
        for i,stage in enumerate(('new','labeling','review','done')):
            b=self.save_batch(dict(name=['센서 A · 오전 촬영','돌출·함몰 검토','표면 오염 확인','검수 완료 데이터'][i],stage=stage))
            for j in range(4):
                key=uid(); name=f'예제_Sensor{chr(65+i)}_{j+1:03}.svg'
                defect=i>0 and j!=3
                svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="640" viewBox="0 0 1600 640"><defs><linearGradient id="c" x2="0" y2="1"><stop stop-color="#b7b9ba"/><stop offset=".22" stop-color="#eeeeeb"/><stop offset=".54" stop-color="#b0b3b3"/><stop offset="1" stop-color="#666b6e"/></linearGradient><pattern id="p" width="28" height="18" patternUnits="userSpaceOnUse"><path d="M0 0h28" stroke="#ffffff" opacity=".14"/></pattern></defs><rect width="1600" height="640" fill="#d9d8d2"/><path d="M0 215 Q800 170 1600 215 V480 Q800 440 0 480Z" fill="url(#c)"/><path d="M0 215 Q800 170 1600 215 V480 Q800 440 0 480Z" fill="url(#p)"/><text x="160" y="365" fill="#4f5558" font-family="monospace" font-size="42" opacity=".5">DXEL 2026 · SURFACE INSPECTION</text>{'<ellipse cx="1050" cy="320" rx="65" ry="28" fill="#756654" opacity=".7"/>' if defect else ''}<text x="55" y="70" fill="#6b716f" font-family="sans-serif" font-size="24">SYNTHETIC SAMPLE · Sensor {chr(65+i)}</text></svg>'''
                (self.data/'media'/(key+'.svg')).write_text(svg,encoding='utf-8')
                ann=[dict(id=uid(),class_id='4',points=[[980,285],[1090,278],[1120,329],[1055,358],[985,344]],source='human')] if defect else []
                self.store.put('images',dict(id=key,name=name,file=key+'.svg',width=1600,height=640,sha256=hashlib.sha256(svg.encode()).hexdigest(),batch=b['id'],sensor=chr(65+i),split=['train','train','valid','test'][j] if i==3 else '',status=['todo','todo','ambiguous','reviewed'][i],tags=['샘플'],note='실제 촬영 사진이 아닌 기능 확인용 합성 예제입니다.',annotations=ann,deleted=False,revision=1,created=now(),updated=now()))
        self.create_version(dict(name='예제 v1',note='기능 확인용 합성 예제'))
        self.store.put('settings',dict(id='demo',value=True))
