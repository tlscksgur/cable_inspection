"""Bridge to the EfficientAD workspace using Studio's session-only SSH client."""
import json,shlex,threading,time,http.client,io,re
from pathlib import Path
ROOT='/srv/cable/cable_efficientad'
PYTHON='/srv/cable/miniconda3/envs/anomaly/bin/python'
class ChannelReader(io.RawIOBase):
 def __init__(self,c):super().__init__();self.c=c
 def readable(self):return True
 def readinto(self,b):
  raw=self.c.recv(len(b));b[:len(raw)]=raw;return len(raw)
class ChannelSocket:
 def __init__(self,c):self.c=c
 def sendall(self,b):self.c.sendall(b)
 def makefile(self,mode):return io.BufferedReader(ChannelReader(self.c))
 def close(self):pass

class EfficientAD:
 def __init__(self,ml):self.ml=ml;self.lock=threading.Lock();self.client=None;self.cached=None;self.cached_at=0
 def inspection(self,path,body=None,token=''):
  remote=self.ml.remote
  if remote is None or not remote.client.get_transport() or not remote.client.get_transport().is_active():raise RuntimeError('설정에서 AI 서버에 먼저 연결하세요')
  prefix='/efficientad-test';target=path[len(prefix):].split('?')[0] or '/'
  if target=='/script.js':
   if not getattr(self,'inspection_script',None):self.inspection(prefix+'/')
   return 200,'text/javascript; charset=utf-8',self.inspection_script
  allowed=target in ['/','/health','/api/inspect'] or re.fullmatch(r'/jobs/[a-f0-9]{32}/(?:status.json|results.json|(?:bestModel_ver[12]|water|base|dense)_\d+/(?:original.jpg|heatmap.jpg|marked.jpg|result.json))',target)
  if not allowed:raise ValueError('검사 경로가 올바르지 않습니다')
  transport=remote.client.get_transport()
  try:channel=transport.open_channel('direct-tcpip',('127.0.0.1',8768),('127.0.0.1',0),timeout=10)
  except Exception:
   code="import pathlib,subprocess,sys; r=pathlib.Path('/srv/cable/cable_efficientad'); log=(r/'logs/presentation_gui_8768.log').open('a'); subprocess.Popen([sys.executable,'-u','-m','efficientad_compare.gui_server','--port','8768'],cwd=r,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)"
   _,out,err=remote.client.exec_command(shlex.quote(PYTHON)+' -c '+shlex.quote(code));out.channel.recv_exit_status()
   channel=None
   for _ in range(15):
    try:channel=transport.open_channel('direct-tcpip',('127.0.0.1',8768),('127.0.0.1',0),timeout=3);break
    except Exception:time.sleep(.3)
   if channel is None:raise RuntimeError('EfficientAD 검사 서버를 시작하지 못했습니다')
  channel.settimeout(60);connection=http.client.HTTPConnection('127.0.0.1',8768,timeout=60);connection.sock=ChannelSocket(channel)
  try:
   raw=json.dumps(body).encode('utf8') if body is not None else None
   headers={'Content-Type':'application/json','X-GUI-Token':token} if raw else {}
   connection.request('POST' if raw else 'GET',target,body=raw,headers=headers);response=connection.getresponse();data=response.read();mime=response.getheader('Content-Type','application/json');status=response.status
   if target=='/' and status==200:
    page=data.decode('utf8').replace("fetch('/","fetch('/efficientad-test/").replace("const prefix='/jobs/'","const prefix='/efficientad-test/jobs/'").replace("history.replaceState(null,'','/?job='","history.replaceState(null,'','/efficientad-test/?job='")
    match=re.search(r'<script>([\s\S]*?)</script>',page)
    if not match:raise RuntimeError('검사 화면 스크립트를 찾지 못했습니다')
    self.inspection_script=match[1].encode('utf8');page=page[:match.start()]+'<script src="/efficientad-test/script.js"></script>'+page[match.end():];data=page.encode('utf8')
   return status,mime,data
  finally:connection.close();channel.close()
 def request(self,body):
  remote=self.ml.remote
  if remote is None or not remote.client.get_transport() or not remote.client.get_transport().is_active():
   if body.get('action','state')=='state':return dict(ready=False,models=[],datasets=[],jobs=[],reason='설정에서 AI 서버에 연결하세요')
   raise ValueError('설정에서 AI 서버에 먼저 연결하세요')
  with self.lock:
   if self.client is not remote.client:
    with remote.client.open_sftp() as s:
     try:s.mkdir(ROOT+'/studio_management')
     except OSError:pass
     s.put(str(Path(__file__).with_name('efficientad_worker.py')),ROOT+'/studio_management/worker.py')
     s.put(str(Path(__file__).with_name('efficientad_dense_worker.py')),ROOT+'/studio_management/efficientad_dense_worker.py')
    self.client=remote.client;self.cached=None
   if body.get('action','state')=='state' and self.cached and time.monotonic()-self.cached_at<3:return self.cached
   stdin,out,err=remote.client.exec_command(shlex.quote(PYTHON)+' '+shlex.quote(ROOT+'/studio_management/worker.py'),timeout=60)
   stdin.write(json.dumps(body,ensure_ascii=False));stdin.channel.shutdown_write();raw=out.read().decode('utf8');error=err.read().decode('utf8');code=out.channel.recv_exit_status()
   try:result=json.loads(raw)
   except ValueError:raise RuntimeError('EfficientAD 서버 응답을 읽을 수 없습니다: '+error[-400:])
   if code or result.get('error'):raise ValueError(result.get('error','EfficientAD 실행 실패'))
   if body.get('action','state')=='state':self.cached=result;self.cached_at=time.monotonic()
   else:self.cached=None
   return result
