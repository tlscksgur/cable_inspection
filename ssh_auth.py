"""Session SSH login using the dedicated workstation key or an explicit password."""
from pathlib import Path
KEY_FILE=Path.home()/'.ssh'/'dxel_studio_ed25519'
from server_settings import HOST, USER
def auto_available():return KEY_FILE.is_file()
def open_client(paramiko,password=None):
 client=paramiko.SSHClient();client.load_system_host_keys();client.set_missing_host_key_policy(paramiko.RejectPolicy())
 credentials={'key_filename':str(KEY_FILE)} if auto_available() else {}
 if password is not None:credentials['password']=password
 if not credentials:raise RuntimeError('자동 연결용 SSH 키 등록이 필요합니다. 설정에서 서버에 연결하세요.')
 try:client.connect(HOST,username=USER,look_for_keys=False,allow_agent=False,timeout=10,auth_timeout=15,banner_timeout=15,**credentials)
 except Exception:client.close();raise
 client.get_transport().set_keepalive(20);return client
