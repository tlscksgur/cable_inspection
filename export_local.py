"""Export only frozen network outputs; keep postprocessing explicit and testable."""
import argparse,json,sys,hashlib
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--spec',required=True);a=p.parse_args();s=json.loads(Path(a.spec).read_text())
 sys.path.insert(0,str(Path(__file__).parent/'export_deps'))
 import torch,numpy as np,codecs
 from numpy.core import multiarray
 from mmengine.logging.history_buffer import HistoryBuffer
 torch.serialization.add_safe_globals([HistoryBuffer,getattr,codecs.encode,np.ndarray,np.dtype,multiarray._reconstruct,multiarray.scalar,(multiarray._reconstruct,'numpy._core.multiarray._reconstruct'),(multiarray.scalar,'numpy._core.multiarray.scalar'),*{type(np.dtype(t)) for t in (np.float64,np.float32,np.float16,np.int64,np.int32,np.int16,np.int8,np.uint64,np.uint32,np.uint16,np.uint8,np.bool_)}])
 from mmdet.apis import init_detector
 from worker import portable_config
 torch.set_num_threads(4)
 out=Path(s['out']);out.mkdir(parents=True,exist_ok=True)
 cfg=portable_config(s['config'],s['mmdet_root'],out)
 model=init_detector(cfg,s['checkpoint'],device='cpu');model.eval()
 class Raw(torch.nn.Module):
  def __init__(self):super().__init__();self.model=model
  def forward(self,x):
   c,b,k,m=self.model.bbox_head(self.model.extract_feat(x));return tuple(c)+tuple(b)+tuple(k)+(m,)
 names=[f'{t}{i}' for t in ('cls','box','kernel') for i in range(3)]+['mask']
 net=Raw().eval();x=torch.zeros(1,3,640,1536)
 axes={'image':{2:'height',3:'width'},**{n:{2:n+'_h',3:n+'_w'} for n in names}}
 with torch.no_grad():torch.onnx.export(net,x,str(out/'model.onnx'),input_names=['image'],output_names=names,dynamic_axes=axes,opset_version=17,dynamo=False)
 head=model.bbox_head;dp=model.data_preprocessor
 pipeline=model.cfg.test_dataloader.dataset.pipeline
 scale=next(z['scale'] for z in pipeline if z['type']=='Resize')
 pad=next((z.get('pad_val',{}).get('img',0) for z in pipeline if z['type']=='Pad'),0)
 metadata=dict(classes=s['classes'],scale=list(scale),pad=pad,mean=dp.mean.flatten().tolist(),std=dp.std.flatten().tolist(),bgr_to_rgb=bool(dp._channel_conversion),strides=[int(v[0]) for v in head.prior_generator.strides],offset=head.prior_generator.offset,weight_nums=head.weight_nums,bias_nums=head.bias_nums,prototypes=head.num_prototypes,channels=head.dyconv_channels,test_cfg=dict(head.test_cfg),checkpoint_sha256=hashlib.sha256(Path(s['checkpoint']).read_bytes()).hexdigest())
 (out/'metadata.json').write_text(json.dumps(metadata))
 pad_cfg=next((dict(z) for z in pipeline if z['type']=='Pad'),{})
 metadata.update(format_version=2,pad_size=pad_cfg.get('size'),pad_divisor=pad_cfg.get('size_divisor',32))
 (out/'metadata.json').write_text(json.dumps(metadata))
 print('EXPORTED',flush=True)
if __name__=='__main__':main()
