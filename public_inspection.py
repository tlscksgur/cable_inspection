"""Public inspection-only gateway. Training/admin routes are never proxied."""
import argparse,http.client,json,re,secrets,threading,time,logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit

PREFIX='/cable/rtmdet'
ID=re.compile(r'^[a-f0-9]{32}$')
LOG=logging.getLogger('public_inspection')

def configure_logging():
 folder=Path(__file__).resolve().parent/'.runtime/logs';folder.mkdir(parents=True,exist_ok=True)
 LOG.setLevel(logging.INFO)
 handler=RotatingFileHandler(folder/'public-inspection.log',maxBytes=2*1024*1024,backupCount=3,encoding='utf8')
 handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
 LOG.addHandler(handler)

def safe_route(path):
 path=urlsplit(path).path
 if path in (PREFIX,PREFIX+'/',PREFIX+'/models',PREFIX+'/health',PREFIX+'/images',PREFIX+'/jobs',PREFIX+'/inspect.js',PREFIX+'/inspect_boot.js',PREFIX+'/styles.css'):return path
 if re.fullmatch(re.escape(PREFIX)+r'/(images|jobs)/[a-f0-9]{32}',path):return path.rsplit('/',1)[0]+'/<id>'
 return '<other>'

def create_server(port=7777,host='0.0.0.0',upstream_port=8899):
 sessions={};lock=threading.RLock()
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def reply(self,status,raw=b'',ctype='application/json',sid=None,location=None):
   LOG.info('HTTP client=%s method=%s route=%s status=%s',self.client_address[0],self.command,safe_route(self.path),status)
   self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)))
   self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
   self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
   if sid:self.send_header('Set-Cookie',f'rtmdet_session={sid}; Path={PREFIX}/; HttpOnly; SameSite=Lax')
   if location:self.send_header('Location',location)
   self.end_headers()
   try:self.wfile.write(raw)
   except (BrokenPipeError,ConnectionResetError):pass
  def proxy(self):
   external_path=urlsplit(self.path).path
   if self.command=='GET' and external_path==PREFIX:return self.reply(302,location=PREFIX+'/')
   if not external_path.startswith(PREFIX+'/'):return self.reply(404)
   path=external_path[len(PREFIX):]
   cookie=SimpleCookie()
   try:cookie.load(self.headers.get('Cookie',''));sid=cookie['rtmdet_session'].value if 'rtmdet_session' in cookie else ''
   except Exception:sid=''
   issued=None
   with lock:
    for key in [k for k,v in sessions.items() if time.time()-v['seen']>86400]:del sessions[key]
    if sid not in sessions:
     if self.command!='GET' or path!='/':return self.reply(404)
     sid=secrets.token_urlsafe(32);sessions[sid]={'seen':time.time(),'images':set(),'jobs':set()};issued=sid
    session=sessions[sid];session['seen']=time.time()
   body=None
   if self.command=='GET':
    static=path in ('/','/styles.css','/inspect.js','/inspect_boot.js','/models','/health')
    match=re.fullmatch(r'/(jobs|images)/([a-f0-9]{32})',path)
    with lock:owned=bool(match and match[2] in session[match[1]])
    if not static and not owned:return self.reply(404)
   else:
    origin=self.headers.get('Origin','');expected='http://'+self.headers.get('Host','')
    if origin!=expected or self.headers.get('X-Studio-Test')!='1':return self.reply(403)
    if path not in ('/images','/jobs'):return self.reply(404)
    try:
     length=int(self.headers.get('Content-Length','0'))
     if not 0<length<=50*1024*1024:return self.reply(413)
     body=self.rfile.read(length)
     if len(body)!=length:return self.reply(400)
     if path=='/jobs':
      spec=json.loads(body);ids=spec.get('images',[])
      with lock:valid=isinstance(ids,list) and bool(ids) and all(isinstance(i,str) and ID.fullmatch(i) and i in session['images'] for i in ids)
      if not valid:return self.reply(400,b'{"error":"Select your images again"}')
    except (ValueError,TypeError):return self.reply(400)
   conn=http.client.HTTPConnection('127.0.0.1',upstream_port,timeout=60)
   try:
    headers={}
    if body is not None:headers={'Origin':f'http://127.0.0.1:{upstream_port}','X-Studio-Test':'1','Content-Type':self.headers.get('Content-Type','application/json')}
    conn.request(self.command,path,body=body,headers=headers);response=conn.getresponse();raw=response.read();ctype=response.getheader('Content-Type','application/json')
    if self.command=='POST' and response.status==200:
     key=json.loads(raw).get('id')
     if key:
      with lock:session['images' if path=='/images' else 'jobs'].add(key)
    if path=='/' and response.status==200:
     page=raw.decode('utf8').replace('http://127.0.0.1:8898/#/train',PREFIX+'/')
     page=page.replace('학습 화면으로','이미지 검사').replace('href="/styles.css"',f'href="{PREFIX}/styles.css"').replace('src="/inspect_boot.js"',f'src="{PREFIX}/inspect_boot.js"');raw=page.encode('utf8')
    if path=='/inspect.js' and response.status==200:
     script=raw.decode('utf8').replace('const base=location.origin;',f'const base=location.origin+{json.dumps(PREFIX)};').replace('내 PC · CPU','운영 PC · CPU').replace('내 PC의 CPU','운영 PC의 CPU').replace('내 PC CPU','운영 PC CPU').replace('로컬은 이 PC의 CPU','로컬은 운영 PC의 CPU')
     raw=script.replace('let base=location.origin;',f'let base=location.origin+{json.dumps(PREFIX)};').encode('utf8')
    if path=='/inspect_boot.js' and response.status==200:
     raw=raw.decode('utf8').replace("fetch('/models')",f"fetch('{PREFIX}/models')").encode('utf8')
    if path.startswith('/jobs/') and response.status==200:
     result=json.loads(raw)
     for row in result.get('results',[]):
      if 'device' in row:row['device']=row['device'].replace('내 PC','운영 PC')
     result['message']=result.get('message','').replace('내 PC','운영 PC');raw=json.dumps(result,ensure_ascii=False).encode('utf8')
    self.reply(response.status,raw,ctype,issued)
   except (OSError,http.client.HTTPException,ValueError) as error:
    LOG.error('UPSTREAM_FAILED type=%s',type(error).__name__)
    self.reply(502,b'{"error":"Inspection service unavailable"}')
   finally:conn.close()
  do_GET=proxy
  do_POST=proxy
 class LoggedServer(ThreadingHTTPServer):
  def get_request(self):
   sock,addr=super().get_request();LOG.info('TCP_ACCEPT client=%s',addr[0]);return sock,addr
 server=LoggedServer((host,port),Handler);server.daemon_threads=True;return server

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=7777);p.add_argument('--host',default='0.0.0.0');a=p.parse_args()
 configure_logging();LOG.info('START bind=%s port=%s prefix=%s upstream=127.0.0.1:8899',a.host,a.port,PREFIX)
 server=create_server(a.port,a.host);print(f'INSPECTION_PUBLIC_READY {a.host}:{a.port}',flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
