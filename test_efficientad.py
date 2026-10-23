import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import efficientad_worker as worker
class EfficientADGuardTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent/".verification");self.root=Path(self.tmp.name).resolve();self.patch1=patch.object(worker,'ROOT',self.root);self.patch2=patch.object(worker,'HOME',self.root/'studio_management');self.patch1.start();self.patch2.start()
 def tearDown(self):self.patch1.stop();self.patch2.stop();self.tmp.cleanup()
 def test_paths_reject_escape(self):
  for name in ['../other','/tmp/out','x;y','', 'x/y']:
   with self.assertRaises(ValueError):worker.safe(name)
  with self.assertRaises(ValueError):worker.inside(self.root.parent/'other')
 def test_prepared_data_and_native_models(self):
  p=self.root/'artifacts/native';(p/'training').mkdir(parents=True);(p/'training/model.ckpt').write_bytes(b'checkpoint')
  for name,value in [('config.json',{}),('sources.json',[{'split':'train'},{'split':'calibration'}]),('manifest.json',[{'split':s,'tile':s+'.png'} for s in ['train','calibration','test']]),('preparation.json',{'status':'complete'}),('provenance.json',{})]:worker.write(p/name,value)
  (p/'roi_edge/tiles/train').mkdir(parents=True)
  state=worker.inventory();self.assertTrue(state['models'][0]['trainable']);self.assertEqual(state['datasets'][0]['counts'],{'train':1,'calibration':1})
 def test_dense_models_are_not_native_finetune_targets(self):
  p=self.root/'saved_models/dense';(p/'training').mkdir(parents=True);(p/'training/decoder.pt').write_bytes(b'head');worker.write(p/'config.json',{'method':'dense spatial convolution decoder'})
  model=worker.inventory()['models'][0];self.assertEqual(model['kind'],'dense');self.assertFalse(model['trainable'])
 def test_rename_does_not_move_model_files(self):
  p=self.root/'saved_models/native';p.mkdir(parents=True);(p/'model.ckpt').write_bytes(b'original')
  worker.handle({'action':'rename','id':'native','name':'새 표시 이름'});self.assertEqual((p/'model.ckpt').read_bytes(),b'original');self.assertEqual(worker.inventory()['models'][0]['name'],'새 표시 이름')
 def test_invalid_launch_creates_no_job(self):
  with self.assertRaises(ValueError):worker.handle({'action':'train','name':'trial','dataset':'missing','steps':100})
  self.assertFalse((worker.HOME/'jobs').exists())
if __name__=='__main__':unittest.main()

