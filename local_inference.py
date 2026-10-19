"""RTMDet-Ins ONNX CPU inference with explicit same-resolution mask decoding."""
import json,time
from pathlib import Path

class LocalModel:
 def __init__(self,folder):
  import onnxruntime as ort
  self.meta=json.loads((Path(folder)/'metadata.json').read_text())
  opts=ort.SessionOptions();opts.intra_op_num_threads=4;opts.inter_op_num_threads=1
  self.session=ort.InferenceSession(str(Path(folder)/'model.onnx'),opts,providers=['CPUExecutionProvider'])

 def predict(self,path,threshold=.4):
  import numpy as np,cv2
  start=time.perf_counter();im=cv2.imdecode(np.fromfile(str(path),dtype=np.uint8),cv2.IMREAD_COLOR)
  if im is None:raise ValueError('이미지 파일을 읽을 수 없습니다')
  oh,ow=im.shape[:2];m=self.meta;tw,th=m['scale'];ratio=min(max(tw,th)/max(ow,oh),min(tw,th)/min(ow,oh))
  w,h=int(ow*ratio+.5),int(oh*ratio+.5);image=cv2.resize(im,(w,h))
  pad=m.get('pad',114);pad=(pad,pad,pad) if isinstance(pad,(float,int)) else pad
  divisor=m.get('pad_divisor') or 32;pw,ph=m.get('pad_size') or ((w+divisor-1)//divisor*divisor,(h+divisor-1)//divisor*divisor)
  image=cv2.copyMakeBorder(image,0,ph-h,0,pw-w,cv2.BORDER_CONSTANT,value=pad)
  if m['bgr_to_rgb']:image=image[:,:,::-1]
  image=(image.astype(np.float32)-np.array(m['mean'],np.float32))/np.array(m['std'],np.float32)
  x=image.transpose(2,0,1)[None].copy()
  raw=self.session.run(None,{'image':x});candidates=[];cfg=m['test_cfg']
  for i,stride in enumerate(m['strides']):
   c,b,k=raw[i][0],raw[i+3][0],raw[i+6][0];hh,ww=c.shape[1:];scores=1/(1+np.exp(-np.clip(c.transpose(1,2,0).reshape(-1,c.shape[0]),-80,80)))
   rows,labels=np.where(scores>cfg['score_thr']);values=scores[rows,labels]
   order=np.argsort(-values,kind='stable')[:cfg['nms_pre']];rows,labels,values=rows[order],labels[order],values[order]
   if not len(rows):continue
   priors=np.stack(((rows%ww+m['offset'])*stride,(rows//ww+m['offset'])*stride),1).astype(np.float32)
   d=b.transpose(1,2,0).reshape(-1,4)[rows];boxes=np.concatenate((priors-d[:,:2],priors+d[:,2:]),1);boxes[:,[0,2]]=boxes[:,[0,2]].clip(0,pw);boxes[:,[1,3]]=boxes[:,[1,3]].clip(0,ph)
   kernels=k.transpose(1,2,0).reshape(-1,k.shape[0])[rows]
   candidates.extend((float(v),int(l),box,ker,pt,float(stride)) for v,l,box,ker,pt in zip(values,labels,boxes,kernels,priors))
  candidates.sort(key=lambda c:-c[0]);kept=[]
  for c in candidates:
   if len(kept)>=cfg['max_per_img']:break
   overlap=False
   for d in kept:
    if c[1]!=d[1]:continue
    lo=np.maximum(c[2][:2],d[2][:2]);hi=np.minimum(c[2][2:],d[2][2:]);inter=np.prod(np.maximum(hi-lo,0));area=lambda b:np.prod(np.maximum(b[2:]-b[:2],0))
    if inter/max(float(area(c[2])+area(d[2])-inter),1e-8)>cfg['nms']['iou_threshold']:overlap=True;break
   if not overlap:kept.append(c)
  annotations=[];feat=raw[9][0];mh,mw=feat.shape[1:];yy,xx=np.mgrid[:mh,:mw];coord=np.stack(((xx+m['offset'])*m['strides'][0],(yy+m['offset'])*m['strides'][0])).astype(np.float32)
  for score,label,box,kernel,pt,stride in kept:
   if score<threshold:continue
   relative=(pt[:,None,None]-coord)/(stride*8);z=np.concatenate((relative,feat)).reshape(m['prototypes']+2,-1)
   offset=0;weights=[];biases=[]
   for n in m['weight_nums']:weights.append(kernel[offset:offset+n]);offset+=n
   for n in m['bias_nums']:biases.append(kernel[offset:offset+n]);offset+=n
   for j,(weight,bias) in enumerate(zip(weights,biases)):
    z=weight.reshape(len(bias),-1)@z+bias[:,None]
    if j<len(weights)-1:z=np.maximum(z,0)
   # Preserve both bilinear resizes used by the original head.
   logits=cv2.resize(z.reshape(mh,mw),(mw*m['strides'][0],mh*m['strides'][0]),interpolation=cv2.INTER_LINEAR)
   logits=cv2.resize(logits,(int(np.ceil(logits.shape[1]*ow/w)),int(np.ceil(logits.shape[0]*oh/h))),interpolation=cv2.INTER_LINEAR)[:oh,:ow]
   binary=(logits>np.log(cfg['mask_thr_binary']/(1-cfg['mask_thr_binary']))).astype('uint8')
   contours,_=cv2.findContours(binary,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
   polygons=[cv2.approxPolyDP(c,1.,True)[:,0,:].tolist() for c in contours if len(c)>=3 and cv2.contourArea(c)>=1]
   annotations.append(dict(class_id=m['classes'][label]['id'],score=score,box=(box/np.array([w/ow,h/oh,w/ow,h/oh])).tolist(),polygons=polygons))
  return dict(width=ow,height=oh,annotations=annotations,seconds=time.perf_counter()-start,device='내 PC · CPU',provider=self.session.get_providers())
