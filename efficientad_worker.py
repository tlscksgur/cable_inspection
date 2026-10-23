"""EfficientAD management worker. All writes are confined to its authorized root."""
import argparse,json,os,re,shutil,signal,subprocess,sys,time
from collections import Counter
from pathlib import Path
ROOT=Path('/srv/cable/cable_efficientad')
HOME=ROOT/'studio_management'
PYTHON='/srv/cable/miniconda3/envs/anomaly/bin/python'
def read(p,default=None):
 try:return json.loads(p.read_text(encoding='utf8'))
 except (OSError,ValueError):return default

def write(p,data):
 p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(p)
def safe(name):
 if not isinstance(name,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,120}',name):raise ValueError('영문·숫자·밑줄·하이픈으로 이름을 입력하세요')
 return name

def inside(path):
 p=Path(path).resolve()
 if not p.is_relative_to(ROOT) or p==ROOT:raise ValueError('EfficientAD 프로젝트 밖의 경로입니다')
 return p

def inventory():
 meta=read(HOME/'catalog.json',{}) or {};models=[];datasets=[]
 roots={}
 for parent in [ROOT/'artifacts',ROOT/'saved_models']:
  if not parent.exists():continue
  for p in sorted(parent.iterdir()):
   if p.is_dir() and not p.is_symlink() and not p.name.startswith('smoke'):roots.setdefault(p.name,[]).append(p)
 for name,paths in roots.items():
  paths=sorted(paths,key=lambda p:p.parent.name!='saved_models');config=next((read(p/'config.json') for p in paths if (p/'config.json').is_file()),{}) or {}
  cp=next((str(inside(f)) for p in paths for f in [p/'training/model.ckpt',p/'model.ckpt'] if f.is_file()),None)
  has_head=any(list(p.glob('*.pt')) or list((p/'training').glob('*head*.pt')) or list((p/'training').glob('*decoder*.pt')) for p in paths)
  method=str(config.get('method',''));kind='dense' if 'dense' in method.lower() or 'spatial' in method.lower() else 'mil' if has_head else 'efficientad'
  # Archived bundles have varying layouts. A head without a full checkpoint is a model too.
  if cp or has_head:
   metrics={}
   for p in [ROOT/'artifacts'/name,*paths]:
    for file in ['evaluation/summary.json','evaluation/report.json','summary.json','evaluation.json','report.json']:
     value=read(p/file)
     if value:metrics[file]=value
   dense_ready=kind=='dense' and config.get('architecture')=='regularized' and bool(config.get('legacy_feature_model')) and (ROOT/'artifacts'/name/'training/decoder.pt').is_file() and (ROOT/'artifacts'/name/'training/selection.json').is_file()
   models.append(dict(dense_trainable=dense_ready,id=name,name=meta.get(name,{}).get('name',name),kind=kind,checkpoint=cp,trainable=kind=='efficientad' and bool(cp),config=config,metrics=metrics,paths=[str(p) for p in paths],active=meta.get('_active')==name))
  p=ROOT/'artifacts'/name
  prep=read(p/'preparation.json',{}) or {}
  if prep.get('status')=='complete' and all((p/f).is_file() for f in ['manifest.json','config.json','sources.json','provenance.json']) and (p/'roi_edge/tiles/train').is_dir() and not (p/'model_removed.json').exists():
   rows=read(p/'sources.json',[]) or [];manifest=read(p/'manifest.json',[]) or []
   if manifest and isinstance(manifest[0],dict) and 'tile' in manifest[0] and all(any(m.get('split')==s for m in manifest) for s in ['train','calibration','test']):
    datasets.append(dict(kind='efficientad',id=name,counts=dict(Counter(r.get('split','unknown') for r in rows)),tiles=dict(Counter(r.get('split','unknown') for r in manifest))))
 for p in sorted((ROOT/'artifacts').iterdir()) if (ROOT/'artifacts').exists() else []:
  if not p.is_dir() or p.is_symlink():continue
  if all((p/f).is_file() for f in ['selection.json','training/projection.pt','config.json']) and (p/'dense_features').is_dir():
   rows=read(p/'selection.json',[]) or []
   if rows and all(any(r.get('role')==role for r in rows) for role in ['train','calibration','validation','test']):
    datasets.append(dict(id=p.name,kind='dense',counts=dict(Counter(r.get('role','unknown') for r in rows)),tiles={}))
 jobs=[]
 for p in sorted((HOME/'jobs').glob('*/status.json'),key=lambda p:p.stat().st_mtime,reverse=True):
  row=read(p,{}) or {};row['id']=p.parent.name;jobs.append(row)
 return dict(ready=True,models=models,datasets=datasets,jobs=jobs[:100],root=str(ROOT))

def handle(req):
 action=req.get('action','state')
 if action=='state':return inventory()
 if action=='rename':
  key=safe(req['id']);catalog=inventory()
  if not any(m['id']==key for m in catalog['models']):raise ValueError('모델이 없습니다')
  name=str(req.get('name','')).strip()
  if not name or len(name)>160:raise ValueError('모델 이름은 1~160자입니다')
  meta=read(HOME/'catalog.json',{}) or {};meta.setdefault(key,{})['name']=name;write(HOME/'catalog.json',meta);return {'saved':True}
 if action=='activate':
  key=safe(req['id'])
  if not any(m['id']==key for m in inventory()['models']):raise ValueError('모델이 없습니다')
  meta=read(HOME/'catalog.json',{}) or {};meta['_active']=key;write(HOME/'catalog.json',meta);return {'saved':True}
 if action=='log':
  folder=HOME/'jobs'/safe(req['id']);p=folder/'worker.log'
  if not folder.is_dir():raise ValueError('작업이 없습니다')
  if not p.exists():return {'text':'로그 준비 중'}
  with p.open('rb') as f:f.seek(max(0,p.stat().st_size-24000));return {'text':f.read().decode('utf8','replace')}
 if action=='cancel':
  key=safe(req['id']);folder=HOME/'jobs'/key;status=read(folder/'status.json',{}) or {};proc=read(folder/'process.json',{}) or {}
  if status.get('status') not in ['running','queued']:raise ValueError('진행 중인 작업이 아닙니다')
  pid=int(proc.get('pid',0))
  if pid<=1:raise ValueError('작업 프로세스를 확인할 수 없습니다')
  cmdline=Path('/proc')/str(pid)/'cmdline'
  args=cmdline.read_bytes().split(b'\0') if cmdline.exists() else []
  if str(HOME/'worker.py').encode() not in args or b'--run' not in args or key.encode() not in args:raise ValueError('이 GUI에서 시작한 작업 프로세스만 중단할 수 있습니다')
  os.kill(pid,signal.SIGTERM);return {'cancelled':True}
 if action in ['train','preflight']:
  catalog=inventory()
  if any(j.get('status') in ['running','queued'] for j in catalog['jobs']):raise ValueError('진행 중인 EfficientAD 학습이 끝난 후 실행하세요')
  name='gui_'+safe(req['name']);dataset=safe(req['dataset']);steps=int(req.get('steps',10000));kind=req.get('kind','efficientad')
  if kind not in ['efficientad','dense']:raise ValueError('학습 방식을 선택하세요')
  if not (1<=steps<=200 if kind=='dense' else 100<=steps<=200000):raise ValueError('학습 step은 100~200000입니다')
  if not any(d['id']==dataset and d['kind']==kind for d in catalog['datasets']):raise ValueError('완료된 고정 분할 데이터셋을 선택하세요')
  base=req.get('base') or None
  if kind=='dense' and not base:raise ValueError('추가 학습할 WaterDense 모델을 선택하세요')
  if base and not any(m['id']==base and (m['dense_trainable'] if kind=='dense' else m['trainable']) for m in catalog['models']):raise ValueError('일반 EfficientAD 체크포인트를 선택하세요')
  if kind=='dense':
   import hashlib
   projection=lambda key:hashlib.sha256((inside(ROOT/'artifacts'/key/'training/projection.pt')).read_bytes()).hexdigest()
   if projection(dataset)!=projection(base):raise ValueError('시작 모델과 데이터셋의 특징 변환이 다릅니다. 같은 계열 데이터셋을 선택하세요')
  for p in [ROOT/'artifacts'/name,ROOT/'saved_models'/name,HOME/'jobs'/name]:
   if p.exists():raise ValueError('이미 사용한 학습 이름입니다. 새 이름을 입력하세요')
  if action=='preflight':return dict(ready=True,kind=kind,dataset=dataset,base=base,budget=steps,name=name)
  folder=HOME/'jobs'/name;folder.mkdir(parents=True)
  spec=dict(kind=kind,name=name,dataset=dataset,steps=steps,base=base,created=time.time());write(folder/'spec.json',spec);write(folder/'status.json',dict(status='queued',name=name,stage='학습 준비',unit='epoch' if kind=='dense' else 'step',step=0,total=steps,created=spec['created']))
  env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',XDG_CACHE_HOME=str(ROOT/'.cache'),TORCH_HOME=str(ROOT/'.cache/torch'),TMPDIR=str(ROOT/'tmp'))
  (ROOT/'tmp').mkdir(exist_ok=True)
  with (folder/'worker.log').open('wb') as log:
   proc=subprocess.Popen([PYTHON,str(Path(__file__).resolve()),'--run',name],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=env)
  write(folder/'process.json',dict(pid=proc.pid));return {'id':name}
 raise ValueError('지원하지 않는 작업')

def run(name):
 folder=HOME/'jobs'/safe(name);spec=read(folder/'spec.json');out=ROOT/'artifacts'/name;status=read(folder/'status.json')
 def update(**kw):status.update(kw);status['updated']=time.time();write(folder/'status.json',status)
 def cancelled(*args):
  update(status='cancelled',stage='사용자가 학습을 중단했습니다');raise SystemExit(0)
 signal.signal(signal.SIGTERM,cancelled)
 try:
  update(status='running',stage='고정 데이터 분할 복사')
  if spec.get('kind')=='dense':
   from efficientad_dense_worker import train_dense
   train_dense(ROOT,spec,update);return
  template=inside(ROOT/'artifacts'/safe(spec['dataset']));out.mkdir()
  for file in ['config.json','sources.json','manifest.json','preparation.json','provenance.json','fixed_split.json','test_labels.json','roi_by_original.json']:
   if (template/file).is_file():shutil.copyfile(template/file,out/file)
  (out/'roi_edge').mkdir();(out/'roi_edge/tiles').symlink_to(inside(template/'roi_edge/tiles'),target_is_directory=True)
  sys.path.insert(0,str(ROOT))
  from efficientad_compare import training
  original_imports=training.imports
  def imports(config,device):
   imported=list(original_imports(config,device));torch,_,_,_,Engine,EfficientAd,Callback=imported
   class Progress(Callback):
    def on_train_batch_end(self,trainer,*args,**kwargs):
     step=trainer.global_step
     if step%25==0 or step>=spec['steps']:update(stage='학습 중',step=step,total=spec['steps'])
   class ManagedEngine(Engine):
    def __init__(self,*args,**kwargs):kwargs['callbacks']=[*kwargs.get('callbacks',[]),Progress()];super().__init__(*args,**kwargs)
   imported[4]=ManagedEngine;return imported
  training.imports=imports
  if spec.get('base'):
   model=next(m for m in inventory()['models'] if m['id']==spec['base'] and m['trainable']);checkpoint=inside(model['checkpoint']);make=training.make_model
   def load(cls,root):
    import torch
    result=make(cls,root);state=torch.load(checkpoint,map_location='cpu',weights_only=False);result.load_state_dict(state['state_dict']);return result
   training.make_model=load
  update(stage='학습 시작')
  training.train(ROOT,out,Path('/srv/cable/cable_anomaly'),spec['steps'],0)
  update(stage='정상 calibration 기준 계산 및 고정 테스트',step=spec['steps'])
  training.evaluate_run(ROOT,out,Path('/srv/cable/cable_anomaly'),0)
  dest=ROOT/'saved_models'/name;dest.mkdir();shutil.copyfile(out/'training/model.ckpt',dest/'model.ckpt');shutil.copyfile(out/'config.json',dest/'config.json');shutil.copytree(out/'evaluation',dest/'evaluation')
  write(dest/'studio_training.json',spec);update(status='completed',stage='학습·평가 완료',model=name,summary=read(out/'evaluation/summary.json'))
 except Exception as e:
  import traceback
  traceback.print_exc();update(status='failed',stage='학습 실패',error=str(e))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run');args=p.parse_args()
 if args.run:run(args.run)
 else:
  try:print(json.dumps(handle(json.load(sys.stdin)),ensure_ascii=False))
  except Exception as e:print(json.dumps({'error':str(e)},ensure_ascii=False));sys.exit(1)
