"""Exercise worker setup with mocked MMDetection; never launch GPU work."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import worker

class Config(dict):
    def __getattr__(self,key):return self[key]
    def __setattr__(self,key,value):self[key]=value
    def dump(self,path):pass
    @staticmethod
    def fromfile(path):
        return Config(model=NS(bbox_head=NS(),backbone=NS(),data_preprocessor=NS(pad_mask=False)),
                      optim_wrapper=NS(optimizer=NS(lr=0),paramwise_cfg={}),default_hooks=NS(checkpoint=None),
                      custom_hooks=[dict(type='EarlyStoppingHook'),dict(type='EMAHook')],
                      train_cfg=dict(type='EpochBasedTrainLoop'),train_dataloader={'dataset':'empty'},
                      val_dataloader=NS(dataset=NS(pipeline=[dict(type='Resize',scale=(640,1536))])),
                      test_cfg=dict(type='TestLoop'),val_cfg=dict(type='ValLoop'))

class SetupTests(unittest.TestCase):
    def exercise(self,mode,resume=False,resume_epoch=0,start_mode='scratch'):
        class TrainStopped(Exception):pass
        captured={}
        class Runner:
            @classmethod
            def from_cfg(cls,cfg):
                captured['cfg']=cfg
                obj=cls();obj.test_dataloader=[1,2];obj.hooks=[];obj.message_hub=NS(runtime_info={},update_info=lambda *args:None);obj.val_loop=NS(run=lambda:(captured.update(recovered_validation=True) or {'coco/segm_mAP_50':.75}));return obj
            def register_hook(self,hook,**kwargs):self.hooks.append(hook)
            def test(self):
                cfg=captured['cfg']
                self.assert_no_train(cfg)
                for i in range(2):
                    for hook in self.hooks:hook.after_test_iter(self,i)
                return {'coco/segm_mAP_50':.75}
            def assert_no_train(self,cfg):
                assert cfg.custom_hooks==[]
                assert cfg.train_dataloader is None and cfg.train_cfg is None
                assert cfg.optim_wrapper is None and cfg.param_scheduler is None
                assert cfg.test_dataloader['dataset']['ann_file']=='valid.json'
                assert cfg.test_dataloader['dataset']['test_mode'] is True
                assert cfg.test_dataloader['batch_size']==1
                assert cfg.load_from=='my-model.pth'
                assert cfg.test_cfg['fp16'] is False
            def train(self):
                self.iter=1731;self.max_iters=69240;self.epoch=1;self.val_dataloader=[1,2]
                for hook in self.hooks:
                    if hasattr(hook,'before_train'):hook.before_train(self)
                for hook in self.hooks:
                    if hasattr(hook,'after_val_iter'):hook.after_val_iter(self,0)
                raise TrainStopped()
        modules={
          'torch':NS(serialization=NS(),cuda=NS(is_available=lambda:True)),
          'numpy':NS(),'numpy.core':NS(multiarray=NS()),
          'mmengine.logging.history_buffer':NS(HistoryBuffer=object),
          'mmengine.config':NS(Config=Config),'mmengine.runner':NS(Runner=Runner),
          'mmdet.utils':NS(register_all_modules=lambda:None),'mmengine.hooks':NS(Hook=object)}
        root=Path(__file__).parent/'.verification';root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            p=Path(folder);config=p/'config.py';config.write_text('# exported config')
            spec=dict(mode=mode,work_dir=str(p/'work'),config=str(config),mmdet_root=str(p),
                      dataset=str(p/'dataset'),classes=[{'id':'1','name':'bulge'}],
                      checkpoint='my-model.pth',version_id='fixed-valid',size='l',width=640,height=1536,
                      epochs=40,lr=.0002,patience=10,batch_size=2,resume=resume,resume_epoch=resume_epoch,start_mode=start_mode,
                      status_path=str(p/'status.json'),result_path=str(p/'result.json'))
            with patch.dict(sys.modules,modules), patch.object(worker,'register_fast_metric'):
                if mode=='train':
                    with self.assertRaises(TrainStopped):worker.run(spec)
                    progress=json.loads((p/'status.json').read_text())
                    self.assertEqual(progress['message'],'valid 검증 중 · epoch 1 · 1/2')
                    self.assertEqual(progress['progress'],2.5)
                else:
                    worker.run(spec)
                    result=json.loads((p/'result.json').read_text())
                    self.assertEqual(result['metrics']['coco/segm_mAP_50'],.75)
                    self.assertEqual(result['version_id'],'fixed-valid')
                    self.assertEqual(json.loads((p/'status.json').read_text())['step'],2)
            if resume_epoch==5 or (start_mode=='finetune' and not resume):self.assertTrue(captured.get('recovered_validation'))
            if start_mode=='finetune' and not resume:
                baseline=json.loads((p/'work'/'finetune_baseline.json').read_text())
                self.assertEqual(baseline['metrics']['coco/segm_mAP_50'],.75)
            elif mode=='train':self.assertFalse((p/'work'/'finetune_baseline.json').exists())
            return captured['cfg']

    def test_eval_uses_selected_checkpoint_valid_only_and_reports_results(self):
        self.exercise('eval')

    def test_finetune_reuses_early_features_but_resume_does_not_change_trainability(self):
        cfg=self.exercise('train',start_mode='finetune')
        self.assertEqual(cfg.model.backbone.frozen_stages,2)
        self.assertEqual(cfg.optim_wrapper.paramwise_cfg['custom_keys']['backbone']['lr_mult'],.1)
        resumed=self.exercise('train',resume=True,start_mode='finetune')
        self.assertFalse(hasattr(resumed.model.backbone,'frozen_stages'))

    def test_resuming_restores_training_state_without_changing_batch_or_schedule(self):
        cfg=self.exercise('train',resume=True)
        self.assertTrue(cfg.resume)
        self.assertEqual(cfg.load_from,'my-model.pth')
        self.assertEqual(cfg.train_cfg['max_epochs'],40)
        self.assertEqual(cfg.train_cfg['val_interval'],5)
        self.assertEqual(cfg.train_dataloader['batch_size'],2)
        self.assertEqual(cfg.optim_wrapper.optimizer.lr,.0002)

    def test_failed_validation_is_retried_in_float32_before_next_training_epoch(self):
        cfg=self.exercise('train',resume=True,resume_epoch=5)
        self.assertFalse(cfg.val_cfg['fp16'])
        self.assertEqual(cfg.optim_wrapper.type,'AmpOptimWrapper')

    def test_train_pads_masks_for_mixed_aspect_ratio_batch(self):
        cfg=self.exercise('train')
        self.assertTrue(cfg.model.data_preprocessor.pad_mask)
        self.assertEqual(cfg.train_cfg['val_interval'],5)
        self.assertEqual(cfg.optim_wrapper.type,'AmpOptimWrapper')
        self.assertFalse(cfg.val_cfg['fp16'])
        stop=cfg.custom_hooks[1]
        self.assertEqual(stop['patience'],2)
        self.assertEqual(stop['min_delta'],.001)
        self.assertFalse(cfg.resume)
        self.assertEqual(cfg.train_dataloader['batch_size'],2)
        self.assertEqual(cfg.train_dataloader['dataset']['pipeline'][2]['keep_ratio'],True)
        self.assertEqual(cfg.train_dataloader['dataset']['pipeline'][1]['with_mask'],True)

class CheckpointTests(unittest.TestCase):
    def test_selected_checkpoint_follows_recorded_score_not_newest_timestamp(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'.verification') as folder:
            work=Path(folder);baseline=work/'best_coco_segm_mAP_50_epoch_0.pth';baseline.write_bytes(b'better-start')
            (work/'best_coco_segm_mAP_50_epoch_20.pth').write_bytes(b'newer-but-worse')
            runner=NS(message_hub=NS(get_info=lambda key:str(baseline)))
            self.assertEqual(worker.selected_best_checkpoint(runner,work),baseline.resolve())
            baseline.unlink()
            with self.assertRaisesRegex(RuntimeError,'저장 위치'):worker.selected_best_checkpoint(runner,work)

    def test_copying_previous_best_keeps_original_and_redirects_only_best_paths(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'.verification') as folder:
            root=Path(folder);old=root/'old';new=root/'new';old.mkdir();new.mkdir()
            checkpoint=old/'epoch_2.pth';checkpoint.write_bytes(b'optimizer-and-weights')
            best=old/'best_coco_segm_mAP_50_epoch_1.pth';best.write_bytes(b'best-weights')
            info={'best_ckpt':str(best),'best_score':.75}
            runner=NS(message_hub=NS(runtime_info=info,update_info=lambda k,v:info.update({k:v})))
            worker.preserve_previous_best(runner,checkpoint,new)
            self.assertEqual(Path(info['best_ckpt']).read_bytes(),b'best-weights')
            self.assertEqual(Path(info['best_ckpt']).parent,new)
            self.assertEqual(best.read_bytes(),b'best-weights')
            self.assertEqual(checkpoint.read_bytes(),b'optimizer-and-weights')
            self.assertEqual(info['best_score'],.75)

if __name__=='__main__':unittest.main()
