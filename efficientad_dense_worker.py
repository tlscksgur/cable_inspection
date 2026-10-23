"""Warm-start existing WaterDense decoder on cached, fixed original-level splits."""
import json,shutil,sys,time
from pathlib import Path

def train_dense(root,spec,update):
 sys.path.insert(0,str(root))
 import torch
 from efficientad_compare import dense_regions as dense,dense_regions_regularized as regular,ilin172_finetune as warm,water_mil as mil
 from efficientad_compare.common import read_json,write_json,file_hash
 name=spec['name'];base=root/'artifacts'/spec['base'];source=root/'artifacts'/spec['dataset'];out=root/'artifacts'/name
 torch.manual_seed(42);torch.set_num_threads(8);torch.cuda.set_per_process_memory_fraction(.2)
 rows=read_json(source/'selection.json');config=read_json(base/'config.json')
 initial=read_json(base/'training/selection.json')
 if not all(k in initial for k in ['dense_threshold','gate_floor']):raise ValueError('완료된 WaterDense 판별기가 필요합니다')
 for row in rows:
  feature=(source/'dense_features'/(row['sha256']+'.pt')).resolve()
  if not feature.is_relative_to(root) or not feature.is_file():raise ValueError('캐시 특징이 없거나 프로젝트 밖의 경로입니다')
 out.mkdir();(out/'training').mkdir();(out/'dense_features').symlink_to((source/'dense_features').resolve(),target_is_directory=True)
 for file in ['projection.pt','decoder.pt','selection.json']:shutil.copyfile(base/'training'/file,out/'training'/file)
 write_json(out/'selection.json',rows)
 write_json(out/'annotations_snapshot.json',{r['sha256']:r.get('annotation') for r in rows if r.get('annotation')})
 config.update(name=name,finetune_from=base.name,max_epochs=spec['steps'],new_originals=0,old_training_replay=True,distillation_on_old_training_only=True,tests_used_for_training_or_selection=False)
 write_json(out/'config.json',config)
 frozen={str(base/'training'/n):file_hash(base/'training'/n) for n in ['projection.pt','decoder.pt','selection.json']}
 frozen[str(source/'selection.json')]=file_hash(source/'selection.json');write_json(out/'frozen_inputs.json',frozen)
 parent=root/'artifacts'/config['parent_model'];state=torch.load(parent/'training/head.pt',weights_only=True,map_location='cpu')
 prior_head=mil.make_head(state['dimension']);prior_head.load_state_dict(state['state_dict']);prior_head.eval()
 cutoff=read_json(parent/'evaluation/threshold.json')['threshold']
 def records(records,roles):
  result=[]
  with torch.inference_mode():
   for r in records:
    if r['role'] not in roles:continue
    d=torch.load(source/'dense_features'/(r['sha256']+'.pt'),weights_only=True,map_location='cpu')
    if 'prior_scores' in d:prior=d['prior_scores']
    else:
     f=parent/'features'/(r['sha256']+'.pt')
     if f.is_file():
      legacy=torch.load(f,weights_only=True,map_location='cpu');x=((legacy['features']-state['mean'])/state['std']).clamp(-12,12)
      prior=torch.nn.functional.softplus(prior_head(x).flatten())/cutoff
      if len(legacy['points'])!=len(d['tiles'])*4:raise ValueError('기존 타일과 특징 좌표가 다릅니다')
      d['legacy_cells']=[int((p[1]-y)//32)*16+int((p[0]-x)//32) for (x,y),points in zip(d['tiles'],[legacy['points'][n:n+4] for n in range(0,len(legacy['points']),4)]) for p in points]
     elif r['role']=='train':prior=torch.zeros(len(d['tiles'])*4)
     else:raise ValueError('고정 검증·평가 특징이 없습니다')
    result.append((r,d,prior))
  return result
 warm.BASE=base;warm.OUT=out;warm.NAME=name;warm.MAX_EPOCHS=spec['steps'];warm.records=records
 def status(stage,**values):
  write_json(out/'pipeline_status.json',dict(stage=stage,**values))
  update(status='running',stage='WaterDense 위치 판별기 추가 학습' if stage=='warm_start_training' else stage,step=values.get('epoch',0),total=spec['steps'],unit='epoch')
 warm.status=status
 update(stage='기존 특징 재사용 · WaterDense 가중치 불러오기',unit='epoch')
 selected=warm.train(rows)
 update(stage='고정 테스트 · 이전 모델과 비교',step=spec['steps'])
 held=records(rows,{'test','regression','validation','calibration'})
 head=regular.make_decoder(128).cuda();head.load_state_dict(torch.load(out/'training/decoder.pt',weights_only=True,map_location='cpu')['state_dict'])
 old=regular.make_decoder(128).cuda();old.load_state_dict(torch.load(base/'training/decoder.pt',weights_only=True,map_location='cpu')['state_dict'])
 after=dense.fuse(held,regular.infer(head,held),selected['dense_threshold'],selected['gate_floor'])
 before=dense.fuse(held,regular.infer(old,held),initial['dense_threshold'],initial['gate_floor'])
 summary=dict(name=name,baseline=base.name,selected=selected,by_role={},tests_used_for_training_or_selection=False)
 results=[{**r,'before_score':b,'score':a,'threshold':1.,'pred_anomaly':a>1.,'before_pred_anomaly':b>1.} for (r,d,p),b,a in zip(held,before,after)]
 for role in ['test','regression','validation','calibration']:
  subset=[r for r in results if r['role']==role]
  summary['by_role'][role]=dict(before=dense.operating_metrics(subset,[r['before_score'] for r in subset],1.),after=dense.operating_metrics(subset,[r['score'] for r in subset],1.))
 write_json(out/'evaluation/summary.json',summary);write_json(out/'evaluation/results.json',results)
 write_json(out/'evaluation/threshold.json',dict(threshold=1.,dense_threshold=selected['dense_threshold'],calibration_sha256=[r['sha256'] for r in rows if r['role']=='calibration'],normal_originals=sum(r['role']=='calibration' for r in rows)))
 for file,digest in frozen.items():
  if file_hash(Path(file))!=digest:raise ValueError('기존 학습 입력이 변경됐습니다')
 saved=root/'saved_models'/name;saved.mkdir()
 for file in ['config.json','selection.json','annotations_snapshot.json','frozen_inputs.json','training/projection.pt','training/decoder.pt','training/selection.json','training/settings.json','training/history.json','evaluation/summary.json','evaluation/threshold.json']:
  dest=saved/file;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(out/file,dest)
 shutil.copyfile(root/'artifacts'/config['frozen_feature_model']/'training/model.ckpt',saved/'base_model.ckpt')
 shutil.copyfile(root/'artifacts'/config['legacy_feature_model']/'training/model.ckpt',saved/'legacy_model.ckpt')
 shutil.copyfile(parent/'training/head.pt',saved/'training/parent_head.pt')
 write_json(saved/'studio_training.json',spec);write_json(saved/'checksums.json',{str(p.relative_to(saved)):file_hash(p) for p in saved.rglob('*') if p.is_file()})
 update(status='completed',stage='WaterDense 학습·평가 완료',model=name,summary=summary,step=spec['steps'])
