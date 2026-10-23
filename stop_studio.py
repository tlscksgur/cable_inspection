"""Stop only recognizable local cable services; leave shared server routes alone."""
import argparse
import json
import re
import subprocess

QUERY=r'''
$ErrorActionPreference='Stop'
@(Get-NetTCPConnection -LocalPort 8898,8899,18990 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
 $p=Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)"
 [pscustomobject]@{port=$_.LocalPort;pid=$p.ProcessId;command=$p.CommandLine}
}) | ConvertTo-Json -Compress
'''
EXPECTED={8898:r'\bserver\.py\s+--port\s+8898(?:\s|$)',
          8899:r'\btest_service\.py(?:["\s]|$)',
          18990:r'\b(?:connect_management_gateway|launch_studio)\.py(?:["\s]|$)'}


def allowed(row):
    return bool(re.search(EXPECTED.get(row['port'],r'(?!)'),row.get('command') or ''))


def main(check=False):
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',QUERY],capture_output=True,text=True,encoding='utf-8',errors='replace')
    if result.returncode:raise RuntimeError('실행 중인 프로세스를 확인하지 못했습니다. 종료하지 않았습니다.')
    rows=json.loads(result.stdout.strip() or '[]')
    if isinstance(rows,dict):rows=[rows]
    known=[r for r in rows if allowed(r)]
    for row in rows:
        if not allowed(row):print(f"{row['port']}: 다른 프로그램이므로 유지합니다.")
    if not known:print('실행 중인 케이블 웹이 없습니다.');return
    if check:
        for r in known:print(f"종료 대상: 포트 {r['port']} / PID {r['pid']}")
        return
    # Revalidate PID, port, and command immediately before terminating each process.
    for row in sorted(known,key=lambda r:r['port']!=18990):
        pid=int(row['pid']);port=int(row['port'])
        command=r'''
$p=Get-CimInstance Win32_Process -Filter 'ProcessId=PID_VALUE'
$listener=Get-NetTCPConnection -LocalPort PORT_VALUE -State Listen -ErrorAction SilentlyContinue
if ($p -and $listener -and $p.CommandLine -eq EXPECTED_COMMAND -and ($listener.OwningProcess -contains PID_VALUE)) {Stop-Process -Id PID_VALUE -ErrorAction Stop}
'''.replace('PID_VALUE',str(pid)).replace('PORT_VALUE',str(port)).replace('EXPECTED_COMMAND',"'"+row['command'].replace("'","''")+"'")
        result=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True)
        if result.returncode:raise RuntimeError(f'{port} 종료 실패. 실행 창을 확인하세요.')
    print('케이블 웹 종료 완료. 명함 웹과 서버 중계는 유지했습니다.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args()
    try:main(a.check)
    except Exception as error:print('종료 실패: '+str(error));raise SystemExit(1)
