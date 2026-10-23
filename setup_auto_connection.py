"""Explicit, one-time SSH key registration. No changes without --register."""
import argparse
import getpass
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEY = Path.home() / '.ssh' / 'dxel_studio_ed25519'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--register', action='store_true')
    parser.add_argument('--startup', action='store_true')
    args = parser.parse_args()
    if not args.register:
        print('Preview only: register a workstation key for cable@gpu.example.internal.')
        print('Private key: user .ssh/dxel_studio_ed25519; no password is stored.')
        return
    sys.path.insert(0, str(ROOT / '.runtime/python_deps'))
    import paramiko

    KEY.parent.mkdir(exist_ok=True)
    if KEY.is_symlink() or KEY.with_suffix('.pub').is_symlink():
        raise RuntimeError('SSH key path is a symbolic link')
    if not KEY.exists():
        subprocess.run([
            'C:/Windows/System32/OpenSSH/ssh-keygen.exe', '-q', '-t', 'ed25519',
            '-f', str(KEY), '-N', '', '-C', 'dxel-studio-workstation',
        ], check=True, capture_output=True)
    sid = subprocess.check_output([
        'powershell.exe', '-NoProfile', '-Command',
        '[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value',
    ], text=True).strip()
    subprocess.run([
        'icacls.exe', str(KEY), '/inheritance:r', '/grant:r',
        '*' + sid + ':(F)', '*S-1-5-18:(F)',
    ], check=True, capture_output=True)

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    password = getpass.getpass('SSH password (registration only, not stored): ')
    client.connect('gpu.example.internal', username='cable', password=password,
                   look_for_keys=False, allow_agent=False, timeout=15)
    del password
    public = KEY.with_suffix('.pub').read_text().strip()
    code = '''import os,pathlib,pwd,json,sys
assert pwd.getpwuid(os.getuid()).pw_name == 'cable'
source=os.environ['SSH_CONNECTION'].split()[0]
assert source == 'gpu.example.internal', 'Unexpected workstation source address'
public=json.load(sys.stdin)['public']
assert public.startswith('ssh-ed25519 ') and '\\n' not in public
folder=pathlib.Path.home()/'.ssh';folder.mkdir(mode=0o700,exist_ok=True)
path=folder/'authorized_keys'
assert not folder.is_symlink() and not path.is_symlink()
previous=path.read_text() if path.exists() else ''
if public.split()[1] not in previous:
    options='from="'+source+'",restrict,port-forwarding,permitopen="127.0.0.1:8768" '
    with path.open('a') as f:
        f.write(('\\n' if previous and not previous.endswith('\\n') else '')+options+public+'\\n')
folder.chmod(0o700);path.chmod(0o600)
print('PUBLIC_KEY_REGISTERED')
'''
    stdin, stdout, stderr = client.exec_command(
        '/srv/cable/miniconda3/envs/anomaly/bin/python -c ' + shlex.quote(code))
    stdin.write(json.dumps({'public': public}))
    stdin.channel.shutdown_write()
    stdout.read()
    error = stderr.read()
    if stdout.channel.recv_exit_status():
        raise RuntimeError(error.decode('utf8', 'replace')[-800:])
    client.close()

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect('gpu.example.internal', username='cable', key_filename=str(KEY),
                   look_for_keys=False, allow_agent=False, timeout=15)
    _, out, _ = client.exec_command('true')
    assert out.channel.recv_exit_status() == 0
    channel = client.get_transport().open_channel(
        'direct-tcpip', ('127.0.0.1', 8768), ('127.0.0.1', 0), timeout=10)
    channel.close()
    client.close()
    print('KEY_LOGIN_AND_EFFICIENTAD_TUNNEL_VERIFIED')
    if args.startup:
        startup = Path.home() / 'AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup'
        link = startup / 'dxel Studio.lnk'
        pythonw = Path.home() / 'AppData/Local/Programs/Python/Python313/pythonw.exe'
        def quoted(value):
            return "'" + str(value).replace("'", "''") + "'"
        command = (
            '$shell=New-Object -ComObject WScript.Shell;'
            '$link=$shell.CreateShortcut(' + quoted(link) + ');'
            '$link.TargetPath=' + quoted(pythonw) + ';'
            '$link.Arguments=' + quoted('"' + str(ROOT / 'auto_services.py') + '"') + ';'
            '$link.WorkingDirectory=' + quoted(ROOT) + ';$link.Save()'
        )
        subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], check=True)
        print('WINDOWS_LOGIN_STARTUP_REGISTERED')


if __name__ == '__main__':
    main()
