import {inspectionPage,mountInspection} from './inspect.js';
try{
 const response=await fetch('/models');if(!response.ok)throw Error('모델 목록을 읽을 수 없습니다.');
 document.querySelector('#main').innerHTML=inspectionPage(await response.json());mountInspection();
}catch(e){document.querySelector('#main').textContent=e.message;}
