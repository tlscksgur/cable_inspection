"""Same frozen checkpoint/images, compare exact COCO encodings and wall time."""
import json,time,copy
from pathlib import Path
import torch
import worker
from mmengine.runner import Runner
from mmdet.structures.mask import encode_mask_results

def main():
    root=Path('/srv/cable/cable_rtmdet/studio_rebuild')
    out=root/'optimization_20261019'
    spec=json.loads((root/'jobs/6385e4e6135b4db8/spec.json').read_text())
    spec.update(work_dir=str(out/'probe'),status_path=str(out/'status.json'),result_path=str(out/'unused.json'),fast_mask_encoding=False)
    class Captured(Exception):pass
    saved=Runner.from_cfg
    box={}
    def capture(cfg):box['cfg']=cfg;raise Captured()
    Runner.from_cfg=capture
    try:worker.run(spec)
    except Captured:pass
    finally:Runner.from_cfg=saved
    cfg=box['cfg']
    # Spread across the fixed valid ordering; do not alter source annotations.
    cfg.test_dataloader.dataset.indices=[0,40,80,160,240,360,440,480,520,640,800,960]
    runner=Runner.from_cfg(cfg);runner.load_or_resume();runner.model.eval()
    records=[]
    with torch.inference_mode():
     for i,batch in enumerate(runner.test_dataloader):
        torch.cuda.synchronize();t=time.perf_counter()
        output=runner.model.test_step(batch);torch.cuda.synchronize();forward=time.perf_counter()-t
        masks=output[0].pred_instances.masks
        times={};encoded={}
        for name,fn in [('old',lambda:encode_mask_results(masks.cpu().numpy())),('fast',lambda:worker.encode_cuda_masks(masks))]:
            torch.cuda.synchronize();t=time.perf_counter();encoded[name]=fn();torch.cuda.synchronize();times[name]=time.perf_counter()-t
        assert len(encoded['old'])==len(encoded['fast'])
        assert all(a==b for a,b in zip(encoded['old'],encoded['fast']))
        records.append(dict(image_id=output[0].img_id,masks=len(masks),forward_seconds=forward,encoding_seconds=times,exact=True))
        print('PROBE',records[-1],flush=True)
    result=dict(images=len(records),exact_rle=all(r['exact'] for r in records),records=records)
    for key in ('old','fast'):result[key+'_seconds']=sum(r['forward_seconds']+r['encoding_seconds'][key] for r in records)
    result['speedup']=result['old_seconds']/result['fast_seconds']
    (out/'benchmark_real.json').write_text(json.dumps(result,indent=2))
    print('RESULT',json.dumps(result),flush=True)

def train_probe():
    import gc
    root=Path('/srv/cable/cable_rtmdet/studio_rebuild');out=root/'optimization_20261019'
    spec=json.loads((root/'jobs/91192b996c52492e/spec.json').read_text())
    spec.update(checkpoint=str(root/'artifacts/664bde7e7faef9ca0d731eb8c1b87484d9afd9337fa773d9ab7421467969a9ee.pth'),start_mode='finetune',resume=False)
    records=[]
    for freeze in (False,True):
        spec.update(work_dir=str(out/('train_frozen' if freeze else 'train_all')),status_path=str(out/'train_status.json'),result_path=str(out/'train_result.json'))
        box={};saved=Runner.from_cfg
        class Captured(Exception):pass
        def capture(cfg):box['cfg']=cfg;raise Captured()
        Runner.from_cfg=capture
        try:worker.run(spec)
        except Captured:pass
        finally:Runner.from_cfg=saved
        cfg=box['cfg'];cfg.model.backbone.frozen_stages=2 if freeze else -1
        cfg.train_dataloader.dataset.indices=list(range(64))
        cfg.train_cfg=dict(type='EpochBasedTrainLoop',max_epochs=1,val_interval=99)
        cfg.val_dataloader=None;cfg.val_cfg=None;cfg.val_evaluator=None
        cfg.test_dataloader=None;cfg.test_cfg=None;cfg.test_evaluator=None
        cfg.custom_hooks=[];cfg.default_hooks.checkpoint=dict(type='CheckpointHook',interval=99,save_last=False)
        runner=Runner.from_cfg(cfg)
        from mmengine.hooks import Hook
        stats=[]
        class Clock(Hook):
            def before_train_iter(self,runner,batch_idx,data_batch=None):
                torch.cuda.synchronize();self.t=time.perf_counter()
            def after_train_iter(self,runner,batch_idx,data_batch=None,outputs=None):
                torch.cuda.synchronize();elapsed=time.perf_counter()-self.t
                loss=float(outputs['loss']);assert __import__('math').isfinite(loss)
                stats.append(dict(seconds=elapsed,loss=loss))
        runner.register_hook(Clock());runner.train()
        records.append(dict(frozen=freeze,steps=len(stats),mean_step_seconds=sum(s['seconds'] for s in stats[3:])/len(stats[3:]),finite_losses=True,trainable_parameters=sum(p.numel() for p in runner.model.parameters() if p.requires_grad)))
        del runner;gc.collect();torch.cuda.empty_cache()
    (out/'benchmark_train.json').write_text(json.dumps(records,indent=2));print('TRAIN_RESULT',json.dumps(records),flush=True)

if __name__=='__main__':
    import sys
    train_probe() if '--train' in sys.argv else main()
