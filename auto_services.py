"""Keep the three Studio services running; use the workstation SSH key."""
import json,msvcrt,os,socket,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'.runtime';LOGS=RUNTIME/'logs';LOGS.mkdir(parents=True,exist_ok=True)
lock=(RUNTIME/'auto-services.lock').open('a+b');lock.seek(0)
if not lock.read(1):lock.write(b'1');lock.flush()
lock.seek(0)
try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
except OSError:raise SystemExit(0)
MAIN_PYTHON=Path(os.environ['LOCALAPPDATA'])/'Programs/Python/Python313/python.exe'
TEST_PYTHON=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
services=[('management',8898,MAIN_PYTHON,['server.py','--port','8898']),('inspection',8899,TEST_PYTHON,['test_service.py']),('gateway',7777,TEST_PYTHON,['public_inspection.py','--port','7777'])]
children={}
def listening(port):
 try:
  with socket.create_connection(('127.0.0.1',port),timeout=1):return True
 except OSError:return False
while True:
 state={}
 for name,port,python,args in services:
  running=listening(port)
  if not running and (name not in children or children[name].poll() is not None):
   with (LOGS/(name+'-auto.log')).open('ab') as log:
    children[name]=subprocess.Popen([str(python),'-X','utf8',*args],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  state[name]={'port':port,'listening':running}
 try:(RUNTIME/'auto-services.json').write_text(json.dumps(state,indent=2),encoding='utf8')
 except OSError:pass
 time.sleep(10)
