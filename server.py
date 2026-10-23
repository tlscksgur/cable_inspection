"""Local dxel Studio rebuild. Python standard library only."""
import argparse
import gzip
import io
import json
import mimetypes
import os
import threading
import traceback
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from services import Studio, now, uid
from store import Store
from ml import ML
from efficientad import EfficientAD

ROOT=Path(__file__).resolve().parent


def create_server(data, port=8898, demo=False):
    data=Path(data).resolve()
    store=Store(data/('demo.sqlite' if demo else 'studio.sqlite'))
    studio=Studio(store,data)
    if demo: studio.demo()
    ml=ML(studio)
    efficientad=EfficientAD(ml)
    mutation_lock=threading.RLock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,fmt,*args):
            # Do not log request query strings or user data.
            pass

        def send(self,content,status=200,ctype='application/json; charset=utf-8',filename=None):
            if not isinstance(content,bytes): content=json.dumps(content,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
            compressed=len(content)>1024 and 'gzip' in self.headers.get('Accept-Encoding','') and any(x in ctype for x in ('json','javascript','html','css'))
            if compressed:content=gzip.compress(content,compresslevel=3)
            self.send_response(status)
            self.send_header('Content-Type',ctype)
            self.send_header('Content-Length',str(len(content)))
            if compressed:self.send_header('Content-Encoding','gzip');self.send_header('Vary','Accept-Encoding')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors "+("'self'" if self.path.startswith('/efficientad-test/') else "'none'"))
            if filename:
                from urllib.parse import quote
                self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(filename))
            self.end_headers(); self.wfile.write(content)

        def do_GET(self): self.handle_request()
        def do_POST(self): self.handle_request()

        def handle_request(self):
            host=self.headers.get('Host','')
            if urlsplit('//'+host).hostname not in ('127.0.0.1','localhost','::1'):
                self.send(dict(error='로컬 호스트에서만 접근할 수 있습니다'),403); return
            origin=self.headers.get('Origin')
            if origin and origin!='http://'+host:
                self.send(dict(error='다른 사이트에서 보낸 요청은 허용하지 않습니다'),403); return
            try:
                with mutation_lock:
                    parts=urlsplit(self.path); path=unquote(parts.path); q=parse_qs(parts.query)
                    if self.command=='GET': self.get(path,q)
                    else:
                        length=int(self.headers.get('Content-Length',0))
                        if not 0<length<=85*1024*1024: raise ValueError('요청 크기가 올바르지 않습니다')
                        raw=self.rfile.read(length)
                        if path=='/api/upload':
                            meta=json.loads(self.headers.get('X-Upload-Meta','{}'))
                            self.send(studio.upload(raw,meta.get('name',''),meta)); return
                        if self.headers.get('Content-Type','').split(';')[0]!='application/json': raise ValueError('JSON 요청이 필요합니다')
                        self.post(path,json.loads(raw))
            except KeyError as e: self.send(dict(error=str(e)),404)
            except (ValueError,TypeError,IndexError) as e: self.send(dict(error=str(e)),400)
            except RuntimeError as e: self.send(dict(error=str(e)),503)
            except (BrokenPipeError,ConnectionResetError): pass
            except Exception as e:
                print('Request failed:',type(e).__name__)
                self.send(dict(error='처리에 실패했습니다. 서버 설정을 확인하세요.'),500)

        def get(self,path,q):
            if path.startswith('/efficientad-test/'):
                status,mime,raw=efficientad.inspection(path);self.send(raw,status,ctype=mime)
            elif path=='/api/efficientad':
                self.send(efficientad.request(dict(action='state')))
            elif path=='/api/state':
                ml.start_auto_connection();ml.refresh(); state=studio.state(compact=q.get('compact')==['1'])
                state['versions']=[{k:v for k,v in x.items() if k not in ('images','classes')} for x in state['versions']]
                state['jobs']=[{k:v for k,v in x.items() if k!='spec'} for x in state['jobs']]
                state['connection']=dict(database='샘플 DB' if demo else '로컬 SQLite',demo=demo,ml=ml.info,mode='local',schema_version=1)
                self.send(state)
            elif path=='/api/activity':
                ml.refresh()
                self.send(dict(jobs=[{k:v for k,v in x.items() if k!='spec'} for x in store.all('jobs')],
                    models=store.all('models'),versions=store.summaries('versions',('images','classes'))))
            elif path=='/api/image-previews':
                ids=q.get('ids',[''])[0].split(',')
                if not 1<=len(ids)<=100:raise ValueError('한 번에 최대 100장입니다')
                self.send([dict(id=x['id'],revision=x['revision'],annotations=[dict(class_id=a['class_id'],points=a['points']) for a in x.get('annotations',[])]) for x in (store.get('images',key) for key in ids)])
            elif path.startswith('/api/images/'):
                self.send(store.get('images',path.split('/')[3]))
            elif path=='/api/gpu': self.send(ml.gpu_info())
            elif path=='/api/backup': self.send(store.backup(),filename='studio-backup.json')
            elif path.startswith('/api/versions/'):
                key=path.split('/')[3]
                if path.endswith('/export'):
                    fmt=q.get('format',['coco'])[0]
                    if fmt not in ('coco','yolo'): raise ValueError('지원하지 않는 내보내기 형식')
                    blob,name=studio.export_version(key,fmt,q.get('images',['0'])[0]=='1'); self.send(blob,ctype='application/zip',filename=name)
                elif path.endswith('/compare'):
                    a=store.get('versions',key); b=store.get('versions',q['with'][0]); aa={x['id']:x for x in a['images']}; bb={x['id']:x for x in b['images']}
                    self.send(dict(added=[x['name'] for k,x in aa.items() if k not in bb],removed=[x['name'] for k,x in bb.items() if k not in aa],changed=[x['name'] for k,x in aa.items() if k in bb and (x['annotations']!=bb[k]['annotations'] or x['split']!=bb[k]['split'])]))
                else: self.send(store.get('versions',key))
            elif path.startswith('/api/jobs/') and path.endswith('/log'):
                key=path.split('/')[3]; store.get('jobs',key)
                p=data/'jobs'/key/'worker.log'
                if p.exists():
                    with p.open('rb') as f:
                        f.seek(max(0,p.stat().st_size-50000)); text=f.read().decode('utf-8',errors='replace')
                else: text='아직 로그가 없습니다'
                self.send(dict(text=text))
            elif path.startswith('/api/models/') and path.endswith('/download'):
                model=studio.model_for_use(path.split('/')[3]); checkpoint=Path(model['checkpoint'])
                if not checkpoint.is_file(): raise KeyError('체크포인트 파일 없음')
                if q.get('bundle',['0'])[0]=='1':
                    buf=io.BytesIO()
                    with zipfile.ZipFile(buf,'w',zipfile.ZIP_STORED) as z:
                        z.write(checkpoint,'model.pth'); z.write(model['config'],'training_config.py')
                        bundle_root=checkpoint.parent.resolve()
                        for artifact in model.get('artifacts',[]):
                            artifact=Path(artifact).resolve()
                            if artifact.parent==bundle_root and artifact.is_file() and artifact not in (checkpoint.resolve(),Path(model['config']).resolve()):
                                z.write(artifact,'original/'+artifact.name)
                        z.writestr('model.json',json.dumps(model,ensure_ascii=False,indent=2))
                        z.writestr('README.txt','RTMDet-Ins / MMDetection\nUse training_config.py and model.pth with mmdet.apis.init_detector.\nClass order is preserved in model.json.\n')
                    self.send(buf.getvalue(),ctype='application/zip',filename=model['name']+'.zip')
                else: self.send(checkpoint.read_bytes(),ctype='application/octet-stream',filename=model['name']+'.pth')
            elif path.startswith('/media/'):
                p=studio.media(path.removeprefix('/media/')); self.send(p.read_bytes(),ctype=mimetypes.guess_type(p)[0] or 'application/octet-stream')
            elif path.startswith('/api/'): raise KeyError('API를 찾을 수 없습니다')
            else:
                p=(ROOT/'web'/(path.lstrip('/') or 'index.html')).resolve()
                if not p.is_relative_to(ROOT/'web') or not p.is_file(): raise KeyError('파일 없음')
                self.send(p.read_bytes(),ctype=mimetypes.guess_type(p)[0] or 'application/octet-stream')

        def post(self,path,body):
            if path=='/efficientad-test/api/inspect':
                status,mime,raw=efficientad.inspection(path,body,self.headers.get('X-GUI-Token',''));self.send(raw,status,ctype=mime);return
            elif path=='/api/efficientad': result=efficientad.request(body)
            elif path=='/api/ml/connect': result=ml.connect_remote(body)
            elif path=='/api/images/bulk': result=studio.bulk(body)
            elif path.startswith('/api/images/'): result=studio.update_image(path.split('/')[3],body)
            elif path=='/api/batches': result=studio.save_batch(body)
            elif path=='/api/batches/merge': result=studio.merge_batches(body)
            elif path=='/api/classes': result=studio.save_class(body)
            elif path=='/api/split/preview': result=studio.split(body)
            elif path=='/api/split/apply': result=studio.split(body,apply=True)
            elif path=='/api/versions/preview': result=studio.preview_version(body)
            elif path=='/api/versions': result=studio.create_version(body)
            elif path=='/api/jobs': result=ml.launch(body)
            elif path.startswith('/api/jobs/') and path.endswith('/resume-fast'): result=ml.resume_training(path.split('/')[3])
            elif path.startswith('/api/jobs/') and path.endswith('/cancel'): result=ml.cancel(path.split('/')[3])
            elif path=='/api/predictions/accept':
                job=store.get('jobs',body['job_id'])
                if job['status']!='completed' or job['mode']!='predict': raise ValueError('완료된 예측 작업을 선택하세요')
                predictions=job['result']['predictions']
                updates=[]
                for pred in predictions:
                    x=store.get('images',pred['image_id'])
                    if x['revision']!=pred['revision'] or x['deleted']: raise ValueError('예측 후 사진이 수정되었습니다. 예측을 다시 실행하세요.')
                    if x['annotations'] and not body.get('append'): raise ValueError('기존 라벨이 있습니다. 기존 라벨에 추가 옵션을 선택하세요.')
                    anns=x['annotations']+pred['annotations'] if body.get('append') else pred['annotations']
                    x.update(annotations=studio.validate_annotations(anns,x),status='auto',revision=x['revision']+1,updated=now()); updates.append(x)
                store.put_many('images',updates); studio.event('자동 라벨 적용',f'{len(updates)}장 · 사람 검수 필요'); result=dict(count=len(updates))
            elif path=='/api/models/register':
                cp=Path(body.get('checkpoint','')).resolve(); cfg=Path(body.get('config','')).resolve()
                if not cp.is_file() or cp.suffix!='.pth' or not cfg.is_file() or cfg.suffix!='.py': raise ValueError('서버의 .pth 체크포인트와 .py 설정 파일 경로가 필요합니다')
                size=body.get('size','l')
                if size not in ('s','m','l','x'): raise ValueError('모델 크기 오류')
                classes=store.all('classes')
                result=dict(id=uid(),name=str(body.get('name') or cp.stem)[:160],type='RTMDet-Ins',size=size,checkpoint=str(cp),config=str(cfg),classes=classes,class_ids=[c['id'] for c in classes],metrics={},evaluations={},active=False,created=now())
                store.put('models',result); studio.event('모델 등록',result['name'])
            elif path.startswith('/api/models/'):
                result=studio.update_model(path.split('/')[3],body)
            elif path=='/api/settings':
                if set(body)-{'project_name','shortcuts','grid_size'}: raise ValueError('지원하지 않는 설정')
                for k,v in body.items(): store.put('settings',dict(id=k,value=v))
                result=dict(saved=True)
            else: raise KeyError('API를 찾을 수 없습니다')
            self.send(result)

    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.studio=studio; server.ml=ml
    return server


if __name__=='__main__':
    active=ROOT/'.runtime'/'active-data.json'
    active_data=str(ROOT/json.loads(active.read_text(encoding='utf-8-sig'))['data_dir']) if active.exists() else str(ROOT/'data')
    p=argparse.ArgumentParser(description='dxel Studio local rebuild')
    p.add_argument('--port',type=int,default=8898); p.add_argument('--data-dir',default=os.environ.get('STUDIO_DATA_DIR',active_data)); p.add_argument('--demo',action='store_true')
    args=p.parse_args(); server=create_server(args.data_dir,args.port,args.demo)
    print(f'dxel Studio: http://127.0.0.1:{server.server_port}/',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
