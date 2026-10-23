import copy
import unittest
from ml import finetune_class_transfer
from worker import remap_classification_state


class Tensor:
    """Small tensor substitute; real checkpoint verification also runs on GPU server."""
    def __init__(self,values,shape):self.values=copy.deepcopy(values);self.shape=shape
    def clone(self):return Tensor(self.values,self.shape)
    def __getitem__(self,i):return self.values[i]
    def __setitem__(self,i,v):self.values[i]=copy.deepcopy(v)


class FinetuneClassTests(unittest.TestCase):
    def setUp(self):
        self.old=[dict(id='1',name='dent',normal=False),dict(id='2',name='water',normal=True)]
        self.other=dict(id='3',name='other',normal=True)
        self.model=dict(id='best',name='v26',size='l',classes=self.old,class_ids=['1','2'])
        self.version=dict(classes=self.old+[self.other],images=[dict(split='train',annotations=[dict(class_id='3')])])

    def test_added_normal_class_is_supported_and_recorded(self):
        plan=finetune_class_transfer(self.version,self.model,'l')
        self.assertEqual(plan['added_classes'],['other'])
        self.assertEqual(plan['source_model_id'],'best')

    def test_same_class_finetuning_stays_unchanged(self):
        self.version['classes']=self.old
        self.assertIsNone(finetune_class_transfer(self.version,self.model,'l'))

    def test_size_removal_meaning_and_unlabelled_additions_blocked(self):
        with self.assertRaisesRegex(ValueError,'크기'):finetune_class_transfer(self.version,self.model,'s')
        self.version['images'][0]['annotations']=[]
        with self.assertRaisesRegex(ValueError,'train 라벨'):finetune_class_transfer(self.version,self.model,'l')
        self.version['classes']=[self.other]
        with self.assertRaisesRegex(ValueError,'삭제'):finetune_class_transfer(self.version,self.model,'l')
        self.version['classes']=copy.deepcopy(self.old);self.version['classes'][0]['normal']=True
        with self.assertRaisesRegex(ValueError,'구분'):finetune_class_transfer(self.version,self.model,'l')

    def tensors(self):
        source={'backbone.weight':Tensor([11,22],(2,)),
                'bbox_head.rtm_cls.0.weight':Tensor([[10,11],[20,21]],(2,2)),
                'bbox_head.rtm_cls.0.bias':Tensor([1,2],(2,)),
                'bbox_head.rtm_reg.0.weight':Tensor([33],(1,))}
        target={'backbone.weight':Tensor([-1,-1],(2,)),
                'bbox_head.rtm_cls.0.weight':Tensor([[90,91],[92,93],[94,95]],(3,2)),
                'bbox_head.rtm_cls.0.bias':Tensor([-4.59,-4.59,-4.59],(3,)),
                'bbox_head.rtm_reg.0.weight':Tensor([-3],(1,))}
        return source,target

    def test_old_rows_and_shared_weights_preserved_new_row_initialization_retained(self):
        source,target=self.tensors();fresh=copy.deepcopy(target)
        state,report=remap_classification_state(source,target,self.old,self.old+[self.other])
        self.assertIs(state['backbone.weight'],source['backbone.weight'])
        self.assertIs(state['bbox_head.rtm_reg.0.weight'],source['bbox_head.rtm_reg.0.weight'])
        self.assertEqual(state['bbox_head.rtm_cls.0.weight'].values,[[10,11],[20,21],[94,95]])
        self.assertEqual(state['bbox_head.rtm_cls.0.bias'].values,[1,2,-4.59])
        self.assertEqual(target['bbox_head.rtm_cls.0.weight'].values,fresh['bbox_head.rtm_cls.0.weight'].values)
        self.assertEqual(report['initialized_classes'],['other'])

    def test_reordered_classes_copy_by_id_not_position(self):
        source,target=self.tensors()
        state,_=remap_classification_state(source,target,self.old,[self.old[1],self.other,self.old[0]])
        self.assertEqual(state['bbox_head.rtm_cls.0.bias'].values,[2,-4.59,1])
        self.assertEqual(state['bbox_head.rtm_cls.0.weight'].values,[[20,21],[92,93],[10,11]])

    def test_unrelated_shape_or_structure_change_rejected(self):
        source,target=self.tensors();target['backbone.weight'].shape=(3,)
        with self.assertRaisesRegex(ValueError,'클래스 출력 외'):remap_classification_state(source,target,self.old,self.old+[self.other])
        target.pop('backbone.weight')
        with self.assertRaisesRegex(ValueError,'모델 구조'):remap_classification_state(source,target,self.old,self.old+[self.other])


if __name__=='__main__':unittest.main()
