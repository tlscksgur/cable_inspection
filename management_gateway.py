"""Prefix-aware bridge for the existing Studio, reached through SSH only."""
import http.client
import gzip
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

PREFIX = '/cable'


def rewrite(raw, mime, test=False):
    if not any(t in mime for t in ('html', 'javascript', 'css')):
        return raw
    text = raw.decode('utf-8')
    text = text.replace('http://127.0.0.1:8899/', PREFIX+'/test/')
    text = text.replace('http://127.0.0.1:8898/', PREFIX+'/')
    if test:
        text = text.replace('const base=location.origin;', "const base=location.origin+'/cable/test';").replace('let base=location.origin;', "let base=location.origin+'/cable/test';")
        text = re.sub(r'''(?<=["'`])/(?!/)(?=(?:models(?:["'`?])|styles\.css|inspect(?:_boot)?\.js))''', PREFIX+'/test/', text)
        text = text.replace('내 PC · CPU', '운영 PC · CPU').replace('내 PC의 CPU', '운영 PC의 CPU')
    else:
        text = re.sub(r'''(?<=["'`])/(?!/)(?=(?:api/|media/|efficientad-test/|styles\.css|app\.js))''', PREFIX+'/', text)
    return text.encode('utf-8')


def create_server(port=18990):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass  # Never log credentials, bodies, or user file names.

        def reply(self, status, raw=b'', mime='text/plain; charset=utf-8', extra=()):
            compressed=len(raw)>1024 and 'gzip' in self.headers.get('Accept-Encoding','') and any(x in mime for x in ('json','html','javascript','css'))
            if compressed:raw=gzip.compress(raw,compresslevel=3)
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            if compressed:self.send_header('Content-Encoding','gzip');self.send_header('Vary','Accept-Encoding')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection','close')
            self.close_connection=True
            self.send_header('X-Content-Type-Options', 'nosniff')
            for name, value in extra:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(raw)

        def proxy(self):
            path = urlsplit(self.path).path
            if path == PREFIX:
                return self.reply(308, extra=(('Location', PREFIX+'/'),))
            if path == PREFIX+'/test':
                return self.reply(308, extra=(('Location', PREFIX+'/test/'),))
            if not path.startswith(PREFIX+'/'):
                return self.reply(404)
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            if origin and origin != 'http://'+host:
                return self.reply(403)
            test = path.startswith(PREFIX+'/test/')
            port = 8899 if test else 8898
            target = self.path[len(PREFIX+'/test') if test else len(PREFIX):]
            headers = {k:v for k,v in self.headers.items() if k.lower() not in
                       ('host','origin','connection','accept-encoding','transfer-encoding')}
            headers['Host'] = f'127.0.0.1:{port}'
            if origin or self.command != 'GET':
                headers['Origin'] = f'http://127.0.0.1:{port}'
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=300)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0 or length > 85*1024*1024:
                    return self.reply(413)
                if self.headers.get('Transfer-Encoding'):
                    return self.reply(400)
                body = self.rfile.read(length) if length else None
                connection.request(self.command, target, body=body, headers=headers)
                response = connection.getresponse()
                mime = response.getheader('Content-Type', 'application/octet-stream')
                raw = rewrite(response.read(), mime, test)
                extra = [(k,v) for k,v in response.getheaders() if k.lower() in
                         ('content-security-policy','content-disposition','referrer-policy')]
                self.reply(response.status, raw, mime, extra)
            except (OSError, http.client.HTTPException):
                self.reply(502, ('{"error":"'+('RTMDet 테스트 실행부(8899)' if test else '관리 웹(8898)')+'에 연결할 수 없습니다. start.cmd 실행 상태를 확인하세요."}').encode('utf-8'),'application/json; charset=utf-8')
            finally:
                connection.close()

        do_GET = proxy
        do_POST = proxy

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


if __name__ == '__main__':
    create_server().serve_forever()
