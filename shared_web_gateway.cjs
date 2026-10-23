// Independent shared entry point. Neither application owns public port 7777.
const http = require('node:http');
function createGateway({businessPort=17777,cablePort=18990}={}) {
  return http.createServer((req,res) => {
    const pathname=req.url.split('?')[0];
    const business=pathname==='/businessCard'||pathname.startsWith('/businessCard/');
    const cable=pathname==='/cable'||pathname.startsWith('/cable/');
    if (!business&&!cable) { res.writeHead(404);res.end('Not found');return; }
    const upstream=http.request({hostname:'127.0.0.1',port:business?businessPort:cablePort,
      method:req.method,path:req.url,headers:{...req.headers,connection:'close'},agent:false,timeout:660000}, response=>{
      res.writeHead(response.statusCode,response.headers);
      response.on('error',()=>res.destroy());response.pipe(res);
    });
    upstream.on('timeout',()=>upstream.destroy());
    upstream.on('error',error=>{
      if(res.headersSent) {res.destroy();return;}
      console.warn('UPSTREAM_FAILED',business?'businessCard':'cable',error.code||'UNKNOWN');
      res.writeHead(502,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
      res.end(JSON.stringify({error:business?'명함 웹에 연결할 수 없습니다.':'케이블 관리 PC와 연결이 끊겼습니다. start.cmd 실행 상태를 확인하세요.'}));
    });
    req.on('aborted',()=>upstream.destroy());
    res.on('close',()=>{if(!res.writableEnded)upstream.destroy();});
    req.pipe(upstream);
  });
}
module.exports={createGateway};
if(require.main===module) {
  const server=createGateway();
  server.on('error',e=>{console.error('Shared gateway failed:',e.code);process.exitCode=1;});
  server.listen(7777,'0.0.0.0',()=>console.log('SHARED_GATEWAY_READY businessCard=17777 cable=18990'));
}
