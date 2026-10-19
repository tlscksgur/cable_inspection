import json,sys,time
from pathlib import Path
import torch,numpy as np,codecs
from numpy.core import multiarray
from mmengine.logging.history_buffer import HistoryBuffer
torch.serialization.add_safe_globals([HistoryBuffer,getattr,codecs.encode,np.ndarray,np.dtype,multiarray._reconstruct,multiarray.scalar,(multiarray._reconstruct,'numpy._core.multiarray._reconstruct'),(multiarray.scalar,'numpy._core.multiarray.scalar'),*{type(np.dtype(t)) for t in (np.float64,np.float32,np.float16,np.int64,np.int32,np.int16,np.int8,np.uint64,np.uint32,np.uint16,np.uint8,np.bool_)}])
from mmdet.apis import init_detector,inference_detector
from worker import portable_config
import cv2
s=json.loads(Path(sys.argv[1]).read_text());out=Path(s['out']);out.mkdir(parents=True,exist_ok=True)
torch.set_num_threads(4);torch.cuda.set_per_process_memory_fraction(.15)
t=time.perf_counter();model=init_detector(portable_config(s['config'],s['mmdet_root'],out),s['checkpoint'],device='cuda:0');load=time.perf_counter()-t
results=[]
with torch.inference_mode():
 for path in s['images']:
  t=time.perf_counter();image=cv2.imread(path);p=inference_detector(model,image).pred_instances.cpu();anns=[]
  for i,score in enumerate(p.scores):
   if float(score)<s['threshold']:continue
   cs,_=cv2.findContours(p.masks[i].numpy().astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
   polygons=[cv2.approxPolyDP(c,1.,True)[:,0,:].tolist() for c in cs if len(c)>=3 and cv2.contourArea(c)>=1]
   anns.append(dict(class_id=s['classes'][int(p.labels[i])]['id'],score=float(score),box=p.bboxes[i].tolist(),polygons=polygons))
  results.append(dict(width=image.shape[1],height=image.shape[0],annotations=anns,seconds=time.perf_counter()-t,device='회사 AI 서버 · NVIDIA CUDA'))
(out/'result.json').write_text(json.dumps(dict(results=results,load_seconds=load)))
