"""Class alignment must preserve checkpoint labels and validation ground truth."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from ml import ML, align_evaluation_classes
from services import Studio


class EvaluationClassTests(unittest.TestCase):
    def setUp(self):
        self.classes=[dict(id='a',name='dent',normal=False),dict(id='b',name='water',normal=True)]
        self.other=dict(id='c',name='other',normal=True)
        self.model=dict(classes=copy.deepcopy(self.classes),class_ids=['a','b'])
        self.version=dict(id='v',classes=copy.deepcopy(self.classes),images=[
            dict(id='im',split='valid',annotations=[dict(id='ann',class_id='a',points=[[0,0],[10,0],[10,10]])]),
            dict(id='training',split='train',annotations=[dict(class_id='c')])])

    def test_added_unlabelled_normal_with_train_labels_keeps_valid_and_sources(self):
        self.version['classes'].append(self.other)
        before=copy.deepcopy((self.version,self.model))
        aligned,scope=align_evaluation_classes(self.version,self.model)
        self.assertEqual([c['id'] for c in aligned['classes']],['a','b'])
        self.assertEqual([i['id'] for i in aligned['images']],['im'])
        self.assertEqual(aligned['images'][0],self.version['images'][0])
        self.assertEqual(scope['omitted_unlabelled_normal_classes'],['other'])
        self.assertEqual((self.version,self.model),before)

    def test_reordered_categories_use_checkpoint_order_in_coco(self):
        self.model.update(classes=list(reversed(self.classes)),class_ids=['b','a'])
        aligned,_=align_evaluation_classes(self.version,self.model)
        aligned['images'][0].update(file='im.jpg',name='im.jpg',width=100,height=100)
        coco=Studio.coco(None,aligned,'valid')
        self.assertEqual([c['name'] for c in coco['categories']],['water','dent'])
        self.assertEqual(coco['annotations'][0]['category_id'],2)

    def test_new_model_on_old_version_retains_extra_output_slot(self):
        self.model['classes'].append(self.other);self.model['class_ids'].append('c')
        aligned,scope=align_evaluation_classes(self.version,self.model)
        self.assertEqual([c['id'] for c in aligned['classes']],['a','b','c'])
        self.assertEqual(scope['model_only_unlabelled_normal_classes'],['other'])

    def test_missing_annotated_normal_is_rejected(self):
        self.version['classes'].append(self.other)
        self.version['images'][0]['annotations'].append(dict(class_id='c'))
        with self.assertRaisesRegex(ValueError,'other'):align_evaluation_classes(self.version,self.model)

    def test_defect_class_mismatch_rejected_even_without_gt(self):
        self.version['classes'].append(dict(self.other,normal=False))
        with self.assertRaises(ValueError):align_evaluation_classes(self.version,self.model)
        self.version['classes'].pop()
        self.model['classes'].append(dict(self.other,normal=False));self.model['class_ids'].append('c')
        with self.assertRaises(ValueError):align_evaluation_classes(self.version,self.model)

    def test_same_id_different_meaning_or_broken_model_metadata_rejected(self):
        self.model['classes'][0]['name']='scratch'
        with self.assertRaises(ValueError):align_evaluation_classes(self.version,self.model)
        self.model['classes'][0]['name']='dent';self.model['class_ids'].reverse()
        with self.assertRaises(ValueError):align_evaluation_classes(self.version,self.model)

    def test_launch_materializes_aligned_copy_without_altering_version(self):
        self.version['classes'].append(self.other)
        self.version['counts']={'valid':1}
        self.model.update(id='m',name='old',checkpoint='frozen.pth',config='cfg.py')
        studio=MagicMock();studio.store.get.side_effect=lambda kind,key:copy.deepcopy(self.model if kind=='models' else self.version)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'.verification') as folder:
            studio.data=Path(folder)
            ml=ML.__new__(ML);ml.studio=studio;ml.info={'ready':True};ml.root='root';ml.remote=MagicMock()
            ml.worker=Path('worker.py');ml.lock=__import__('threading').RLock();ml.processes={};ml.refresh=lambda:None
            job=ml.launch(dict(mode='eval',model_id='m',version_id='v'))
            materialized=studio.materialize.call_args.args[0]
            self.assertEqual([c['id'] for c in materialized['classes']],['a','b'])
            self.assertEqual(len(materialized['images']),1)
            self.assertEqual(job['spec']['evaluation_scope']['omitted_unlabelled_normal_classes'],['other'])
            self.assertEqual(len(self.version['classes']),3)


if __name__=='__main__':unittest.main()
