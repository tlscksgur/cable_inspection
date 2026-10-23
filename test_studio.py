import hashlib
import http.client
import io
import json
import os
import sqlite3
import struct
import tempfile
import threading
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

from server import create_server
from store import Store
from import_backup import run as import_backup


def png(width=64,height=2160,shade=100):
    def chunk(kind,data): return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    rows=(b'\x00'+bytes([shade,shade,shade])*width)*height
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')


class StudioTests(unittest.TestCase):
    def setUp(self):
        test_root=Path(__file__).parent.resolve()/'.verification'
        test_root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=test_root,prefix='test-')
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(test_root))
        with patch.dict(os.environ,{'STUDIO_ML_PYTHON':'','STUDIO_MMDET_ROOT':''}):
            self.server=create_server(self.temp.name,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.studio=self.server.studio; self.store=self.studio.store

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def req(self,path,body=None,method=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        headers=headers or {}
        if body is not None and not isinstance(body,bytes):
            body=json.dumps(body).encode(); headers={'Content-Type':'application/json',**headers}
        c.request(method or ('POST' if body is not None else 'GET'),path,body,headers)
        r=c.getresponse(); content=r.read(); status=r.status; c.close()
        return status,json.loads(content) if r.getheader('Content-Type','').startswith('application/json') else content

    def image(self,name='2026_10_16_10_00_00_000_SensorA.png',shade=100,batch='test'):
        meta=dict(name=name,width=64,height=2160,batch=batch)
        status,result=self.req('/api/upload',png(shade=shade),headers={'X-Upload-Meta':json.dumps(meta)})
        self.assertEqual(status,200,result);return result

    def annotate(self,x,status='reviewed'):
        body=dict(revision=x['revision'],status=status,annotations=[dict(class_id='1',points=[[1,1500],[50,1500],[50,2100],[1,2100]])])
        code,result=self.req('/api/images/'+x['id'],body);self.assertEqual(code,200,result);return result

    def test_custom_editor_shortcuts_persist_in_settings(self):
        code,result=self.req('/api/settings',dict(shortcuts={'review':'K','next':'J','ambiguous':'U'}))
        self.assertEqual(code,200,result)
        self.assertEqual(self.req('/api/state')[1]['settings']['shortcuts']['review'],'K')
        self.assertEqual(Store(self.store.path).all('settings')[0]['value']['next'],'J')

    def test_original_height_and_duplicate_preservation(self):
        x=self.image(); x=self.annotate(x)
        self.assertEqual(x['height'],2160);self.assertEqual(x['annotations'][0]['points'][2][1],2100)
        duplicate=self.image();self.assertTrue(duplicate['skipped'])
        self.assertEqual(len(self.store.all('images')),1)
        self.assertEqual((Path(self.temp.name)/'media'/x['file']).read_bytes(),png())

    def test_imported_boundary_polygons_save_without_changing_original_coordinates(self):
        x=self.image()
        original=dict(id='original',class_id='1',points=[[-2,1500],[50,1500],[50,2163]],source='human',group_id='one-mask')
        x['annotations']=[original];self.store.put('images',x)
        code,result=self.req('/api/images/'+x['id'],dict(revision=1,note='reviewed note',annotations=[original]))
        self.assertEqual(code,200,result)
        self.assertEqual(result['annotations'],[original])
        changed={**original,'points':[[-3,1500],[50,1500],[50,2163]]}
        self.assertEqual(self.req('/api/images/'+x['id'],dict(revision=result['revision'],annotations=[changed]))[0],400)

    def test_disconnected_original_mask_stays_one_coco_instance(self):
        x=self.image()
        x['annotations']=[dict(id=str(i),class_id='1',group_id='same-mask',points=p,source='human')
            for i,p in enumerate([[[1,1],[10,1],[10,10]],[[20,20],[30,20],[30,30]]])]
        result=self.studio.coco(dict(classes=self.store.all('classes'),images=[x]))
        self.assertEqual(len(result['annotations']),1)
        self.assertEqual(len(result['annotations'][0]['segmentation']),2)

    def test_state_has_version_summaries_without_snapshot_payload(self):
        self.store.put('versions',dict(id='v-source',name='v27',images=[{'huge':'snapshot'}],classes=[],counts={'train':1}))
        code,result=self.req('/api/state')
        self.assertEqual(code,200)
        self.assertNotIn('images',result['versions'][0])
        self.assertEqual(self.store.get('versions','v-source')['images'],[{'huge':'snapshot'}])

    def test_compact_state_preserves_full_labels_for_editor_and_previews(self):
        image=self.annotate(self.image())
        image['original_source']={'large_metadata':'preserved'}
        self.store.put('images',image)
        code,state=self.req('/api/state?compact=1')
        self.assertEqual(code,200)
        brief=state['images'][0]
        self.assertTrue(brief['_summary'])
        self.assertEqual(brief['annotations'],[{'class_id':'1'}])
        self.assertNotIn('original_source',brief)
        code,detail=self.req('/api/images/'+image['id'])
        self.assertEqual(detail['annotations'],image['annotations'])
        self.assertEqual(detail['original_source'],image['original_source'])
        code,previews=self.req('/api/image-previews?ids='+image['id'])
        self.assertEqual(previews[0]['annotations'][0]['points'],image['annotations'][0]['points'])
        self.assertEqual(previews[0]['revision'],image['revision'])
        self.assertEqual(self.store.get('images',image['id']),image)

    def test_activity_does_not_include_image_collection(self):
        self.image()
        code,activity=self.req('/api/activity')
        self.assertEqual(code,200)
        self.assertNotIn('images',activity)
        self.assertIn('jobs',activity)

    def test_conflict_and_invalid_polygon_leave_data_unchanged(self):
        x=self.image(); updated=self.annotate(x)
        code,_=self.req('/api/images/'+x['id'],dict(revision=x['revision'],note='stale'))
        self.assertEqual(code,400)
        for point in ([[1,2200],[10,100],[50,500]],[[1,1],[2,2],[3,float('nan')]]):
            code,_=self.req('/api/images/'+x['id'],dict(revision=updated['revision'],annotations=[dict(class_id='1',points=point)]))
            self.assertEqual(code,400)
        self.assertEqual(self.store.get('images',x['id']),updated)

    def test_bulk_preflight_and_soft_trash_restore(self):
        x=self.image()
        code,_=self.req('/api/images/bulk',dict(ids=[x['id'],'missing'],changes=dict(deleted=True)))
        self.assertEqual(code,404);self.assertFalse(self.store.get('images',x['id'])['deleted'])
        for deleted in (True,False):
            code,_=self.req('/api/images/bulk',dict(ids=[x['id']],changes=dict(deleted=deleted)))
            self.assertEqual(code,200);self.assertEqual(self.store.get('images',x['id'])['deleted'],deleted)
            self.assertTrue(self.studio.media(x['file']).is_file())

    def test_split_adjacent_originals_and_stale_preview(self):
        a=self.image();b=self.image('2026_10_16_10_00_05_000_SensorA.png',101,'another-upload')
        c=self.image('2026_10_16_12_00_00_000_SensorA.png',102,'another-upload')
        body=dict(train=70,valid=20,test=10,gap=10,scope='unassigned')
        code,preview=self.req('/api/split/preview',body);self.assertEqual(code,200);self.assertEqual(preview['groups'],2)
        self.assertEqual(sum(preview['counts'].values()),3)
        self.studio.bulk(dict(ids=[c['id']],changes=dict(tags=['changed'])))
        code,_=self.req('/api/split/apply',{**body,'fingerprint':preview['fingerprint']});self.assertEqual(code,400)
        _,preview=self.req('/api/split/preview',body)
        code,_=self.req('/api/split/apply',{**body,'fingerprint':preview['fingerprint']});self.assertEqual(code,200)
        self.assertEqual(self.store.get('images',a['id'])['split'],self.store.get('images',b['id'])['split'])
        self.assertEqual(self.req('/api/split/preview',{**body,'train':99})[0],400)

    def test_version_snapshot_and_coco_yolo_export(self):
        x=self.annotate(self.image());self.studio.save_batch(dict(id=x['batch'],stage='done'))
        self.studio.bulk(dict(ids=[x['id']],changes=dict(split='valid')))
        code,v=self.req('/api/versions',dict(name='frozen'));self.assertEqual(code,200)
        current=self.store.get('images',x['id']);self.studio.update_image(x['id'],dict(revision=current['revision'],annotations=[]))
        self.studio.save_class(dict(id='1',name='renamed',color='#112233'))
        frozen=self.store.get('versions',v['id']);self.assertEqual(len(frozen['images'][0]['annotations']),1)
        code,blob=self.req('/api/versions/'+v['id']+'/export?format=coco&images=1');self.assertEqual(code,200)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            coco=json.loads(z.read('valid.json'));self.assertEqual(coco['images'][0]['height'],2160)
            self.assertEqual(coco['categories'][0]['name'],'bulge');self.assertEqual(coco['annotations'][0]['bbox'],[1.,1500.,49.,600.])
            self.assertIn('images/'+x['file'],z.namelist())
        code,blob=self.req('/api/versions/'+v['id']+'/export?format=yolo');self.assertEqual(code,200)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            line=z.read('labels/valid/'+Path(x['file']).stem+'.txt').decode().split()
            self.assertAlmostEqual(float(line[2]),1500/2160,places=5)

    def test_auto_and_ambiguous_excluded_from_versions(self):
        a=self.image();b=self.image('second.png',101);c=self.image('third.png',102)
        self.studio.save_batch(dict(id=a['batch'],stage='done'))
        self.studio.bulk(dict(ids=[a['id'],b['id'],c['id']],changes=dict(split='train')))
        self.studio.bulk(dict(ids=[a['id']],changes=dict(status='ambiguous')))
        self.studio.bulk(dict(ids=[b['id']],changes=dict(status='auto')))
        version=self.studio.create_version({})
        self.assertEqual([x['id'] for x in version['images']],[c['id']])

    def test_version_always_uses_done_batches_and_train_selection_does_not_reduce_valid_test(self):
        images=[]
        for i,(batch,stage,split) in enumerate([('done-A','done','train'),('done-B','done','train'),('done-A','done','valid'),('done-B','done','test'),('review','review','train'),('new','new','train'),('labeling','labeling','train')]):
            x=self.annotate(self.image(name=f'case{i}.png',shade=120+i,batch=batch))
            self.studio.save_batch(dict(id=x['batch'],stage=stage));self.studio.bulk(dict(ids=[x['id']],changes=dict(split=split)));images.append(x)
        all_done=self.studio.create_version(dict(name='done-default',train_batches=[]))
        self.assertEqual({x['id'] for x in all_done['images']},{x['id'] for x in images[:4]})
        forced=self.studio.create_version(dict(name='cannot-disable',done_only=False))
        self.assertTrue(forced['rules']['done_only']);self.assertEqual(forced['counts'],all_done['counts'])
        one=self.studio.create_version(dict(name='one-batch',train_batches=[images[0]['batch']]))
        self.assertEqual({x['id'] for x in one['images']},{images[i]['id'] for i in (0,2,3)})
        self.assertEqual(one['rules']['resolved_train_batches'],[images[0]['batch']])
        self.assertTrue(all(b['stage']=='done' for b in one['batch_snapshot']))
        with self.assertRaisesRegex(ValueError,'완료 배치만'):
            self.studio.create_version(dict(name='reject-review',train_batches=[images[4]['batch']]))
        self.assertEqual(len(self.store.all('versions')),3)

    def test_completed_reviewed_unsplit_uploads_cannot_silently_disappear_from_version(self):
        old=self.image(batch='old');self.studio.save_batch(dict(id=old['batch'],stage='done'))
        self.studio.bulk(dict(ids=[old['id']],changes=dict(split='train')))
        new=self.annotate(self.image(name='new.png',shade=112,batch='newData - mix'))
        self.studio.save_batch(dict(id=new['batch'],stage='done'))
        code,preview=self.req('/api/versions/preview',{})
        self.assertEqual(code,200);self.assertEqual(preview['counts']['train'],1)
        self.assertEqual(preview['pending_count'],1)
        self.assertEqual(preview['pending_batches'][0]['name'],'newData - mix')
        code,result=self.req('/api/versions',dict(name='must-not-silently-ignore'))
        self.assertEqual(code,400);self.assertIn('미분할 사진 1장',result['error'])
        self.assertEqual(self.store.all('versions'),[])
        self.assertEqual(self.store.get('images',new['id'])['split'],'')
        self.studio.bulk(dict(ids=[new['id']],changes=dict(split='train')))
        code,version=self.req('/api/versions',dict(name='new-data-included'))
        self.assertEqual(code,200);self.assertEqual(version['counts']['train'],2)
        self.assertEqual(version['selection_audit']['pending_count'],0)
        with tempfile.TemporaryDirectory(dir=self.temp.name) as folder:
            self.studio.materialize(version,folder)
            coco=json.loads((Path(folder)/'train.json').read_text(encoding='utf8'))
            self.assertEqual({x['file_name'] for x in coco['images']},{old['file'],new['file']})

    def test_version_pending_respects_filters_and_explicit_train_batch_scope(self):
        old=self.image(batch='ready');self.studio.save_batch(dict(id=old['batch'],stage='done'))
        self.studio.bulk(dict(ids=[old['id']],changes=dict(split='train')))
        new=self.image(name='pending.png',shade=113,batch='pending');self.studio.save_batch(dict(id=new['batch'],stage='done'))
        auto=self.image(name='auto.png',shade=114,batch='pending');auto=self.annotate(auto,status='auto')
        preview=self.studio.preview_version(dict(train_batches=[old['batch']]))
        self.assertEqual(preview['pending_count'],0)
        self.assertEqual(preview['excluded']['automatic_label'],1)
        self.assertEqual(preview['excluded']['unselected_batch'],1)
        self.assertEqual(self.studio.preview_version(dict(reviewed_only=True))['pending_count'],0)
        self.assertEqual(self.studio.preview_version(dict(include_background=False))['pending_count'],0)
        self.assertEqual(self.studio.preview_version({})['pending_count'],1)
        self.assertEqual(self.studio.create_version(dict(train_batches=[old['batch']]))['counts']['train'],1)

    def test_version_commit_rechecks_uploads_arriving_after_preview(self):
        old=self.image();self.studio.save_batch(dict(id=old['batch'],stage='done'))
        self.studio.bulk(dict(ids=[old['id']],changes=dict(split='train')))
        self.assertEqual(self.studio.preview_version({})['pending_count'],0)
        self.image(name='late.png',shade=115)
        self.assertEqual(self.req('/api/versions',dict(name='stale-preview'))[0],400)
        self.assertEqual(self.store.all('versions'),[])

    def test_unconfigured_training_is_not_fake_success(self):
        self.assertEqual(self.req('/api/jobs',dict(mode='train',model_type='other'))[0],400)
        code,result=self.req('/api/jobs',dict(mode='train',model_type='RTMDet-Ins'));self.assertEqual(code,503)
        self.assertEqual(self.store.all('jobs'),[])
        self.assertFalse(self.req('/api/state')[1]['connection']['ml']['ready'])

    def test_reject_foreign_database_without_modification(self):
        path=Path(self.temp.name)/'original.sqlite'
        c=sqlite3.connect(path)
        c.execute('CREATE TABLE original(id INTEGER)'); c.commit(); c.close()
        before=hashlib.sha256(path.read_bytes()).digest()
        with self.assertRaises(ValueError):Store(path)
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),before)

    def test_no_cross_origin_or_private_file_serving(self):
        self.assertEqual(self.req('/api/settings',dict(project_name='bad'),headers={'Origin':'http://evil.test'})[0],403)
        self.assertEqual(self.req('/api/state',headers={'Host':'evil.test'})[0],403)
        self.assertEqual(self.req('/%2e%2e/server.py')[0],404)
        self.assertEqual(self.req('/data/studio.sqlite')[0],404)
        self.assertEqual(self.req('/api/unknown')[0],404)

    def model(self, name='model-test'):
        root=Path(self.temp.name)
        cp=root/(name+'.pth'); cfg=root/(name+'.py')
        cp.write_bytes(b'checkpoint-fixture-not-a-trained-model')
        cfg.write_text('# test fixture; never executed\n',encoding='utf-8')
        code,model=self.req('/api/models/register',dict(name=name,size='l',checkpoint=str(cp),config=str(cfg)))
        self.assertEqual(code,200,model)
        return model

    def test_model_bundle_preserves_imported_metadata_and_limits_files(self):
        model=self.model()
        extra=Path(model['checkpoint']).parent/'model_info.json'
        extra.write_text('{"trained_on":27}',encoding='utf-8')
        outside=Path(self.temp.name)/'other'/'outside.txt'
        outside.parent.mkdir()
        outside.write_text('not a model artifact',encoding='utf-8')
        model['artifacts']=[model['checkpoint'],model['config'],str(extra),str(outside)]
        self.store.put('models',model)
        code,blob=self.req('/api/models/'+model['id']+'/download?bundle=1')
        self.assertEqual(code,200)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            self.assertEqual(z.read('model.pth'),Path(model['checkpoint']).read_bytes())
            self.assertEqual(z.read('training_config.py'),Path(model['config']).read_bytes())
            self.assertEqual(z.read('original/model_info.json'),extra.read_bytes())
            self.assertNotIn('original/outside.txt',z.namelist())

    def test_remote_login_is_not_persisted_and_evaluation_updates_selected_version(self):
        model=self.model();valid=self.image();train=self.image(name='train.png',shade=101)
        valid['split']='valid';train['split']='train'
        self.store.put('versions',dict(id='remote-version',name='v-test',images=[valid,train],
            classes=self.store.all('classes'),counts={'valid':1,'train':1}))
        from unittest.mock import Mock
        process=Mock();process.poll.return_value=None;process.progress_snapshot.return_value={}
        training=Mock();training.poll.return_value=None;training.progress_snapshot.return_value={}
        scratch=Mock();scratch.poll.return_value=None;scratch.progress_snapshot.return_value={}
        with patch('remote_ml.RemoteBackend') as backend:
            backend.return_value.root='/mmdet'
            backend.return_value.info=dict(ready=True,remote=True,reason='test fixture')
            backend.return_value.start.side_effect=[process,training,scratch]
            backend.return_value.gpu_info.return_value=dict(available=True,gpus=[dict(index=0,utilization=12,memory_used_mib=2093,memory_total_mib=97887,temperature=45)])
            code,_=self.req('/api/ml/connect',dict(password='fixture-password-not-real'))
            self.assertEqual(code,200)
            code,job=self.req('/api/jobs',dict(mode='eval',model_id=model['id'],version_id='remote-version'))
            self.assertEqual(code,200,job)
            code,train_job=self.req('/api/jobs',dict(mode='train',resume_model=model['id'],version_id='remote-version',size='l'))
            self.assertEqual(code,200,train_job)
            self.assertNotEqual(job['id'],train_job['id'])
            self.assertEqual(len(self.server.ml.processes),2)
            self.assertEqual(train_job['spec']['start_mode'],'finetune')
            self.assertEqual(train_job['spec']['checkpoint'],model['checkpoint'])
            code,new_job=self.req('/api/jobs',dict(mode='train',version_id='remote-version',size='l'))
            self.assertEqual(code,200,new_job)
            self.assertEqual(new_job['spec']['start_mode'],'scratch')
            self.assertIsNone(new_job['spec']['checkpoint'])
            self.assertEqual(len(self.server.ml.processes),3)
            self.assertEqual(self.req('/api/gpu')[1]['gpus'][0]['utilization'],12)
            self.assertEqual(self.req('/api/jobs/'+train_job['id']+'/cancel',{})[0],200)
            training.terminate.assert_called_once();process.terminate.assert_not_called()
            spec=job['spec'];dataset=Path(spec['dataset'])
            self.assertEqual(len(json.loads((dataset/'valid.json').read_text(encoding='utf-8'))['images']),1)
            self.assertEqual(len(json.loads((dataset/'train.json').read_text(encoding='utf-8'))['images']),0)
            self.assertNotIn('fixture-password-not-real',json.dumps(self.store.backup()))
            self.assertNotIn('fixture-password-not-real',Path(spec['work_dir']).parent.joinpath('spec.json').read_text(encoding='utf-8'))
            Path(spec['result_path']).write_text(json.dumps(dict(metrics={'coco/segm_mAP_50':.75},version_id='remote-version',split='valid')),encoding='utf-8')
            process.poll.return_value=0
            self.server.ml.refresh()
            result=self.store.get('models',model['id'])['evaluations']['remote-version']
            self.assertEqual(result['metrics']['coco/segm_mAP_50'],.75)
            self.assertEqual(self.store.get('jobs',job['id'])['status'],'completed')

    def test_fast_resume_preserves_frozen_spec_and_does_not_restart_from_scratch(self):
        from unittest.mock import Mock
        valid=self.image();valid['split']='valid'
        train=self.image(name='train.png',shade=101);train['split']='train'
        self.store.put('versions',dict(id='resume-version',name='resume-v',images=[valid,train],classes=self.store.all('classes'),counts={'valid':1,'train':1}))
        remote=Mock();process=Mock();process.poll.return_value=None;process.progress_snapshot.return_value={}
        remote.start.return_value=process
        remote.training_checkpoint.return_value=('/srv/cable/cable_rtmdet/studio_rebuild/jobs/old/work/epoch_2.pth',2)
        self.server.ml.remote=remote;self.server.ml.info=dict(ready=True)
        code,original=self.req('/api/jobs',dict(mode='train',version_id='resume-version',epochs=40,batch_size=2))
        self.assertEqual(code,200)
        self.assertEqual(self.req('/api/jobs/'+original['id']+'/resume-fast',{})[0],400)
        self.assertEqual(self.req('/api/jobs/'+original['id']+'/cancel',{})[0],200)
        code,resumed=self.req('/api/jobs/'+original['id']+'/resume-fast',{})
        self.assertEqual(code,200)
        self.assertTrue(resumed['spec']['resume'])
        self.assertEqual(resumed['spec']['resume_epoch'],2)
        self.assertEqual(resumed['spec']['batch_size'],2)
        self.assertEqual(resumed['spec']['dataset'],original['spec']['dataset'])
        self.assertEqual(resumed['spec']['version_id'],'resume-version')
        self.assertEqual(resumed['spec']['lr'],original['spec']['lr'])
        self.assertEqual(self.store.get('jobs',original['id'])['status'],'cancelled')
        self.assertEqual(self.req('/api/jobs/'+original['id']+'/resume-fast',{})[0],400)
        self.server.ml.processes.clear()

    def test_model_trash_restore_preserves_files_and_activation(self):
        model=self.model(); key=model['id']
        self.assertEqual(self.req('/api/models/'+key,dict(active=True))[0],200)
        before={p:Path(model[p]).read_bytes() for p in ('checkpoint','config')}
        code,trashed=self.req('/api/models/'+key,dict(deleted=True))
        self.assertEqual(code,200);self.assertTrue(trashed['deleted']);self.assertFalse(trashed['active']);self.assertTrue(trashed['deleted_at'])
        self.assertEqual(self.req('/api/models/'+key,dict(active=True))[0],400)
        self.assertEqual(self.req('/api/models/'+key+'/download')[0],400)
        self.assertEqual(self.req('/api/models/'+key,dict(name='cannot rename'))[0],400)
        self.assertEqual(self.req('/api/models/'+key,dict(deleted='false'))[0],400)
        self.assertTrue(next(m for m in self.req('/api/state')[1]['models'] if m['id']==key)['deleted'])
        code,restored=self.req('/api/models/'+key,dict(deleted=False))
        self.assertEqual(code,200);self.assertFalse(restored['deleted']);self.assertFalse(restored['active']);self.assertIsNone(restored['deleted_at'])
        self.assertEqual(self.req('/api/models/'+key,dict(active=True))[0],200)
        self.assertEqual(self.req('/api/models/'+key+'/download')[1],before['checkpoint'])
        for p,content in before.items():self.assertEqual(Path(model[p]).read_bytes(),content)

    def test_trashed_models_rejected_by_all_ml_entrypoints(self):
        model=self.model();key=model['id']
        self.req('/api/models/'+key,dict(deleted=True))
        for body in (dict(mode='predict',model_id=key,image_ids=['any']),dict(mode='eval',model_id=key,version_id='any'),dict(mode='train',resume_model=key,version_id='any')):
            code,response=self.req('/api/jobs',body)
            self.assertEqual(code,400,response);self.assertIn('휴지통',response['error'])
        self.assertEqual(self.store.all('jobs'),[])

    def test_model_in_use_cannot_be_trashed(self):
        model=self.model(); key=model['id']
        for spec in (dict(model=dict(id=key)),dict(checkpoint=model['checkpoint'])):
            self.store.put('jobs',dict(id='running-test',status='running',spec=spec))
            code,_=self.req('/api/models/'+key,dict(deleted=True))
            self.assertEqual(code,400);self.assertFalse(self.store.get('models',key).get('deleted',False))
        self.store.put('jobs',dict(id='running-test',status='completed',spec=spec))
        self.assertEqual(self.req('/api/models/'+key,dict(deleted=True))[0],200)

    def test_editor_photo_trash_preserves_annotations_and_version(self):
        image=self.annotate(self.image());self.studio.save_batch(dict(id=image['batch'],stage='done'))
        image=self.studio.update_image(image['id'],dict(revision=image['revision'],split='valid'))
        version=self.studio.create_version({})
        code,trashed=self.req('/api/images/'+image['id'],dict(revision=image['revision'],deleted=True))
        self.assertEqual(code,200);self.assertTrue(trashed['deleted']);self.assertEqual(trashed['annotations'],image['annotations'])
        self.assertTrue(self.studio.media(image['file']).exists())
        self.assertEqual(self.store.get('versions',version['id'])['images'][0]['annotations'],image['annotations'])
        self.assertEqual(self.req('/api/images/'+image['id'],dict(revision=image['revision'],deleted=False))[0],400)
        code,restored=self.req('/api/images/'+image['id'],dict(revision=trashed['revision'],deleted=False))
        self.assertEqual(code,200);self.assertFalse(restored['deleted']);self.assertEqual(restored['annotations'],image['annotations'])

    def test_backup_import_requires_apply_and_checks_every_source(self):
        x=self.image()
        root=Path(self.temp.name);backup=root/'backup.json';dest=root/'imported'
        backup.write_text(json.dumps(self.store.backup()),encoding='utf-8')
        result=import_backup(backup,root/'media',dest)
        self.assertEqual(result['files'],1);self.assertFalse(dest.exists())
        before=self.studio.media(x['file']).read_bytes()
        import_backup(backup,root/'media',dest,apply=True)
        restored=Store(dest/'studio.sqlite')
        self.assertEqual(restored.get('images',x['id'])['height'],2160)
        self.assertEqual((dest/'media'/x['file']).read_bytes(),before)
        self.assertEqual(self.studio.media(x['file']).read_bytes(),before)
        with self.assertRaises(ValueError):import_backup(backup,root/'media',dest,apply=True)
        bad=json.loads(backup.read_text());bad['records']['images'][0]['file']='missing.png'
        backup.write_text(json.dumps(bad),encoding='utf-8')
        with self.assertRaises(FileNotFoundError):import_backup(backup,root/'media',root/'must-not-exist',apply=True)
        self.assertFalse((root/'must-not-exist').exists())


if __name__=='__main__': unittest.main(verbosity=2)
