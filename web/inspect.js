const base=location.origin;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let chosen=[],results=[],classes=[],busy=false,shown=20;
async function api(path,body){
 let response;
 try{response=await fetch(base+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-Studio-Test':'1'}:{},body:body?JSON.stringify(body):undefined});}
 catch{throw Error('테스트 실행부에 연결되지 않습니다. start-test.cmd를 실행하세요.');}
 const value=await response.json();if(!response.ok)throw Error(value.error||'요청 실패');return value;
}
export function inspectionPage(models){return `<section class="card pad"><div class="cardhead"><h2>이미지 테스트</h2><span class="tiny muted">학습 데이터·라벨에 반영되지 않습니다</span></div><div class="formgrid"><label class="field">모델<select id="inspect-model">${models.map(m=>`<option value="${esc(m.id)}" ${m.active?'selected':''}>${esc(m.name)}</option>`).join('')}</select></label><div class="field">실행 위치<div class="row"><button class="btn primary" data-inspect-target="local">내 PC · CPU</button><button class="btn" data-inspect-target="server">회사 AI 서버</button></div><input type="hidden" id="inspect-target" value="local"></div></div><p class="tiny muted" id="inspect-note">로컬은 이 PC의 CPU로 실행합니다. AMD GPU / RTX 3060 측정 결과가 아닙니다. 모델 변환·다운로드는 최초 1회 서버 연결을 사용합니다.</p><div class="row between" style="margin:16px 0"><label class="btn">이미지 추가<input type="file" id="inspect-files" accept="image/jpeg,image/png,image/bmp,image/tiff,image/webp" multiple hidden></label><label class="field">표시 점수 기준<input id="inspect-threshold" type="number" value="0.4" min="0" max="1" step="0.05"></label><button class="btn" id="inspect-clear">선택 비우기</button><button id="inspect-run" class="btn primary">검사 시작</button></div><p id="inspect-status" role="status">이미지를 선택하세요. 장수 제한 없이 순서대로 검사합니다. 파일당 최대 50MB.</p><div id="inspect-selected" class="tiny muted"></div></section><section id="inspect-results" class="inspection-results" aria-label="검사 결과"></section><button class="btn" id="inspect-more" hidden>결과 20개 더 보기</button>`;}
export function mountInspection(){
 const root=document.querySelector('#main'),status=()=>root.querySelector('#inspect-status');
 const notify=t=>{if(status())status().textContent=t;};
 const render=()=>{
  const host=root.querySelector('#inspect-results');if(!host)return;
  root.querySelector('#inspect-selected').textContent=`선택 ${chosen.length}장`;
  host.innerHTML=results.slice(0,shown).map((r,i)=>`<article class="card pad"><div class="row between"><h3>${esc(r.name)}</h3><b class="${r.defect?'inspection-defect':'good'}">${r.defect?'결함 의심':'정상'}</b></div><p class="tiny muted">${esc(r.device)} · ${(r.seconds*1000).toFixed(0)} ms · ${r.annotations.length}개 인식 · ${r.width} × ${r.height}</p><canvas data-inspection="${i}" style="width:100%;height:auto"></canvas><p class="tiny muted">빨강: 결함 · 초록: 정상 물방울·시리얼</p><div class="smalltext">${r.annotations.map(a=>`${esc(classes.find(c=>c.id===a.class_id)?.name||a.class_id)} ${(a.score*100).toFixed(1)}%`).join(' · ')||'표시 기준을 넘는 검출 없음'}</div></article>`).join('');
  root.querySelector('#inspect-more').hidden=results.length<=shown;
  host.querySelectorAll('canvas').forEach(canvas=>{
   const r=results[Number(canvas.dataset.inspection)],img=new Image();img.crossOrigin='anonymous';
   img.onload=()=>{
    const scale=Math.min(1,1400/r.width);canvas.width=Math.round(r.width*scale);canvas.height=Math.round(r.height*scale);const ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);
    r.annotations.forEach(a=>{const c=classes.find(c=>c.id===a.class_id),normal=c?.normal||['water','SerialNumber'].includes(c?.name);ctx.strokeStyle=normal?'#18b582':'#ef4444';ctx.lineWidth=2;
     for(const polygon of a.polygons){ctx.beginPath();polygon.forEach(([x,y],i)=>i?ctx.lineTo(x*scale,y*scale):ctx.moveTo(x*scale,y*scale));ctx.closePath();ctx.stroke();}
     const [x,y,x2,y2]=a.box;ctx.strokeRect(x*scale,y*scale,(x2-x)*scale,(y2-y)*scale);
    });
   };img.src=base+'/images/'+r.image_id;
  });
 };
 root.querySelector('#inspect-files').onchange=e=>{chosen.push(...e.target.files);render();notify(`${chosen.length}장 선택됨`);e.target.value='';};
 root.querySelector('#inspect-more').onclick=()=>{shown+=20;render();};
 root.querySelector('#inspect-clear').onclick=()=>{if(busy)return;chosen=[];results=[];render();notify('이미지를 선택하세요.');};
 root.querySelectorAll('[data-inspect-target]').forEach(b=>b.onclick=()=>{root.querySelector('#inspect-target').value=b.dataset.inspectTarget;root.querySelectorAll('[data-inspect-target]').forEach(x=>x.classList.toggle('primary',x===b));root.querySelector('#inspect-target').dispatchEvent(new Event('change'));});
 root.querySelector('#inspect-target').onchange=e=>{root.querySelector('#inspect-note').textContent=e.target.value==='local'?'로컬은 내 PC CPU로 실행합니다. 최초 1회만 서버에서 변환·다운로드합니다.':'회사 AI 서버의 GPU를 사용합니다. 서버 학습과 동시에 실행하면 양쪽 속도가 느려질 수 있습니다.';};
 root.querySelector('#inspect-run').onclick=async()=>{
  if(busy)return;if(!chosen.length)return notify('검사할 이미지를 선택하세요.');
  const files=[...chosen],model=root.querySelector('#inspect-model').value,target=root.querySelector('#inspect-target').value,threshold=Number(root.querySelector('#inspect-threshold').value);
  if(!Number.isFinite(threshold)||threshold<0||threshold>1)return notify('점수 기준은 0~1입니다.');
  busy=true;root.querySelector('#inspect-run').disabled=true;results=[];shown=20;
  try{
   const ids=[];
   for(let i=0;i<files.length;i++){
    notify(`테스트 이미지 준비 · ${i+1}/${files.length}`);
    const r=await fetch(base+'/images',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Studio-Test':'1'},body:files[i]});const value=await r.json();if(!r.ok)throw Error(value.error);ids.push(value.id);
   }
   const job=await api('/jobs',{model_id:model,target,threshold,images:ids});let state;
   do{await new Promise(r=>setTimeout(r,1000));state=await api('/jobs/'+job.id);notify(state.message);}
   while(state.status==='running');
   if(state.status!=='complete')throw Error(state.message);
   classes=state.classes;results=state.results.map((r,i)=>({...r,name:files[i].name,image_id:ids[i]}));render();
   notify(`완료 ${results.length}장 · 준비/모델 로딩 ${state.load_seconds.toFixed(1)}초 · 전체 ${state.total_seconds.toFixed(1)}초`);
  }catch(e){notify(e.message||'검사 실패');}
  finally{busy=false;const button=root.querySelector('#inspect-run');if(button)button.disabled=false;}
 };
 render();
}
