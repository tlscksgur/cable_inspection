"""Isolated local/remote inspection. Does not restart Studio or alter training."""
import argparse,getpass,hashlib,json,os,re,shlex,sqlite3,sys,threading,time,uuid
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler

ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'.runtime/local_inference'),str(ROOT.parent/'.runtime/ssh')]
from server_settings import HOST, USER, ROOT as REMOTE_ROOT, PYTHON, MMDET_ROOT
REMOTE=REMOTE_ROOT+'/inspection'
ALLOWED={'http://127.0.0.1:8899','http://localhost:8899'}

class Inspection:
 def __init__(self,data,password):
  import paramiko
  self.data=Path(data);self.root=ROOT/'.runtime/model_test';self.root.mkdir(parents=True,exist_ok=True)
  self.paramiko=paramiko;self.client=None;self.connection_lock=threading.RLock();self.jobs={};self.lock=threading.Lock();self.cache={};self.connection_error=None
  try:self.ensure_connection(password)
  except Exception:self.connection_error='AI 서버 연결 대기 중'
 def ensure_connection(self,password=None):
  from ssh_auth import open_client
  with self.connection_lock:
   transport=self.client.get_transport() if self.client else None
   if transport and transport.is_active():return
   candidate=open_client(self.paramiko,password)
   try:
    _,out,err=candidate.exec_command('mkdir -p '+shlex.quote(REMOTE));out.read();err.read()
    if out.channel.recv_exit_status():raise RuntimeError('서버 작업 폴더에 접근할 수 없습니다')
    with candidate.open_sftp() as s:
     for name in ['worker.py','export_local.py','server_predict.py']:s.put(str(ROOT/name),REMOTE+'/'+name)
   except Exception:candidate.close();raise
   old=self.client;self.client=candidate;self.connection_error=None
   if old:old.close()
 def models(self):
  c=sqlite3.connect((self.data/'studio.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
  try:return [m for p, in c.execute("select payload from studio_records where kind='models'") if not (m:=json.loads(p)).get('deleted')]
  finally:c.close()
 def command(self,cmd):
  self.ensure_connection()
  _,o,e=self.client.exec_command(cmd);output=o.read().decode('utf8','replace');error=e.read().decode('utf8','replace')
  if o.channel.recv_exit_status():raise RuntimeError(error[-2000:] or output[-2000:])
  return output
 def remote_spec(self,model):
  result=dict(classes=model['classes'],mmdet_root=MMDET_ROOT)
  with self.client.open_sftp() as s:
   for name,suffix in [('checkpoint','.pth'),('config','.py')]:
    p=Path(model[name]);digest=hashlib.sha256(p.read_bytes()).hexdigest();dest=REMOTE_ROOT+'/artifacts/'+digest+suffix
    try:s.stat(dest)
    except OSError:s.put(str(p),dest)
    result[name]=dest
  return result
 def run(self,key,body):
  job=self.jobs[key]
  try:
   job.update(message='다른 테스트가 끝나기를 기다리는 중')
   with self.lock:
    self.ensure_connection()
    model=next((m for m in self.models() if m['id']==body['model_id']),None)
    if model is None:raise ValueError('사용 가능한 모델을 선택하세요')
    ids=body['images'];files=[self.root/'images'/i for i in ids]
    if not files or any(not re.fullmatch('[a-f0-9]{32}',i) or not p.is_file() for i,p in zip(ids,files)):raise ValueError('테스트 이미지를 다시 선택하세요')
    threshold=float(body.get('threshold',.4))
    if not 0<=threshold<=1:raise ValueError('점수 기준 범위 오류')
    target=body['target'];started=time.perf_counter();results=[]
    if target=='local':
     from local_inference import LocalModel
     sha=hashlib.sha256(Path(model['checkpoint']).read_bytes()+Path(model['config']).read_bytes()).hexdigest()
     folder=self.root/'models'/sha;folder.mkdir(parents=True,exist_ok=True)
     if not (folder/'metadata.json').is_file() or json.loads((folder/'metadata.json').read_text()).get('format_version')!=2:
      job.update(message='최초 1회: 로컬 실행용 모델 변환·다운로드 중 (서버 CPU 사용)')
      spec=self.remote_spec(model);spec['out']=REMOTE+'/local_'+sha
      with self.client.open_sftp() as s:
       with s.open(REMOTE+'/export_spec.json','w') as f:f.write(json.dumps(spec))
      self.command('cd '+REMOTE+' && '+PYTHON+' export_local.py --spec export_spec.json > export.log 2>&1 || { tail -15 export.log; exit 1; }')
      with self.client.open_sftp() as s:
       s.get(spec['out']+'/model.onnx',str(folder/'model.onnx'));s.get(spec['out']+'/metadata.json',str(folder/'metadata.json'))
     job.update(message='내 PC CPU에서 모델 로딩 중')
     if sha not in self.cache:self.cache.clear();self.cache[sha]=LocalModel(folder)
     load=time.perf_counter()-started
     for i,p in enumerate(files):
      job.update(message=f'내 PC CPU 검사 중 · {i+1}/{len(files)}',completed=i)
      results.append(self.cache[sha].predict(p,threshold));job.update(results=results.copy(),completed=i+1)
    elif target=='server':
     job.update(message='회사 AI 서버로 테스트 이미지 전송 중 (학습과 GPU 공유)')
     spec=self.remote_spec(model);directory=REMOTE+'/inspect_'+key
     self.command('mkdir -p '+directory);remote_files=[]
     with self.client.open_sftp() as s:
      for p in files:
       dest=directory+'/'+p.name;s.put(str(p),dest);remote_files.append(dest)
      spec.update(images=remote_files,out=directory,threshold=threshold)
      with s.open(directory+'/spec.json','w') as f:f.write(json.dumps(spec))
     job.update(message='회사 AI 서버 GPU 검사 중')
     self.command('cd '+REMOTE+' && '+PYTHON+' server_predict.py '+directory+'/spec.json > '+directory+'/log.txt 2>&1 || { tail -12 '+directory+'/log.txt; exit 1; }')
     with self.client.open_sftp() as s:
      with s.open(directory+'/result.json') as f:r=json.loads(f.read())
     results=r['results'];load=r['load_seconds']
    else:raise ValueError('실행 위치를 선택하세요')
    normals={c['id'] for c in model['classes'] if c.get('normal') or c['name'] in ('water','SerialNumber')}
    for r in results:r['defect']=any(a['class_id'] not in normals for a in r['annotations'])
    job.update(status='complete',results=results,completed=len(files),message='검사 완료',classes=model['classes'],load_seconds=load,total_seconds=time.perf_counter()-started)
  except Exception as e:job.update(status='failed',message=str(e))

def serve(data,password,port=8899):
 app=Inspection(data,password)
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*a):pass
  def response(self,body,status=200,ctype='application/json'):
   raw=body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False).encode('utf8')
   self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)))
   origin=self.headers.get('Origin')
   if origin in ALLOWED:self.send_header('Access-Control-Allow-Origin',origin)
   self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
  def do_OPTIONS(self):
   if self.headers.get('Origin') not in ALLOWED:return self.response({},403)
   self.send_response(204);self.send_header('Access-Control-Allow-Origin',self.headers['Origin']);self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS');self.send_header('Access-Control-Allow-Headers','Content-Type,X-Studio-Test');self.end_headers()
  def do_GET(self):
   if self.headers.get('Origin') and self.headers['Origin'] not in ALLOWED:return self.response({},403)
   path=self.path.split('?')[0]
   if path=='/':return self.response((ROOT/'web/inspect.html').read_bytes(),ctype='text/html; charset=utf-8')
   if path in ('/styles.css','/inspect.js','/inspect_boot.js'):
    return self.response((ROOT/'web'/path[1:]).read_bytes(),ctype='text/css' if path.endswith('.css') else 'text/javascript')
   if path=='/models':return self.response([{k:m.get(k) for k in ('id','name','active')} for m in app.models()])
   if path=='/health':
    try:app.ensure_connection();return self.response(dict(local='CPUExecutionProvider',server=True))
    except Exception:return self.response(dict(local='CPUExecutionProvider',server=False,reason='AI 서버 자동 연결 대기 중'))
   if path.startswith('/jobs/'):
    job=app.jobs.get(path.split('/')[-1]);return self.response(job or {},200 if job else 404)
   if path.startswith('/images/'):
    name=path.split('/')[-1]
    if re.fullmatch('[a-f0-9]{32}',name) and (p:=app.root/'images'/name).is_file():return self.response(p.read_bytes(),ctype='application/octet-stream')
   self.response({},404)
  def do_POST(self):
   if self.headers.get('Origin') not in ALLOWED or self.headers.get('X-Studio-Test')!='1':return self.response({},403)
   try:
    n=int(self.headers.get('Content-Length','0'))
    if not 0<n<=50*1024*1024:raise ValueError('파일당 최대 50MB입니다')
    raw=self.rfile.read(n)
    if self.path=='/images':
     from PIL import Image
     import io
     with Image.open(io.BytesIO(raw)) as im:im.verify()
     key=uuid.uuid4().hex;(app.root/'images').mkdir(exist_ok=True);(app.root/'images'/key).write_bytes(raw);return self.response(dict(id=key))
    if self.path=='/jobs':
     body=json.loads(raw);key=uuid.uuid4().hex
     app.jobs[key]=dict(status='running',results=[],completed=0,message='준비 중',total=len(body.get('images',[])))
     threading.Thread(target=app.run,args=(key,body),daemon=True).start();return self.response(dict(id=key))
    self.response({},404)
   except Exception as e:self.response(dict(error=str(e)),400)
 server=ThreadingHTTPServer(('127.0.0.1',port),Handler);print(f'TEST_SERVICE_READY http://127.0.0.1:{port}',flush=True);server.serve_forever()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--data-dir');p.add_argument('--password-stdin',action='store_true',help=argparse.SUPPRESS);a=p.parse_args()
 data=a.data_dir or str(ROOT/json.loads((ROOT/'.runtime/active-data.json').read_text())['data_dir'])
 from ssh_auth import auto_available
 password=json.loads(sys.stdin.readline())['password'] if a.password_stdin else (None if auto_available() else getpass.getpass('SSH password (session only): '))
 serve(data,password)
