"""Manual session SSH tunnel. No passwords or keys are persisted."""
import getpass
import select
import socket
import sys
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'.runtime/python_deps'))
import paramiko
from server_settings import HOST, USER
from management_gateway import create_server


def relay(channel, *_):
    local = socket.create_connection(('127.0.0.1',18990), timeout=10)
    local.settimeout(None)
    try:
        while True:
            readable, _, _ = select.select([local,channel],[],[],30)
            for source in readable:
                raw = source.recv(65536)
                if not raw:
                    return
                (channel if source is local else local).sendall(raw)
    finally:
        local.close()
        channel.close()


def run(password=None):
    server = create_server()
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    if password is None:
        password = getpass.getpass('SSH password (session only): ')
    try:
        client.connect(HOST, username=USER, password=password,
                       allow_agent=False, look_for_keys=False, timeout=15)
    finally:
        del password
    transport = client.get_transport()
    transport.set_keepalive(20)
    def accepted(channel, origin, destination):
        threading.Thread(target=relay,args=(channel,),daemon=True).start()
    transport.request_port_forward('127.0.0.1',18990,handler=accepted)
    print('MANAGEMENT_GATEWAY_READY /cable/ -> existing Studio', flush=True)
    try:
        server.serve_forever(poll_interval=1)
    finally:
        client.close()
        server.server_close()


if __name__ == '__main__':
    run()
