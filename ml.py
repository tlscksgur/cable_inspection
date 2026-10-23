"""Runs only this application's jobs. GPU jobs are never simulated."""
import json
import os
import subprocess
import threading
from pathlib import Path
from services import integer, now, uid


def finetune_class_transfer(version,model,size):
    """Allow added classes without discarding any learned class meanings."""
    if model['size']!=size:
        raise ValueError('추가 학습할 모델 크기가 다릅니다. '+model['size'].upper()+' 크기를 선택하세요')
    old=model['classes'];new=version['classes']
    old_ids=[c['id'] for c in old];new_ids=[c['id'] for c in new]
    if old_ids!=model['class_ids'] or len(set(old_ids))!=len(old_ids) or len(set(new_ids))!=len(new_ids):
        raise ValueError('모델 또는 버전의 클래스 정보가 일치하지 않습니다')
    target={c['id']:c for c in new}
    if any(c['id'] not in target for c in old):
        raise ValueError('기존 모델의 클래스를 삭제한 버전으로는 추가 학습할 수 없습니다')
    for c in old:
        other=target[c['id']]
        if (c['name'],bool(c.get('normal')))!=(other['name'],bool(other.get('normal'))):
            raise ValueError('기존 클래스의 이름 또는 정상/결함 구분이 바뀌었습니다: '+c['name'])
    if len({c['name'] for c in new})!=len(new):raise ValueError('중복된 클래스 이름이 있습니다')
    added=[c for c in new if c['id'] not in old_ids]
    labelled={a['class_id'] for x in version['images'] if x['split']=='train' for a in x['annotations']}
    missing=[c['name'] for c in added if c['id'] not in labelled]
    if missing:raise ValueError('추가 클래스의 train 라벨이 필요합니다: '+', '.join(missing))
    if old_ids==new_ids:return None
    return dict(source_classes=old,target_classes=new,added_classes=[c['name'] for c in added],
                source_model_id=model['id'],source_model_name=model['name'])


def align_evaluation_classes(version, model):
    """Keep checkpoint output indices intact; only omit unlabelled normal extras."""
    import copy
    model_classes=model['classes']
    ids=[c['id'] for c in model_classes]
    if ids!=model['class_ids'] or len(set(ids))!=len(ids):
        raise ValueError('모델에 저장된 클래스 정보가 일치하지 않습니다')
    version_ids=[c['id'] for c in version['classes']]
    if len(set(version_ids))!=len(version_ids):
        raise ValueError('평가 버전에 중복된 클래스 ID가 있습니다')
    source={c['id']:c for c in version['classes']}
    target={c['id']:c for c in model_classes}
    labelled={a['class_id'] for x in version['images'] if x['split']=='valid'
              for a in x['annotations']}
    if labelled-set(source):
        raise ValueError('평가 정답에 버전의 클래스 목록에 없는 라벨이 있습니다')
    for key in source.keys() & target.keys():
        if (source[key]['name'],bool(source[key].get('normal'))) != (target[key]['name'],bool(target[key].get('normal'))):
            raise ValueError('같은 클래스 ID의 이름 또는 정상/결함 구분이 달라 평가할 수 없습니다: '+source[key]['name'])
    omitted=[c for c in version['classes'] if c['id'] not in target]
    added=[c for c in model_classes if c['id'] not in source]
    blocked=[c['name'] for c in omitted if not c.get('normal') or c['id'] in labelled]
    blocked.extend(c['name'] for c in added if not c.get('normal'))
    if blocked:
        raise ValueError('모델과 평가 버전의 클래스가 다릅니다: '+', '.join(blocked)+
                         '. valid 정답이 없는 추가 정상 클래스만 자동으로 맞출 수 있습니다')
    aligned=copy.deepcopy(version)
    aligned['images']=[x for x in aligned['images'] if x['split']=='valid']
    aligned['classes']=copy.deepcopy(model_classes)
    scope=dict(model_classes=[c['name'] for c in model_classes],
               labelled_classes=[c['name'] for c in model_classes if c['id'] in labelled],
               omitted_unlabelled_normal_classes=[c['name'] for c in omitted],
               model_only_unlabelled_normal_classes=[c['name'] for c in added],
               reordered=ids!=version_ids,
               note='모델의 출력 클래스 순서로 평가합니다. valid 정답이 없는 클래스는 COCO mAP 평균에서 제외됩니다.')
    return aligned,scope


class ML:
    def __init__(self, studio):
        self.studio=studio
        self.python=os.environ.get('STUDIO_ML_PYTHON','')
        self.root=os.environ.get('STUDIO_MMDET_ROOT','')
        self.worker=Path(__file__).with_name('worker.py')
        self.processes={}
        self.remote=None
        self.lock=threading.RLock()
        self.info=dict(ready=False,reason='gpu.example.internal GPU 서버 로그인이 필요합니다.')
        if self.python and self.root:
            try:
                result=subprocess.run([self.python,str(self.worker),'--probe'],capture_output=True,text=True,timeout=40,encoding='utf-8')
                self.info=json.loads(result.stdout.splitlines()[-1])
                if not Path(self.root,'configs','rtmdet','rtmdet-ins_l_8xb32-300e_coco.py').is_file():
                    self.info=dict(ready=False,reason='MMDetection RTMDet-Ins 설정 파일을 찾을 수 없습니다.')
            except Exception:
                self.info=dict(ready=False,reason='실행 환경을 확인할 수 없습니다. 서버 설정과 Python 경로를 확인하세요.')
        self.start_auto_connection()
        for job in studio.store.all('jobs'):
            if job['status'] in ('running','queued'):
                job.update(status='interrupted',message='서버가 재시작되어 중단되었습니다. 다시 시작하세요.')
                studio.store.put('jobs',job)

    def start_auto_connection(self):
        from ssh_auth import auto_available
        if not auto_available():return
        if getattr(self,'_auto_thread',None) and self._auto_thread.is_alive():return
        self._auto_thread=threading.Thread(target=self._auto_loop,name='studio-ssh-reconnect',daemon=True)
        self._auto_thread.start()

    def _auto_loop(self):
        import time
        from remote_ml import RemoteBackend
        while True:
            try:
                with self.lock:
                    transport=self.remote.client.get_transport() if self.remote else None
                    if not transport or not transport.is_active():
                        self.info=dict(ready=False,reason='AI 서버에 자동 연결 중입니다.')
                        candidate=RemoteBackend()
                        old=self.remote;self.remote=candidate;self.root=candidate.root;self.info=candidate.info
                        if old:old.close()
            except Exception:
                self.info=dict(ready=False,reason='AI 서버 자동 연결을 재시도하고 있습니다. 서버와 네트워크를 확인하세요.')
            time.sleep(15)

    def connect_remote(self,body):
        from remote_ml import RemoteBackend
        if not isinstance(body.get('password'),str) or not 1<=len(body['password'])<=4096:
            raise ValueError('서버 비밀번호를 입력하세요')
        with self.lock:
            self.refresh()
            if any(j['status']=='running' for j in self.studio.store.all('jobs')):
                raise ValueError('실행 중인 작업이 끝난 후 다시 연결하세요')
            remote=RemoteBackend(body['password'])
            if self.remote:self.remote.close()
            self.remote=remote;self.root=remote.root;self.info=remote.info
            return self.info

    def launch(self, body):
        if body.get('model_type','RTMDet-Ins')!='RTMDet-Ins':
            raise ValueError('RTMDet-Ins만 지원합니다')
        if body.get('resume_model'):
            self.studio.model_for_use(body['resume_model'])
        if body.get('model_id'):
            self.studio.model_for_use(body['model_id'])
        if not self.info['ready']:
            raise RuntimeError(self.info['reason'])
        mode=body.get('mode','train')
        if mode not in ('train','eval','predict'): raise ValueError('지원하지 않는 작업')
        with self.lock:
            self.refresh()
            spec=dict(mode=mode,mmdet_root=self.root)
            if mode=='train':
                start_mode=body.get('start_mode') or ('finetune' if body.get('resume_model') else 'scratch')
                if start_mode not in ('scratch','finetune'):raise ValueError('학습 방식을 선택하세요')
                if start_mode=='finetune' and not body.get('resume_model'):raise ValueError('추가 학습할 기존 모델을 선택하세요')
                if start_mode=='scratch' and body.get('resume_model'):raise ValueError('처음부터 학습할 때는 기존 모델을 선택하지 않습니다')
                version=self.studio.store.get('versions',body['version_id'])
                if not version['counts'].get('train') or not version['counts'].get('valid'): raise ValueError('train과 valid 사진이 모두 필요합니다')
                if any(Path(x['file']).suffix.lower()=='.svg' for x in version['images']): raise ValueError('합성 예제는 학습할 수 없습니다. 실제 사진을 추가하세요.')
                size=body.get('size','l').lower()
                if size not in ('s','m','l','x'): raise ValueError('모델 크기를 확인하세요')
                spec.update(version=version,classes=version['classes'],size=size,epochs=integer(body.get('epochs',40),1,1000),patience=integer(body.get('patience',10),1,200),batch_size=integer(body.get('batch_size',2),1,64),height=integer(body.get('height',640),128,4096),width=integer(body.get('width',1536),128,4096),lr=float(body.get('lr',0.0002)))
                if not 0<spec['lr']<=1: raise ValueError('학습률 범위를 확인하세요')
                if body.get('resume_model'):
                    model=self.studio.store.get('models',body['resume_model'])
                    transfer=finetune_class_transfer(version,model,size)
                    if transfer:spec['finetune_class_transfer']=transfer
                    spec['checkpoint']=model['checkpoint']
                    spec['source_model_id']=model['id'];spec['source_model_name']=model['name']
                    spec['start_mode']='finetune'
                else:
                    spec['checkpoint']=None
                    spec['start_mode']='scratch'
                name=body.get('name') or f'rtmins_{version["name"]}_{size}_{uid()[:5]}'
            else:
                model=self.studio.store.get('models',body['model_id'])
                spec.update(model=model,classes=model['classes'],checkpoint=model['checkpoint'],config=model['config'])
                name=('평가 · ' if mode=='eval' else '예측 · ')+model['name']
                if mode=='eval':
                    version=self.studio.store.get('versions',body['version_id'])
                    if not version['counts'].get('valid'):raise ValueError('valid 사진이 있는 버전을 선택하세요')
                    spec['version'],spec['evaluation_scope']=align_evaluation_classes(version,model)
                else:
                    ids=body.get('image_ids',[])
                    if not ids: raise ValueError('예측할 사진을 선택하세요')
                    images=[self.studio.store.get('images',i) for i in ids]
                    spec['images']=[dict(id=x['id'],path=str(self.studio.media(x['file'])),revision=x['revision']) for x in images if not x['deleted']]
                    if not spec['images']: raise ValueError('예측할 사진이 없습니다')
                    spec['threshold']=float(body.get('threshold',.4))
                    if not 0<=spec['threshold']<=1: raise ValueError('점수는 0~1이어야 합니다')
            key=uid(); folder=self.studio.data/'jobs'/key; folder.mkdir(parents=True)
            if 'version' in spec:
                dataset_version=spec['version']
                if mode=='eval':dataset_version={**dataset_version,'images':[x for x in dataset_version['images'] if x['split']=='valid']}
                self.studio.materialize(dataset_version,folder/'dataset')
                spec['dataset']=str(folder/'dataset')
                spec['version_id']=spec['version']['id']
                del spec['version']
            spec['work_dir']=str(folder/'work')
            spec['status_path']=str(folder/'status.json')
            spec['result_path']=str(folder/'result.json')
            (folder/'spec.json').write_text(json.dumps(spec,ensure_ascii=False),encoding='utf-8')
            job=dict(id=key,name=str(name)[:160],mode=mode,status='running',created=now(),progress=0,step=0,total_steps=None,epoch=0,message='실행 환경 준비 중',version_id=spec.get('version_id'),spec=spec)
            self.studio.store.put('jobs',job)
            log=(folder/'worker.log').open('wb')
            try:
                if self.remote:
                    proc=self.remote.start(spec,self.worker,folder)
                else:
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
                    proc=subprocess.Popen([self.python,str(self.worker),'--spec',str(folder/'spec.json')],stdout=log,stderr=subprocess.STDOUT,creationflags=creationflags,env={**os.environ,'PYTHONUNBUFFERED':'1','PYTHONIOENCODING':'utf-8'})
                self.processes[key]=proc
            except Exception:
                job.update(status='failed',message='학습 프로세스를 시작할 수 없습니다.'); self.studio.store.put('jobs',job); raise
            finally: log.close()
            self.studio.event('작업 시작',job['name'])
            return job

    def resume_training(self,key):
        import copy
        with self.lock:
            self.refresh()
            old=self.studio.store.get('jobs',key)
            if old['mode']!='train' or old['status'] not in ('cancelled','failed','interrupted'):
                raise ValueError('중단된 학습 작업만 체크포인트에서 재개할 수 있습니다')
            if not self.remote or not self.info['ready']:raise ValueError('GPU 서버에 먼저 연결하세요')
            if any(j['status']=='running' and j.get('spec',{}).get('origin_job')==key for j in self.studio.store.all('jobs')):
                raise ValueError('이 작업은 이미 재개 중입니다')
            checkpoint,epoch=self.remote.training_checkpoint(key)
            spec=copy.deepcopy(old['spec'])
            if epoch>=spec['epochs']:raise ValueError('이미 마지막 epoch까지 학습된 작업입니다')
            spec.update(checkpoint=checkpoint,resume=True,resume_epoch=epoch,origin_job=key)
            new_key=uid();folder=self.studio.data/'jobs'/new_key;folder.mkdir(parents=True)
            spec.update(work_dir=str(folder/'work'),status_path=str(folder/'status.json'),result_path=str(folder/'result.json'))
            (folder/'spec.json').write_text(json.dumps(spec,ensure_ascii=False),encoding='utf-8')
            job=dict(id=new_key,name=old['name']+' · 빠른 재개',mode='train',status='running',created=now(),
                     progress=round(epoch/spec['epochs']*100,1),step=0,total_steps=None,epoch=epoch,
                     message=f'epoch {epoch} 체크포인트에서 빠른 설정으로 재개 준비 중',version_id=old['version_id'],spec=spec)
            self.studio.store.put('jobs',job)
            try:self.processes[new_key]=self.remote.start(spec,self.worker,folder)
            except Exception:
                job.update(status='failed',message='재개 프로세스를 시작할 수 없습니다');self.studio.store.put('jobs',job);raise
            self.studio.event('학습 재개',job['name'])
            return job

    def refresh(self):
        with self.lock:
            for key,proc in list(self.processes.items()):
                job=self.studio.store.get('jobs',key); folder=self.studio.data/'jobs'/key
                try:
                    if hasattr(proc,'progress_snapshot'):
                        status=proc.progress_snapshot()
                    else:status=json.loads((folder/'status.json').read_text(encoding='utf-8'))
                    job.update({k:status[k] for k in ('step','total_steps','epoch','progress','message') if k in status})
                except (OSError,ValueError): pass
                code=proc.poll()
                if code is not None:
                    try: result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
                    except (OSError,ValueError): result={}
                    job.update(status='completed' if code==0 and result else 'failed',finished=now())
                    if job['status']=='completed':
                        job.update(progress=100,message='완료',result=result)
                        if job['mode']=='train':
                            spec=job['spec']
                            model=dict(id=uid(),name=job['name'],type='RTMDet-Ins',size=spec['size'],classes=spec['classes'],class_ids=[c['id'] for c in spec['classes']],checkpoint=result['checkpoint'],config=result['config'],version_id=spec['version_id'],metrics=result.get('metrics',{}),evaluations={},created=now(),active=False)
                            self.studio.store.put('models',model)
                        elif job['mode']=='eval':
                            model=self.studio.store.get('models',job['spec']['model']['id']); model.setdefault('evaluations',{})[job['version_id']]=result
                            self.studio.store.put('models',model)
                    else: job['message']='실행 실패. 작업 로그를 확인하세요.'
                    del self.processes[key]
                self.studio.store.put('jobs',job)

    def gpu_info(self):
        if self.remote:return self.remote.gpu_info()
        return dict(available=False,reason='GPU 서버 로그인 필요')

    def cancel(self,key):
        with self.lock:
            proc=self.processes.get(key)
            if not proc: raise ValueError('이 앱이 현재 실행 중인 작업만 중단할 수 있습니다')
            proc.terminate()
            try: proc.wait(timeout=8)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=8)
            del self.processes[key]
            job=self.studio.store.get('jobs',key); job.update(status='cancelled',message='사용자가 중단했습니다',finished=now())
            self.studio.store.put('jobs',job)
            return job

