// Mounted before the independent business-card application; never parses bodies.
const http = require('node:http');
module.exports = function cableProxy(req, res) {
  const upstream = http.request({
    hostname: '127.0.0.1', port: 18990, method: req.method,
    path: req.originalUrl, headers: {...req.headers, connection: 'close'},
    timeout: 330000,
  }, response => {
    res.writeHead(response.statusCode, response.headers);
    response.pipe(res);
  });
  upstream.on('timeout', () => upstream.destroy());
  upstream.on('error', () => {
    if (!res.headersSent) res.writeHead(502, {'Content-Type':'text/plain; charset=utf-8'});
    res.end('케이블 관리 PC와 연결되지 않았습니다. 관리자에게 연결 상태를 확인해 주세요.');
  });
  req.on('aborted', () => upstream.destroy());
  res.on('close', () => { if (!res.writableEnded) upstream.destroy(); });
  req.pipe(upstream);
};
