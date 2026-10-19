"""Paced single-GPU RTMDet-Ins inference test. Run on the actual factory PC."""
import argparse,csv,hashlib,json,math,subprocess,threading,time
from pathlib import Path


def percentile(values,q):
    if not values:return None
    a=sorted(values);p=(len(a)-1)*q;lo=math.floor(p);hi=math.ceil(p)
    return a[lo]+(a[hi]-a[lo])*(p-lo)


def gpu_sample(index):
    flags=subprocess.CREATE_NO_WINDOW if __import__('os').name=='nt' else 0
    text=subprocess.check_output(['nvidia-smi','-i',str(index),'--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu','--format=csv,noheader,nounits'],text=True,timeout=3,creationflags=flags)
    row=next(csv.reader(text.splitlines()))
    def number(v):
        try:return float(v)
        except ValueError:return None
    return dict(name=row[0].strip(),utilization=number(row[1]),memory_mib=number(row[2]),total_memory_mib=number(row[3]),temperature=number(row[4]))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True);p.add_argument('--checkpoint',required=True)
    p.add_argument('--images',required=True);p.add_argument('--rate',type=float,default=.2,help='Total images/sec; default one image every 5 seconds')
    p.add_argument('--seconds',type=float,default=600);p.add_argument('--gpu',type=int,default=0)
    p.add_argument('--max-speed',action='store_true',help='Run continuously to measure maximum throughput; may use the whole GPU')
    p.add_argument('--output',default='factory_benchmark_result.json');a=p.parse_args()
    if a.rate<=0 or a.seconds<=0:p.error('rate and seconds must be positive')
    dest=Path(a.output)
    if dest.exists():raise FileExistsError('Choose a new output filename')
    files=sorted(x for x in Path(a.images).rglob('*') if x.suffix.lower() in {'.jpg','.jpeg','.png','.bmp','.tif','.tiff'} and x.is_file())
    if not files:raise ValueError('No test images')
    import torch,cv2
    if not torch.cuda.is_available():raise RuntimeError('This test requires the NVIDIA CUDA factory environment; AMD/CPU results do not validate RTX 3060 capacity.')
    # Share trusted MMEngine checkpoint metadata handling with the studio worker.
    import worker
    from mmdet.apis import init_detector,inference_detector
    from mmengine.logging.history_buffer import HistoryBuffer
    import numpy as np,codecs
    from numpy.core import multiarray
    torch.serialization.add_safe_globals([HistoryBuffer,getattr,codecs.encode,np.ndarray,np.dtype,multiarray._reconstruct,multiarray.scalar,
        (multiarray._reconstruct,'numpy._core.multiarray._reconstruct'),(multiarray.scalar,'numpy._core.multiarray.scalar'),
        *{type(np.dtype(t)) for t in (np.float64,np.float32,np.float16,np.int64,np.int32,np.int16,np.int8,np.uint64,np.uint32,np.uint16,np.uint8,np.bool_)}])
    torch.cuda.set_device(a.gpu);torch.set_num_threads(4)
    # Config must be a complete/portable exported config with unchanged resize settings.
    model=init_detector(a.config,a.checkpoint,device=f'cuda:{a.gpu}')
    def predict(path):
        image=cv2.imread(str(path))
        if image is None:raise ValueError(f'Cannot decode {path}')
        instances=inference_detector(model,image).pred_instances.cpu()
        if hasattr(instances,'masks'):
            for j,score in enumerate(instances.scores):
                if float(score)>=.4:
                    cv2.findContours(instances.masks[j].numpy().astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        torch.cuda.synchronize()
    with torch.inference_mode():
        for i in range(10):predict(files[i%len(files)])
    telemetry=[];stop=threading.Event();errors=[]
    def monitor():
        while not stop.is_set():
            try:telemetry.append(dict(seconds=time.perf_counter()-start,**gpu_sample(a.gpu)))
            except Exception as e:errors.append(type(e).__name__)
            stop.wait(.5)
    latency=[];missed=0;start=time.perf_counter();thread=threading.Thread(target=monitor,daemon=True);thread.start()
    try:
        slot=0
        with torch.inference_mode():
            while (time.perf_counter()-start<a.seconds if a.max_speed else slot/a.rate<a.seconds):
                due=time.perf_counter() if a.max_speed else start+slot/a.rate;now=time.perf_counter()
                if now<due:time.sleep(due-now)
                t=time.perf_counter();predict(files[len(latency)%len(files)]);latency.append(time.perf_counter()-t);slot+=1
                # Skip arrivals that could not be handled, rather than hiding a growing queue.
                next_slot=slot if a.max_speed else min(math.ceil(a.seconds*a.rate),math.ceil((time.perf_counter()-start)*a.rate))
                if next_slot>slot:missed+=next_slot-slot;slot=next_slot
    finally:stop.set();thread.join(timeout=4)
    elapsed=time.perf_counter()-start
    util=[x['utilization'] for x in telemetry if x['utilization'] is not None]
    memory_percent=[100*x['memory_mib']/x['total_memory_mib'] for x in telemetry if x['memory_mib'] is not None and x['total_memory_mib']]
    result=dict(gpu=torch.cuda.get_device_name(a.gpu),torch=torch.__version__,config=a.config,checkpoint=a.checkpoint,
        checkpoint_sha256=hashlib.sha256(Path(a.checkpoint).read_bytes()).hexdigest(),images=len(files),target_fps=None if a.max_speed else a.rate,
        seconds=elapsed,processed=len(latency),achieved_fps=len(latency)/elapsed,missed_arrivals=missed,
        latency_ms=dict(p50=percentile(latency,.5)*1000,p95=percentile(latency,.95)*1000,p99=percentile(latency,.99)*1000,max=max(latency)*1000),
        gpu_total_sampled=dict(mean=sum(util)/len(util) if util else None,max=max(util) if util else None,samples=len(util)),
        vram_total_sampled=dict(max_percent=max(memory_percent) if memory_percent else None),
        sampled_budget_check=dict(compute_below_50=bool(util) and max(util)<50,memory_below_50=bool(memory_percent) and max(memory_percent)<50,
            no_missed_arrivals=None if a.max_speed else missed==0,all_images_within_interval=None if a.max_speed else max(latency)<1/a.rate,
            sufficient_monitoring=len(util)>=max(3,a.seconds) and not errors),
        telemetry=telemetry,telemetry_errors=errors,measurement='Decode + preprocessing + FP32 inference + CPU masks + contours; excludes camera capture, disk writes, network, GUI and PLC.',
        caveat='GPU utilization covers the entire GPU and is sampled, not an instantaneous/per-process cap. Validate on factory PC with normal concurrent applications.')
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='telemetry'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
