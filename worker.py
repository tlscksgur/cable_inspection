"""Run inside an existing MMDetection CUDA environment; no auto-installation."""
import argparse
import ast
import json
import os
import shutil
import time
from pathlib import Path


def encode_cuda_masks(masks):
    """Exact COCO RLE; transfer run boundaries instead of full-resolution masks."""
    import torch
    from pycocotools import mask as mask_util
    # Small masks are faster through the ordinary CPU encoder.
    if masks.numel()<262144:
        from mmdet.structures.mask import encode_mask_results
        return encode_mask_results(masks.cpu().numpy())
    encoded=[]
    for mask in masks:
        h,w=mask.shape
        # COCO scans columns first. Include the initial zero run when needed.
        flat=mask.T.contiguous().flatten()
        edges=torch.nonzero(flat[1:] != flat[:-1],as_tuple=False).flatten()+1
        boundaries=torch.cat((edges.new_zeros(1),edges,edges.new_tensor([flat.numel()])))
        counts=(boundaries[1:]-boundaries[:-1]).cpu().tolist()
        if bool(flat[0]):counts.insert(0,0)
        encoded.append(mask_util.frPyObjects(dict(size=[h,w],counts=counts),h,w))
    return encoded


def register_fast_metric():
    from mmdet.registry import METRICS
    from mmdet.evaluation.metrics import CocoMetric
    @METRICS.register_module(name='StudioCocoMetric',force=True)
    class StudioCocoMetric(CocoMetric):
        def process(self,data_batch,data_samples):
            prepared=[]
            for sample in data_samples:
                item=dict(sample);pred=dict(item['pred_instances'])
                masks=pred.get('masks')
                if masks is not None and getattr(masks,'is_cuda',False):
                    pred['masks']=encode_cuda_masks(masks)
                item['pred_instances']=pred;prepared.append(item)
            return super().process(data_batch,prepared)


def portable_config(config, mmdet_root, work):
    """Resolve exported server-specific base paths without changing the original."""
    config = Path(config)
    source = config.read_text(encoding='utf-8')
    tree = ast.parse(source)
    bases = [n for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == '_base_' for t in n.targets)]
    if not bases:
        return str(config)
    if len(bases) != 1:
        raise ValueError('Multiple base configuration assignments')
    node = bases[0]
    original = ast.literal_eval(node.value)
    names = [original] if isinstance(original, str) else original
    resolved = []
    for name in names:
        candidate = Path(mmdet_root)/'configs'/'rtmdet'/Path(name).name
        if not candidate.is_file():
            raise ValueError(f'MMDetection base configuration missing: {candidate.name}')
        resolved.append(str(candidate.resolve()))
    lines = source.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno] = ['_base_ = '+repr(resolved)+'\n']
    target = Path(work)/'imported_runtime_config.py'
    target.write_text(''.join(lines), encoding='utf-8')
    return str(target)


def write(path, data):
    p=Path(path); temp=p.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,default=str),encoding='utf-8'); os.replace(temp,p)


def configure_evaluation(cfg, checkpoint):
    """Remove training-only state before constructing an evaluation runner."""
    cfg.load_from=checkpoint
    cfg.test_cfg=dict(type='TestLoop',fp16=False)
    # Exported training hooks (early stop/EMA/stage switching) must never
    # build a training loop while evaluating a frozen valid split.
    cfg.custom_hooks=[]
    cfg.train_dataloader=None;cfg.train_cfg=None;cfg.optim_wrapper=None
    cfg.param_scheduler=None
    cfg.val_dataloader=None;cfg.val_cfg=None;cfg.val_evaluator=None

def preserve_previous_best(runner,checkpoint,work):
    origin=Path(checkpoint).resolve().parent
    for key,value in list(runner.message_hub.runtime_info.items()):
        if not key.startswith('best_ckpt') or not isinstance(value,str):continue
        source=Path(value).resolve()
        if source.parent!=origin or not source.is_file():continue
        target=Path(work)/source.name
        if source!=target:shutil.copy2(source,target)
        runner.message_hub.update_info(key,str(target))


def selected_best_checkpoint(runner,work):
    """Return the scored checkpoint, never infer quality from file timestamps."""
    value=runner.message_hub.get_info('best_ckpt')
    if not value:raise RuntimeError('검증 기준 최고 체크포인트가 기록되지 않았습니다')
    checkpoint=Path(value).resolve()
    if checkpoint.parent!=Path(work).resolve() or not checkpoint.is_file():
        raise RuntimeError('최고 체크포인트의 저장 위치를 확인할 수 없습니다')
    return checkpoint


def remap_classification_state(source,target,source_classes,target_classes):
    """Copy every shared tensor exactly, remapping only RTMDet class output rows."""
    old_ids=[c['id'] for c in source_classes];new_ids=[c['id'] for c in target_classes]
    if len(set(old_ids))!=len(old_ids) or len(set(new_ids))!=len(new_ids) or not set(old_ids)<=set(new_ids):
        raise ValueError('추가 학습 클래스 ID 구성이 올바르지 않습니다')
    for c in source_classes:
        dst=target_classes[new_ids.index(c['id'])]
        if c['name']!=dst['name'] or bool(c.get('normal'))!=bool(dst.get('normal')):
            raise ValueError('기존 클래스의 의미가 달라졌습니다: '+c['name'])
    if set(source)!=set(target):
        missing=sorted(set(target)-set(source));extra=sorted(set(source)-set(target))
        raise ValueError('추가 학습 모델 구조가 다릅니다: missing='+str(missing[:5])+', extra='+str(extra[:5]))
    aligned={};heads=[]
    for key,fresh in target.items():
        prior=source[key]
        if key.startswith('bbox_head.rtm_cls.') and key.endswith(('.weight','.bias')):
            if prior.shape[0]!=len(old_ids) or fresh.shape[0]!=len(new_ids) or prior.shape[1:]!=fresh.shape[1:]:
                raise ValueError('분류 출력의 크기가 클래스 정보와 다릅니다: '+key)
            value=fresh.clone()
            for src_idx,class_id in enumerate(old_ids):value[new_ids.index(class_id)]=prior[src_idx]
            aligned[key]=value;heads.append(key)
        else:
            if prior.shape!=fresh.shape:raise ValueError('클래스 출력 외의 가중치 크기가 다릅니다: '+key)
            aligned[key]=prior
    if not heads:raise ValueError('RTMDet 분류 출력 가중치를 찾지 못했습니다')
    return aligned,dict(copied_tensors=len(target)-len(heads),remapped_class_tensors=heads,
                        preserved_classes=[c['name'] for c in source_classes],
                        initialized_classes=[c['name'] for c in target_classes if c['id'] not in old_ids])


def prepare_finetune_checkpoint(cfg,spec,work):
    import torch
    from mmdet.registry import MODELS
    from mmengine.runner.checkpoint import _load_checkpoint
    plan=spec['finetune_class_transfer']
    checkpoint=_load_checkpoint(spec['checkpoint'],map_location='cpu')
    actual=checkpoint.get('meta',{}).get('dataset_meta',{}).get('classes')
    if actual is not None and list(actual)!=[c['name'] for c in plan['source_classes']]:
        raise ValueError('체크포인트에 저장된 클래스 순서가 원본 모델 정보와 다릅니다')
    source=checkpoint.get('state_dict',checkpoint)
    if source and all(k.startswith('module.') for k in source):source={k[7:]:v for k,v in source.items()}
    # CPU initialization supplies the proper low-prior bias for newly added classes.
    model=MODELS.build(cfg.model);model.init_weights()
    target=model.state_dict()
    state,report=remap_classification_state(source,target,plan['source_classes'],plan['target_classes'])
    old_ids=[c['id'] for c in plan['source_classes']];new_ids=[c['id'] for c in plan['target_classes']]
    for key,prior in source.items():
        if key in report['remapped_class_tensors']:
            if any(not torch.equal(prior[i],state[key][new_ids.index(cid)]) for i,cid in enumerate(old_ids)):
                raise ValueError('기존 분류 가중치 보존 확인에 실패했습니다: '+key)
        elif not torch.equal(prior,state[key]):raise ValueError('기존 가중치 보존 확인에 실패했습니다: '+key)
    report['all_original_weights_verified']=True
    path=Path(work)/'finetune_initial.pth'
    # Fine-tune weights only: stale optimizer, EMA, epoch and best scores are not reused.
    torch.save(dict(state_dict=state,meta=dict(dataset_meta=dict(classes=tuple(c['name'] for c in plan['target_classes'])))),path)
    report.update(source_model_id=plan['source_model_id'],source_model_name=plan['source_model_name'])
    write(Path(work)/'class_transfer.json',report)
    return str(path)


def run(spec):
    import torch
    import codecs
    import numpy as np
    from numpy.core import multiarray
    from mmengine.logging.history_buffer import HistoryBuffer
    # MMEngine exports contain training-history/numpy metadata. Keep PyTorch's
    # restricted loader and allow only these known metadata constructors.
    if hasattr(torch.serialization,'add_safe_globals'):
        torch.serialization.add_safe_globals([
            HistoryBuffer,getattr,codecs.encode,np.ndarray,np.dtype,
            (multiarray._reconstruct,'numpy._core.multiarray._reconstruct'),
            (multiarray.scalar,'numpy._core.multiarray.scalar'),
            multiarray._reconstruct,multiarray.scalar,
            *{type(np.dtype(t)) for t in (np.float64,np.float32,np.float16,np.int64,np.int32,np.int16,np.int8,np.uint64,np.uint32,np.uint16,np.uint8,np.bool_)}])
    from mmengine.config import Config
    from mmengine.runner import Runner
    from mmdet.utils import register_all_modules
    register_all_modules()
    if spec.get('fast_mask_encoding',True):register_fast_metric()
    if not torch.cuda.is_available(): raise RuntimeError('CUDA GPU를 찾을 수 없습니다')
    if hasattr(torch,'set_num_threads'):torch.set_num_threads(4)
    mode=spec['mode']; work=Path(spec['work_dir']); work.mkdir(parents=True,exist_ok=True)
    def status(**kw): write(spec['status_path'],kw)
    if mode=='predict':
        import cv2
        from mmdet.apis import init_detector, inference_detector
        config=portable_config(spec['config'],spec['mmdet_root'],work)
        model=init_detector(config,spec['checkpoint'],device='cuda:0')
        predictions=[]
        for i,image in enumerate(spec['images']):
            instances=inference_detector(model,image['path']).pred_instances.cpu()
            annotations=[]
            for j,score in enumerate(instances.scores):
                if float(score)<spec['threshold']: continue
                contours,_=cv2.findContours(instances.masks[j].numpy().astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                # Keep every disconnected component instead of silently losing mask areas.
                for contour in contours:
                    contour=cv2.approxPolyDP(contour,1.,True)
                    if len(contour)<3 or abs(cv2.contourArea(contour))<1: continue
                    annotations.append(dict(class_id=spec['classes'][int(instances.labels[j])]['id'],points=contour[:,0,:].tolist(),score=float(score),source='auto'))
            predictions.append(dict(image_id=image['id'],revision=image['revision'],annotations=annotations))
            status(step=i+1,total_steps=len(spec['images']),progress=round((i+1)/len(spec['images'])*100,1),message='마스크 예측 중')
        write(spec['result_path'],dict(predictions=predictions)); return
    if mode=='train':
        cfg=Config.fromfile(str(Path(spec['mmdet_root'])/'configs'/'rtmdet'/f'rtmdet-ins_{spec["size"]}_8xb32-300e_coco.py'))
        cfg.model.bbox_head.num_classes=len(spec['classes'])
        cfg.model.backbone.init_cfg=None
        if spec.get('start_mode')=='finetune' and not spec.get('resume'):
            # Reuse early visual features; adapt later stages, neck and heads.
            cfg.model.backbone.frozen_stages=2
            cfg.optim_wrapper.paramwise_cfg.setdefault('custom_keys',{})['backbone']=dict(lr_mult=.1)
        elif spec.get('resume'):
            previous=Path(spec['checkpoint']).parent/'training_config.py'
            if previous.is_file():
                previous_cfg=Config.fromfile(str(previous))
                cfg.model.backbone.frozen_stages=previous_cfg.model.backbone.get('frozen_stages',-1)
                cfg.optim_wrapper.paramwise_cfg=previous_cfg.optim_wrapper.get('paramwise_cfg',{})
        # RTMDet-Ins concatenates positive masks across a batch. Pad masks
        # to the same batch dimensions as images, including mixed aspect ratios.
        cfg.model.data_preprocessor.pad_mask=True
        scale=(spec['width'],spec['height'])
        train_pipeline=[dict(type='LoadImageFromFile'),dict(type='LoadAnnotations',with_bbox=True,with_mask=True,poly2mask=False),dict(type='Resize',scale=scale,keep_ratio=True),dict(type='RandomFlip',prob=.5),dict(type='Pad',size_divisor=32,pad_val=dict(img=(114,114,114))),dict(type='PackDetInputs')]
        val_pipeline=[dict(type='LoadImageFromFile'),dict(type='Resize',scale=scale,keep_ratio=True),dict(type='Pad',size_divisor=32,pad_val=dict(img=(114,114,114))),dict(type='LoadAnnotations',with_bbox=True,with_mask=True,poly2mask=False),dict(type='PackDetInputs',meta_keys=('img_id','img_path','ori_shape','img_shape','scale_factor'))]
        interval=min(5,spec['epochs'])
        cfg.train_cfg=dict(type='EpochBasedTrainLoop',max_epochs=spec['epochs'],val_interval=interval)
        cfg.val_cfg=dict(type='ValLoop',fp16=False)
        cfg.optim_wrapper.type='AmpOptimWrapper'
        cfg.optim_wrapper.loss_scale='dynamic'
        cfg.optim_wrapper.optimizer.lr=spec['lr']
        cfg.param_scheduler=[dict(type='CosineAnnealingLR',by_epoch=True,begin=0,end=spec['epochs'],T_max=spec['epochs'],eta_min=spec['lr']*.05)]
        cfg.custom_hooks=[dict(type='EMAHook',ema_type='ExpMomentumEMA',momentum=.0002,update_buffers=True,priority=49),dict(type='EarlyStoppingHook',monitor='coco/segm_mAP_50',patience=max(1,(spec['patience']+interval-1)//interval),min_delta=.001,rule='greater')]
        cfg.default_hooks.checkpoint=dict(type='CheckpointHook',interval=1,max_keep_ckpts=2,save_best='coco/segm_mAP_50',rule='greater')
        cfg.load_from=spec.get('checkpoint'); cfg.resume=bool(spec.get('resume')); cfg.auto_scale_lr=dict(enable=False)
        cfg.randomness=dict(seed=42)
    else:
        cfg=Config.fromfile(portable_config(spec['config'],spec['mmdet_root'],work))
        val_pipeline=cfg.val_dataloader.dataset.pipeline
    root=Path(spec['dataset'])
    classes=tuple(x['name'] for x in spec['classes'])
    for name,split in [('train','train'),('val','valid'),('test','valid')]:
        pipeline=train_pipeline if mode=='train' and name=='train' else val_pipeline
        ds=dict(type='CocoDataset',data_root=str(root)+os.sep,ann_file=f'{split}.json',data_prefix=dict(img='images/'),metainfo=dict(classes=classes),pipeline=pipeline,test_mode=name!='train',filter_cfg=dict(filter_empty_gt=False,min_size=1) if name=='train' else None)
        loader=dict(batch_size=spec.get('batch_size',1) if name=='train' else 1,num_workers=0,persistent_workers=False,pin_memory=False,sampler=dict(type='DefaultSampler',shuffle=name=='train'),dataset=ds)
        if os.name!='nt':
            loader.update(num_workers=4,persistent_workers=True,pin_memory=True,prefetch_factor=2)
        if name!='train': loader['drop_last']=False
        cfg[f'{name}_dataloader']=loader
    for name in ('val','test'):
        cfg[f'{name}_evaluator']=dict(type='StudioCocoMetric' if spec.get('fast_mask_encoding',True) else 'CocoMetric',ann_file=str(root/'valid.json'),metric=['bbox','segm'],format_only=False)
    cfg.work_dir=str(work); cfg.launcher='none'
    cfg.env_cfg=dict(cudnn_benchmark=False,mp_cfg=dict(mp_start_method='spawn',opencv_num_threads=0),dist_cfg=dict(backend='nccl'))
    if mode=='train' and spec.get('finetune_class_transfer') and not spec.get('resume'):
        if spec.get('start_mode')!='finetune':raise ValueError('클래스 전달은 추가 학습에서만 사용할 수 있습니다')
        status(message='기존 클래스 가중치 보존 · 새 클래스 출력 준비 중',progress=0)
        cfg.load_from=prepare_finetune_checkpoint(cfg,spec,work)
    if mode=='eval':
        configure_evaluation(cfg,spec['checkpoint'])
    config_path=work/'training_config.py'; cfg.dump(str(config_path))
    runner=Runner.from_cfg(cfg)
    stage_seconds=dict(train=0.,validation=0.,evaluation=0.)
    if mode=='eval':
        status(message='고정된 valid 데이터 평가 중',progress=0)
        from mmengine.hooks import Hook
        class EvalProgress(Hook):
            def before_test(self,runner):self.started=time.perf_counter()
            def after_test(self,runner):
                stage_seconds['evaluation']=time.perf_counter()-self.started
                write(work/'stage_times.json',stage_seconds)
            def after_test_iter(self,runner,batch_idx,data_batch=None,outputs=None):
                total=len(runner.test_dataloader)
                status(step=batch_idx+1,total_steps=total,
                       progress=round((batch_idx+1)/max(total,1)*100,1),
                       message=f'valid 평가 중 · {batch_idx+1}/{total}' if batch_idx+1<total else 'valid 추론 완료 · mAP 집계 중')
        runner.register_hook(EvalProgress())
        metrics=runner.test()
        write(spec['result_path'],dict(metrics=metrics,version_id=spec['version_id'],split='valid',
                                      evaluation_scope=spec.get('evaluation_scope'))); return
    from mmengine.hooks import Hook
    class Progress(Hook):
        def before_train_epoch(self,runner):self.started=time.perf_counter()
        def after_train_epoch(self,runner):
            stage_seconds['train']+=time.perf_counter()-self.started
            write(work/'stage_times.json',stage_seconds)
        def before_val(self,runner):self.val_started=time.perf_counter()
        def after_val(self,runner):
            stage_seconds['validation']+=time.perf_counter()-self.val_started
            write(work/'stage_times.json',stage_seconds)
        def after_val_iter(self,runner,batch_idx,data_batch=None,outputs=None):
            total=len(runner.val_dataloader);epoch=max(runner.epoch,1)
            status(step=runner.iter,total_steps=runner.max_iters,epoch=epoch,
                   progress=round(runner.iter/max(runner.max_iters,1)*100,1),
                   message=f'valid 검증 중 · epoch {epoch} · {batch_idx+1}/{total}')
        def after_train_iter(self,runner,batch_idx,data_batch=None,outputs=None):
            if runner.iter%10==0:
                status(step=runner.iter+1,total_steps=runner.max_iters,epoch=runner.epoch+1,progress=round((runner.iter+1)/max(runner.max_iters,1)*100,1),message='RTMDet-Ins 학습 중')
    if spec.get('resume'):
        class PreservePreviousBest(Hook):
            def before_train(self,runner):
                preserve_previous_best(runner,spec['checkpoint'],work)
        runner.register_hook(PreservePreviousBest(),priority='HIGH')
    runner.register_hook(Progress(),priority='LOWEST')
    if spec.get('resume') and spec.get('resume_epoch',0)>0 and spec['resume_epoch']%interval==0:
        class ValidateRecoveredCheckpoint(Hook):
            def before_train(self,runner):
                # Epoch checkpoints are saved before validation. Complete the due
                # validation first instead of waiting another five epochs.
                runner.val_loop.run()
        runner.register_hook(ValidateRecoveredCheckpoint(),priority='LOWEST')
    elif spec.get('start_mode')=='finetune' and not spec.get('resume'):
        class ValidateFineTuneStartingPoint(Hook):
            def before_train(self,runner):
                # Same classes/data/EMA and scoring hook as later validations.
                # CheckpointHook includes epoch 0 among best candidates, so a
                # degraded fine-tune cannot replace its better starting weights.
                status(message='추가 학습 전 시작 모델 성능 확인 중',progress=0)
                metrics=runner.val_loop.run()
                write(work/'finetune_baseline.json',dict(metrics=metrics,source_model_id=spec.get('source_model_id'),
                                                       source_model_name=spec.get('source_model_name')))
        runner.register_hook(ValidateFineTuneStartingPoint(),priority='LOWEST')
    runner.train()
    best=selected_best_checkpoint(runner,work)
    metrics=runner.message_hub.get_info('best_score')
    result=dict(checkpoint=str(best),config=str(config_path),metrics={'best_mask_mAP50':metrics})
    baseline=work/'finetune_baseline.json'
    if baseline.exists():result['finetune_baseline']=json.loads(baseline.read_text(encoding='utf8'))
    transfer_report=work/'class_transfer.json'
    if transfer_report.exists():result['class_transfer']=json.loads(transfer_report.read_text(encoding='utf-8'))
    write(spec['result_path'],result)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--probe',action='store_true'); p.add_argument('--spec'); args=p.parse_args()
    if args.probe:
        try:
            import torch, mmcv, mmdet
            import mmcv.ops
            ready=torch.cuda.is_available()
            print(json.dumps(dict(ready=ready,reason='RTMDet-Ins 환경 연결됨' if ready else 'CUDA GPU가 없습니다',torch=torch.__version__,mmdet=mmdet.__version__)))
        except Exception as e: print(json.dumps(dict(ready=False,reason='MMDetection CUDA 환경을 확인하세요: '+type(e).__name__)))
    else:
        write(Path(args.spec).parent/'pid.json',dict(pid=os.getpid(),spec=str(Path(args.spec).resolve())))
        run(json.loads(Path(args.spec).read_text(encoding='utf-8')))
