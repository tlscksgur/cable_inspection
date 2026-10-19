"""Bounded, exact mask encoding benchmark on the configured CUDA environment."""
import json,time
import numpy as np
import torch
from pycocotools import mask as mu
from mmdet.structures.mask import encode_mask_results
from worker import encode_cuda_masks

def main():
    torch.manual_seed(42)
    results=[]
    for n,h,w in [(3,31,47),(20,1080,4096),(100,2160,4096)]:
        # Disconnected shapes and edge pixels, all-zero/all-one masks included.
        x=torch.zeros((n,h,w),dtype=torch.bool,device='cuda')
        x[1]=True;x[2:,h//5:h//2,w//6:w//2]=True
        x[2:,::31,::47]=True
        timings={};outputs={}
        for name,fn in [('old',lambda:encode_mask_results(x.cpu().numpy())),('fast',lambda:encode_cuda_masks(x))]:
            torch.cuda.synchronize();start=time.perf_counter()
            outputs[name]=fn();torch.cuda.synchronize();timings[name]=time.perf_counter()-start
        assert all(a['counts']==b['counts'] and a['size']==b['size'] for a,b in zip(outputs['old'],outputs['fast']))
        results.append(dict(shape=[n,h,w],seconds=timings,speedup=timings['old']/timings['fast'],exact_rle=True))
        del x
    print(json.dumps(results),flush=True)

if __name__=='__main__':main()
