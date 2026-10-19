import json
import tempfile
import unittest
from pathlib import Path

from import_models import run
from store import Store, DEFAULT_CLASSES
from worker import portable_config


class ModelImportTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent/'.verification'
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.root = Path(self.temp.name)
        self.source = self.root/'source'
        self.folder = self.source/'rtmins_example'
        self.folder.mkdir(parents=True)
        self.data = self.root/'data'
        self.data.mkdir()
        self.store = Store(self.data/'studio.sqlite')
        classes = [n for n, _ in DEFAULT_CLASSES]
        (self.folder/'model.pth').write_bytes(b'PKfixture-checkpoint-never-unpickled')
        self.config = "_base_ = ['/opt/mmdetection/configs/rtmdet/rtmdet-ins_l_8xb32-300e_coco.py']\nclasses = "+repr(tuple(classes))+"\n"
        (self.folder/'config.py').write_text(self.config, encoding='utf-8')
        (self.folder/'model_info.json').write_text(json.dumps(dict(arch='rtmdet_ins', classes=classes,
            trained_on=27, evals={'27':dict(segm50=.654, segm5095=.362)})), encoding='utf-8')
        (self.folder/'train_info.json').write_text(json.dumps(dict(name='example', size='l', finished=1,
            version=27)), encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_dry_run_leaves_files_and_database_untouched(self):
        before = (self.data/'studio.sqlite').read_bytes()
        self.assertFalse(run(self.source, self.data, ['studio.sqlite'])['applied'])
        self.assertEqual(before, (self.data/'studio.sqlite').read_bytes())
        self.assertFalse((self.data/'models').exists())

    def test_import_preserves_original_and_repeat_preserves_user_state(self):
        run(self.source, self.data, ['studio.sqlite'], True)
        model = self.store.all('models')[0]
        self.assertEqual(Path(model['config']).read_text(encoding='utf-8'), self.config)
        self.assertEqual(model['version_name'], 'v27')
        self.assertEqual(model['metrics']['best_mask_mAP50'], .654)
        model.update(name='renamed', deleted=True, active=False)
        self.store.put('models', model)
        result = run(self.source, self.data, ['studio.sqlite'], True)
        self.assertEqual(result['registered']['studio.sqlite'], 0)
        self.assertEqual(self.store.all('models')[0]['name'], 'renamed')
        self.assertTrue(self.store.all('models')[0]['deleted'])

    def test_conflicting_destination_rejected_before_database_changes(self):
        run(self.source, self.data, ['studio.sqlite'], True)
        model = self.store.all('models')[0]
        Path(model['config']).write_text('conflict', encoding='utf-8')
        before = self.store.backup()
        with self.assertRaisesRegex(ValueError, 'Destination conflict'):
            run(self.source, self.data, ['studio.sqlite'], True)
        self.assertEqual(before, self.store.backup())

    def test_runtime_base_path_is_resolved_without_editing_original(self):
        base = self.root/'mmdet'/'configs'/'rtmdet'/'rtmdet-ins_l_8xb32-300e_coco.py'
        base.parent.mkdir(parents=True)
        base.write_text('# fixture', encoding='utf-8')
        work = self.root/'work'
        work.mkdir()
        runtime = portable_config(self.folder/'config.py', self.root/'mmdet', work)
        self.assertIn(str(base.resolve()).replace('\\', '\\\\'), Path(runtime).read_text(encoding='utf-8'))
        self.assertEqual((self.folder/'config.py').read_text(encoding='utf-8'), self.config)
        with self.assertRaisesRegex(ValueError, 'missing'):
            portable_config(self.folder/'config.py', self.root/'missing', work)


if __name__ == '__main__':
    unittest.main()
