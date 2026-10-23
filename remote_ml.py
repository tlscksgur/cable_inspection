"""SSH GPU execution; authentication stays in memory, artifacts stay in own workspace."""
import copy
import csv
import hashlib
import json
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


from server_settings import HOST, USER, ROOT, PYTHON


def command(client, python, code, timeout=60):
    _,stdout,stderr=client.exec_command(shlex.quote(python)+' -c '+shlex.quote(code),timeout=timeout)
    data=stdout.read().decode('utf-8',errors='replace')
    error=stderr.read().decode('utf-8',errors='replace')
    if stdout.channel.recv_exit_status()!=0:
        raise RuntimeError('GPU 서버 명령 실패: '+error[-1600:])
    return data


def parse_gpu_csv(text):
    def numeric(value):
        try:return float(value.strip())
        except ValueError:return None
    result=[]
    for row in csv.reader(text.splitlines()):
        if not row:continue
        if len(row)!=6:raise ValueError('Invalid GPU metrics response')
        index,name,util,used,total,temp=row
        result.append(dict(index=int(index.strip()),name=name.strip(),utilization=numeric(util),
                           memory_used_mib=numeric(used),memory_total_mib=numeric(total),temperature=numeric(temp)))
    return result


class RemoteBackend:
    def __init__(self,password=None):
        deps=Path(__file__).parent/'.runtime'/'python_deps'
        if str(deps) not in sys.path:sys.path.insert(0,str(deps))
        try:import paramiko
        except ImportError:raise RuntimeError('SSH 실행 모듈 Paramiko를 설치하세요') from None
        from ssh_auth import open_client
        self.client=None
        try:
            self.client=open_client(paramiko,password)
        except paramiko.AuthenticationException:
            if self.client:self.client.close()
            raise ValueError('서버 인증에 실패했습니다. SSH 키 등록 또는 비밀번호를 확인하세요.') from None
        except Exception as e:
            if self.client:self.client.close()
            raise RuntimeError('SSH 접속을 확인하세요: '+type(e).__name__) from None
        self.client.get_transport().set_keepalive(20)
        probe="""import json, pathlib, torch, mmdet, mmcv.ops
p=pathlib.Path(mmdet.__file__).resolve()
candidates=[p.parent.parent,p.parent/'.mim',pathlib.Path('/srv/cable/cable_rtmdet/src/mmdetection'),pathlib.Path('/srv/cable/cable_rtmdet/mmdetection')]
root=next((str(x) for x in candidates if (x/'configs/rtmdet/rtmdet-ins_l_8xb32-300e_coco.py').is_file()),None)
print(json.dumps(dict(ready=torch.cuda.is_available() and root is not None,root=root,torch=torch.__version__,gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)))
"""
        try:
            result=json.loads(command(self.client,PYTHON,probe,60).strip().splitlines()[-1])
            if not result['ready']:raise RuntimeError('서버의 CUDA 또는 MMDetection 설정을 확인하세요')
            self.root=result['root'];self.python=PYTHON
            self.info=dict(ready=True,remote=True,host=HOST,gpu=result['gpu'],
                           reason=f'{HOST} · {result["gpu"]} · RTMDet-Ins 연결됨')
        except Exception:
            self.client.close();raise
        self._gpu_lock=threading.Lock();self._gpu_stop=threading.Event()
        self._gpu=dict(available=False,reason='GPU 상태 확인 중',host=HOST)
        threading.Thread(target=self._gpu_loop,daemon=True).start()

    def _gpu_loop(self):
        while not self._gpu_stop.is_set():
            try:
                _,out,err=self.client.exec_command('nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits',timeout=5)
                text=out.read().decode('utf-8');err.read()
                if out.channel.recv_exit_status()!=0:raise RuntimeError('nvidia-smi failed')
                gpus=parse_gpu_csv(text)
                if not gpus:raise RuntimeError('No GPU metrics')
                with self._gpu_lock:
                    self._gpu=dict(available=True,host=HOST,gpus=gpus,stale=False,
                                   updated=datetime.now(timezone.utc).isoformat())
            except Exception:
                with self._gpu_lock:self._gpu={**self._gpu,'stale':True,'reason':'GPU 상태를 갱신하지 못했습니다'}
            self._gpu_stop.wait(5)

    def gpu_info(self):
        with self._gpu_lock:return copy.deepcopy(self._gpu)

    def close(self):
        self._gpu_stop.set();self.client.close()

    def training_checkpoint(self,key):
        if not re.fullmatch(r'[0-9a-f]{16}',key):raise ValueError('잘못된 작업 ID')
        work=ROOT+'/jobs/'+key+'/work'
        with self.client.open_sftp() as sftp:
            if sftp.normalize(work)!=work:raise ValueError('체크포인트 경로를 확인하세요')
            candidates=[]
            for entry in sftp.listdir_attr(work):
                match=re.fullmatch(r'epoch_(\d+)\.pth',entry.filename)
                if match and entry.st_size>0:candidates.append((int(match[1]),entry.filename))
            if not candidates:raise ValueError('재개할 epoch 체크포인트가 없습니다')
            epoch,name=max(candidates);path=work+'/'+name
            if sftp.normalize(path)!=path:raise ValueError('체크포인트 심볼릭 링크는 허용하지 않습니다')
            return path,epoch

    def start(self,spec,worker,folder):
        return RemoteProcess(self,spec,worker,folder)


class RemoteProcess:
    def __init__(self,backend,spec,worker,folder):
        self.backend=backend;self.spec=copy.deepcopy(spec);self.worker=Path(worker)
        self.folder=Path(folder);self.remote=ROOT+'/jobs/'+self.folder.name
        self.code=None;self.channel=None;self.cancelled=threading.Event()
        self.status_lock=threading.Lock();self.latest_status={}
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def status(self,**data):
        # Progress is authoritative in memory. A Windows reader/antivirus may hold
        # status.json without delete-sharing; that must never abort a GPU job.
        with self.status_lock:self.latest_status=copy.deepcopy(data)
        path=self.folder/'status.json'
        temp=self.folder/('status.'+uuid.uuid4().hex+'.tmp')
        try:
            temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
            for attempt in range(3):
                try:temp.replace(path);break
                except PermissionError:
                    if attempt<2:time.sleep(.01*(attempt+1))
        except OSError:pass
        finally:
            try:temp.unlink(missing_ok=True)
            except OSError:pass

    def progress_snapshot(self):
        with self.status_lock:return copy.deepcopy(self.latest_status)

    def mkdir(self,sftp,path):
        p=PurePosixPath(path)
        if not p.is_relative_to(PurePosixPath(ROOT)):raise ValueError('Remote workspace escape')
        try:sftp.stat(path)
        except OSError:
            if path!=ROOT:self.mkdir(sftp,str(p.parent))
            try:sftp.mkdir(path)
            except OSError:sftp.stat(path)  # Another job may have created it.
        if sftp.normalize(path)!=path:raise ValueError('Remote workspace contains a symlink')

    def run(self):
        client=self.backend.client
        try:
            with client.open_sftp() as sftp:
                self.mkdir(sftp,self.remote);self.mkdir(sftp,ROOT+'/artifacts')
                transfers={};manifest={}
                def artifact(local):
                    local=Path(local).resolve()
                    with local.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
                    target=ROOT+'/artifacts/'+sha+local.suffix
                    transfers[target]=local;return target
                remote_spec=copy.deepcopy(self.spec)
                remote_spec.update(mmdet_root=self.backend.root,work_dir=self.remote+'/work',
                    status_path=self.remote+'/status.json',result_path=self.remote+'/result.json')
                if self.spec.get('resume'):
                    checkpoint,epoch=self.backend.training_checkpoint(self.spec['origin_job'])
                    if epoch!=self.spec['resume_epoch']:raise ValueError('재개 체크포인트가 바뀌었습니다')
                    remote_spec['checkpoint']=checkpoint
                elif self.spec.get('checkpoint'):
                    remote_spec['checkpoint']=artifact(self.spec['checkpoint'])
                if 'config' in self.spec:remote_spec['config']=artifact(self.spec['config'])
                if 'dataset' in self.spec:
                    dataset=Path(self.spec['dataset']);remote_spec['dataset']=self.remote+'/dataset'
                    for file in dataset.rglob('*'):
                        if file.is_file():manifest[str(file.relative_to(dataset)).replace('\\','/')]=artifact(file)
                for image in remote_spec.get('images',[]):image['path']=artifact(image['path'])
                total=sum(f.stat().st_size for f in transfers.values());done=0;last=[0]
                for index,(target,local) in enumerate(transfers.items()):
                    if self.cancelled.is_set():self.code=-15;return
                    size=local.stat().st_size
                    try:exists=sftp.stat(target).st_size==size
                    except OSError:exists=False
                    if not exists:
                        def progress(sent,_):
                            if self.cancelled.is_set():raise RuntimeError('작업을 중단했습니다')
                            if time.monotonic()-last[0]>1:
                                self.status(message=f'GPU 서버로 전송 중 · {index+1}/{len(transfers)}개 · {(done+sent)//1048576}/{total//1048576} MB',progress=0)
                                last[0]=time.monotonic()
                        partial=target+'.'+self.folder.name+'.part'
                        sftp.put(str(local),partial,callback=progress)
                        try:sftp.rename(partial,target)
                        except OSError:
                            if sftp.stat(target).st_size!=size:raise
                            sftp.remove(partial)  # Another job published the same hash.
                    done+=size
                self.status(message='서버 파일 무결성 확인 중',progress=0)
                checks={target:Path(target).stem for target in transfers}
                with sftp.open(self.remote+'/checks.json','w') as f:f.write(json.dumps(checks))
                verify="import json,hashlib; from pathlib import Path; d=json.loads(Path("+repr(self.remote+'/checks.json')+").read_text()); bad=[p for p,h in d.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]; print(json.dumps(bad))"
                if json.loads(command(client,self.backend.python,verify,300).strip()):raise RuntimeError('서버 전송 파일 해시 불일치')
                if manifest:
                    self.mkdir(sftp,self.remote+'/dataset')
                    for relative,target in manifest.items():
                        path=self.remote+'/dataset/'+relative;self.mkdir(sftp,str(PurePosixPath(path).parent));sftp.symlink(target,path)
                sftp.put(str(self.worker),self.remote+'/worker.py')
                with sftp.open(self.remote+'/spec.json','w') as f:f.write(json.dumps(remote_spec,ensure_ascii=False))
                if self.cancelled.is_set():self.code=-15;return
                self.channel=client.get_transport().open_session()
                self.channel.exec_command('exec env PYTHONUNBUFFERED=1 '+shlex.quote(self.backend.python)+' '+shlex.quote(self.remote+'/worker.py')+' --spec '+shlex.quote(self.remote+'/spec.json'))
                self.status(message='GPU 작업 실행 중',progress=0)
                with (self.folder/'worker.log').open('ab') as log:
                    while not self.channel.exit_status_ready():
                        self.drain(log)
                        try:
                            with sftp.open(self.remote+'/status.json') as f:status=json.loads(f.read())
                            self.status(**status)
                        except OSError:pass
                        time.sleep(1)
                    self.drain(log)
                    code=self.channel.recv_exit_status()
                if code==0:
                    with sftp.open(self.remote+'/result.json') as f:result=json.loads(f.read())
                    if self.spec['mode']=='train':
                        for field in ('checkpoint','config'):
                            remote_file=PurePosixPath(result[field])
                            if not remote_file.is_relative_to(PurePosixPath(self.remote)):raise RuntimeError('Unexpected result path')
                            local=self.folder/remote_file.name;sftp.get(str(remote_file),str(local));result[field]=str(local.resolve())
                    (self.folder/'result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
                self.code=code
        except Exception as e:
            with (self.folder/'worker.log').open('a',encoding='utf-8') as log:log.write('\n'+str(e)+'\n')
            self.code=-1

    def drain(self,log):
        while self.channel.recv_ready():log.write(self.channel.recv(65536))
        while self.channel.recv_stderr_ready():log.write(self.channel.recv_stderr(65536))
        log.flush()

    def poll(self):return self.code

    def terminate(self):
        self.cancelled.set()
        if self.channel is not None and not self.channel.exit_status_ready():
            # Only signal a PID whose command line includes this app's exact job spec.
            code="import json,os,signal;from pathlib import Path;p=Path("+repr(self.remote+'/pid.json')+");d=json.loads(p.read_text());pid=d['pid'];cmd=Path('/proc/'+str(pid)+'/cmdline').read_bytes();assert "+repr((self.remote+'/spec.json').encode())+" in cmd.split(bytes([0]));os.kill(pid,signal.SIGTERM)"
            command(self.backend.client,self.backend.python,code,15)

    def kill(self):self.terminate()

    def wait(self,timeout=None):
        self.thread.join(timeout)
        if self.thread.is_alive():raise subprocess.TimeoutExpired('remote GPU job',timeout)
        return self.code
