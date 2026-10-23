"""One manual launch for Studio, test service and the server route. No saved secrets."""
import argparse
import getpass
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PUBLIC='http://gpu.example.internal:7777/cable/'
PORTS={'관리 웹':8898,'RTMDet 이미지 테스트':8899,'서버 경로 연결':18990}


def listening(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=1):return True
    except OSError:return False


def request(path,body=None,timeout=30):
    raw=json.dumps(body).encode() if body is not None else None
    headers={'Content-Type':'application/json','Origin':'http://127.0.0.1:8898'} if raw else {}
    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8898'+path,raw,headers),timeout=timeout) as response:
        return json.load(response)


def wait_port(port,child=None,seconds=60):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if child and child.poll() is not None:raise RuntimeError('실행에 실패했습니다. .runtime/logs/start-*.log를 확인하세요.')
        if listening(port):return
        time.sleep(.3)
    raise RuntimeError(f'{port} 포트 실행 대기 시간이 초과됐습니다.')


def main(check=False):
    running={name:listening(port) for name,port in PORTS.items()}
    if check:
        for name,ready in running.items():print(f'{name}: {"실행 중" if ready else "꺼짐"}')
        return
    # The launcher is interactive only; it does not install startup entries or keys.
    import msvcrt
    runtime=ROOT/'.runtime';runtime.mkdir(exist_ok=True)
    lock=(runtime/'manual-start.lock').open('a+b')
    if lock.seek(0,2)==0:lock.write(b'1');lock.flush()
    lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        lock.close();print('통합 실행 창이 이미 열려 있습니다.');return
    children=[];gateway_thread=None
    logs=runtime/'logs';logs.mkdir(exist_ok=True)
    def start(name,python,args,password=None):
        with (logs/f'start-{name}.log').open('ab') as log:
            child=subprocess.Popen([str(python),'-X','utf8',*args],cwd=ROOT,
                stdin=subprocess.PIPE if password is not None else subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        children.append(child)
        if password is not None:
            child.stdin.write(json.dumps({'password':password}).encode()+b'\n')
            child.stdin.close()
        return child
    try:
        if not running['관리 웹']:
            print('관리 웹 시작 중…',flush=True)
            wait_port(8898,start('management',sys.executable,['server.py','--port','8898']))
        else:print('관리 웹: 기존 실행 사용')
        try:ai_ready=bool(request('/api/efficientad').get('ready'))
        except Exception:raise RuntimeError('8898 포트의 관리 웹을 확인할 수 없습니다. 기존 프로그램을 확인하세요.')
        needs_password=not ai_ready or not running['RTMDet 이미지 테스트'] or not running['서버 경로 연결']
        password=getpass.getpass('AI 서버 비밀번호 (저장하지 않음): ') if needs_password else None
        try:
            if not ai_ready:
                print('관리 웹 AI 서버 연결 중…',flush=True)
                if not request('/api/ml/connect',{'password':password},timeout=90).get('ready'):
                    raise RuntimeError('관리 웹 AI 서버 연결에 실패했습니다.')
            if not running['RTMDet 이미지 테스트']:
                python=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
                if not python.is_file():raise RuntimeError('이미지 테스트용 Python을 찾지 못했습니다.')
                print('RTMDet 이미지 테스트 시작 중…',flush=True)
                wait_port(8899,start('inspection',python,['test_service.py','--password-stdin'],password),seconds=90)
            else:print('RTMDet 이미지 테스트: 기존 실행 사용')
            if not running['서버 경로 연결']:
                from connect_management_gateway import run
                errors=[]
                def connect(secret):
                    try:run(secret)
                    except Exception as error:errors.append(type(error).__name__)
                gateway_thread=threading.Thread(target=connect,args=(password,),daemon=True)
                gateway_thread.start()
                end=time.monotonic()+40
                while time.monotonic()<end:
                    if errors:raise RuntimeError('서버 경로 연결에 실패했습니다: '+errors[0])
                    try:
                        with urllib.request.urlopen(PUBLIC,timeout=3) as response:
                            if response.status==200:break
                    except OSError:time.sleep(.5)
                else:raise RuntimeError('서버의 7777 중계 프로그램과 SSH 연결을 확인하세요.')
            else:print('서버 경로 연결: 기존 실행 사용')
        finally:
            del password
        for attempt in range(5):
            try:
                with urllib.request.urlopen(PUBLIC,timeout=15) as response:
                    if response.status==200:break
            except OSError:
                if attempt==4:raise RuntimeError('공유 주소 접속을 확인하지 못했습니다.')
                time.sleep(.5)
        print('\n실행 완료: '+PUBLIC+'\n이 창을 켜 두세요. 종료하려면 Ctrl+C를 누르세요.',flush=True)
        while True:
            if any(child.poll() is not None for child in children):raise RuntimeError('실행한 서비스가 종료됐습니다. .runtime/logs/start-*.log를 확인하세요.')
            if gateway_thread and not gateway_thread.is_alive():raise RuntimeError('서버 연결이 종료됐습니다. start.cmd를 다시 실행하세요.')
            time.sleep(2)
    except KeyboardInterrupt:
        print('\n통합 실행을 종료합니다.')
    finally:
        # Never stop a service that was already running before this launcher.
        for child in children:
            if child.poll() is None:child.terminate()
        lock.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    try:main(args.check)
    except Exception as error:
        print('실행 실패: '+str(error),flush=True)
        sys.exit(1)
