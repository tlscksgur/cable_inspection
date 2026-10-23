let base=location.origin;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let chosen=[],results=[],classes=[],busy=false,shown=20,active=0,overlay=true,previewUrls=[],resultModel='';
async function api(path,body){
 let response;
 try{response=await fetch(base+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-Studio-Test':'1'}:{},body:body?JSON.stringify(body):undefined});}
 catch{throw Error('테스트 실행부에 연결되지 않습니다. start-test.cmd를 실행하세요.');}
 return readResponse(response);
}
async function readResponse(response){let value;try{value=await response.json();}catch{throw Error(`이미지 테스트 서버 연결 오류 (${response.status}). start.cmd 실행 상태를 확인하세요.`);}if(!response.ok)throw Error(value.error||`검사 요청 실패 (${response.status})`);return value;}
export function inspectionPage(models){return `<div class="inspection-page"><div class="pagehead"><div><p class="eyebrow">MODEL INSPECTION</p><h1>이미지 테스트</h1><p>사진을 선택하고, 검사 결과를 한 장씩 확인하세요.</p></div><span class="tiny muted">학습 데이터에 반영되지 않습니다</span></div><div class="inspection-layout"><aside class="card inspection-settings"><h2>검사 설정</h2><label class="field">모델<select id="inspect-model">${models.map(m=>`<option value="${esc(m.id)}" ${m.active?'selected':''}>${esc(m.name)}</option>`).join('')}</select></label><div class="field">실행 위치<div class="inspection-targets"><button class="btn primary" data-inspect-target="local">내 PC · CPU</button><button class="btn" data-inspect-target="server">회사 AI 서버</button></div><input type="hidden" id="inspect-target" value="local"></div><p class="tiny muted" id="inspect-note">내 PC의 CPU로 실행합니다. 모델 준비는 최초 1회 서버 연결을 사용합니다.</p><label class="inspection-upload">＋<strong>이미지 추가</strong><span>여러 장 선택 가능 · 파일당 50MB</span><input type="file" id="inspect-files" accept="image/jpeg,image/png,image/bmp,image/tiff,image/webp" multiple hidden></label><div class="row between"><span id="inspect-selected" class="smalltext">선택 0장</span><button class="btn ghost small" id="inspect-clear">선택 비우기</button></div><details class="inspection-options"><summary>검사 옵션</summary><label class="field">표시 점수 기준<input id="inspect-threshold" type="number" value="0.4" min="0" max="1" step="0.05"></label></details><button id="inspect-run" class="btn primary inspection-run">검사 시작</button><p id="inspect-status" role="status" class="tiny muted">이미지를 선택하세요.</p></aside><section class="inspection-workspace"><div id="inspect-summary" class="inspection-summary"></div><div class="inspection-result-layout"><section id="inspect-results" class="card inspection-viewer" aria-label="선택한 이미지"></section><aside class="card inspection-queue"><div class="inspection-queue-head"><h2>이미지 목록</h2><span id="inspect-count" class="tiny muted">0장</span></div><div id="inspect-list"></div><button class="btn" id="inspect-more" hidden>결과 20개 더 보기</button></aside></div></section></div></div>`;}
export function mountInspection({baseUrl}={}){
 if(baseUrl)base=baseUrl;
 const root=document.querySelector('#main'),status=()=>root.querySelector('#inspect-status');
 const notify=t=>{if(status())status().textContent=t;};
 const render=()=>{
  const host=root.querySelector('#inspect-results');if(!host)return;
  root.querySelector('#inspect-selected').textContent=`선택 ${chosen.length}장`;
  const items=results.length?results:chosen.map((f,i)=>({name:f.name,preview:previewUrls[i]}));
  active=Math.min(active,Math.max(0,items.length-1));
  const r=items[active],done=results.length>0;
  root.querySelector('#inspect-count').textContent=`${items.length}장`;
  root.querySelector('#inspect-summary').innerHTML=done?`<span>검사 완료 <b>${results.length}</b>장</span><span class="inspection-defect">결함 의심 <b>${results.filter(r=>r.defect).length}</b></span><span class="good">정상 <b>${results.filter(r=>!r.defect).length}</b></span><span class="muted">평균 ${(results.reduce((s,r)=>s+r.seconds,0)/results.length).toFixed(2)}초 / 장</span>`:`<span>선택한 이미지 <b>${items.length}</b>장</span><span class="muted">${busy?'검사 진행 중':'검사 준비'}</span>`;
  root.querySelector('#inspect-list').innerHTML=items.slice(0,shown).map((r,i)=>`<button class="inspection-item ${i===active?'active':''}" data-inspect-item="${i}" aria-pressed="${i===active}"><img src="${esc(done?base+'/images/'+r.image_id:r.preview)}" alt="" loading="lazy"><span><strong title="${esc(r.name)}">${esc(r.name)}</strong><small class="${done?(r.defect?'inspection-defect':'good'):'muted'}">${done?(r.defect?'결함 의심':'정상'):'검사 대기'}${done?' · '+r.seconds.toFixed(2)+'초':''}</small></span></button>`).join('');
  root.querySelectorAll('[data-inspect-item]').forEach(b=>b.onclick=()=>{active=Number(b.dataset.inspectItem);render();});
  host.innerHTML=r?`<div class="inspection-view-head"><div><h2 title="${esc(r.name)}">${esc(r.name)}</h2><span class="tiny muted">${active+1} / ${items.length}${done?' · '+r.width+' × '+r.height+' px · '+esc(r.device):''}</span></div>${done?`<span class="inspection-badge ${r.defect?'defect':'normal'}">${r.defect?'결함 의심':'정상'}</span>`:''}</div>${done?`<div class="inspection-model-caption" title="${esc(resultModel)}">${esc(resultModel)}</div>`:''}<div class="inspection-toolbar"><div class="row"><button class="btn small" id="inspect-prev" ${active===0?'disabled':''}>← 이전</button><button class="btn small" id="inspect-next" ${active===items.length-1?'disabled':''}>다음 →</button></div>${done?`<label class="checkline"><input id="inspect-overlay" type="checkbox" ${overlay?'checked':''}> 검출 위치 표시</label>`:'<span class="tiny muted">검사 전 원본</span>'}</div><div class="inspection-stage">${done?'<canvas aria-label="검출 위치가 표시된 검사 이미지"></canvas>':`<img src="${esc(r.preview)}" alt="${esc(r.name)}">`}</div>${done?`<div class="inspection-findings"><div class="row between"><strong>검출 항목 <span class="muted">${r.annotations.length}</span></strong><span class="tiny muted">빨강 · 결함 / 초록 · 물방울·시리얼</span></div><div class="inspection-tags">${r.annotations.map(a=>{const c=classes.find(c=>c.id===a.class_id),normal=c?.normal||['water','SerialNumber'].includes(c?.name);return `<span class="inspection-tag ${normal?'normal':'defect'}">${esc(c?.name||a.class_id)} <b>${(a.score*100).toFixed(1)}%</b></span>`;}).join('')||'<span class="muted smalltext">표시 기준을 넘는 검출 없음</span>'}</div></div>`:''}`:`<div class="inspection-empty"><span>▧</span><h2>검사할 이미지를 추가하세요</h2><p>선택한 사진과 검출 위치가 여기에 표시됩니다.</p></div>`;
  root.querySelector('#inspect-more').hidden=items.length<=shown;
  if(!r)return;
  root.querySelector('#inspect-prev').onclick=()=>{active--;render();};
  root.querySelector('#inspect-next').onclick=()=>{active++;shown=Math.max(shown,active+1);render();};
  const toggle=root.querySelector('#inspect-overlay');if(toggle)toggle.onchange=()=>{overlay=toggle.checked;render();};
  const canvas=host.querySelector('canvas');if(!canvas)return;
  const img=new Image();img.onload=()=>{
   const scale=Math.min(1,1800/r.width);canvas.width=Math.round(r.width*scale);canvas.height=Math.round(r.height*scale);const ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);
   if(!overlay)return;
   r.annotations.forEach(a=>{const c=classes.find(c=>c.id===a.class_id),normal=c?.normal||['water','SerialNumber'].includes(c?.name);ctx.strokeStyle=normal?'#18b582':'#ff5252';ctx.lineWidth=2;
    for(const polygon of a.polygons){ctx.beginPath();polygon.forEach(([x,y],i)=>i?ctx.lineTo(x*scale,y*scale):ctx.moveTo(x*scale,y*scale));ctx.closePath();ctx.stroke();}
    const [x,y,x2,y2]=a.box;ctx.strokeRect(x*scale,y*scale,(x2-x)*scale,(y2-y)*scale);
   });
  };img.src=base+'/images/'+r.image_id;
 };
 root.querySelector('#inspect-files').onchange=e=>{if(busy)return;chosen.push(...e.target.files);previewUrls.push(...Array.from(e.target.files,f=>URL.createObjectURL(f)));results=[];shown=20;active=0;render();notify(`${chosen.length}장 선택됨`);e.target.value='';};
 root.querySelector('#inspect-more').onclick=()=>{shown+=20;render();};
 root.querySelector('#inspect-clear').onclick=()=>{if(busy)return;previewUrls.forEach(u=>URL.revokeObjectURL(u));previewUrls=[];chosen=[];results=[];active=0;render();notify('이미지를 선택하세요.');};
 root.querySelectorAll('[data-inspect-target]').forEach(b=>b.onclick=()=>{root.querySelector('#inspect-target').value=b.dataset.inspectTarget;root.querySelectorAll('[data-inspect-target]').forEach(x=>x.classList.toggle('primary',x===b));root.querySelector('#inspect-target').dispatchEvent(new Event('change'));});
 root.querySelector('#inspect-target').onchange=e=>{root.querySelector('#inspect-note').textContent=e.target.value==='local'?'로컬은 내 PC CPU로 실행합니다. 최초 1회만 서버에서 변환·다운로드합니다.':'회사 AI 서버의 GPU를 사용합니다. 서버 학습과 동시에 실행하면 양쪽 속도가 느려질 수 있습니다.';};
 root.querySelector('#inspect-run').onclick=async()=>{
  if(busy)return;if(!chosen.length)return notify('검사할 이미지를 선택하세요.');
  resultModel=root.querySelector('#inspect-model').selectedOptions[0]?.textContent||'';
  const files=[...chosen],model=root.querySelector('#inspect-model').value,target=root.querySelector('#inspect-target').value,threshold=Number(root.querySelector('#inspect-threshold').value);
  if(!Number.isFinite(threshold)||threshold<0||threshold>1)return notify('점수 기준은 0~1입니다.');
  busy=true;root.querySelector('#inspect-run').disabled=true;results=[];shown=20;active=0;render();
  root.querySelectorAll('#inspect-files,#inspect-clear,#inspect-model,#inspect-threshold,[data-inspect-target]').forEach(x=>x.disabled=true);
  try{
   const ids=[];
   for(let i=0;i<files.length;i++){
    notify(`테스트 이미지 준비 · ${i+1}/${files.length}`);
    const r=await fetch(base+'/images',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Studio-Test':'1'},body:files[i]});const value=await readResponse(r);ids.push(value.id);
   }
   const job=await api('/jobs',{model_id:model,target,threshold,images:ids});let state;
   do{await new Promise(r=>setTimeout(r,1000));state=await api('/jobs/'+job.id);notify(state.message);}
   while(state.status==='running');
   if(state.status!=='complete')throw Error(state.message);
   classes=state.classes;results=state.results.map((r,i)=>({...r,name:files[i].name,image_id:ids[i]}));render();
   notify(`완료 ${results.length}장 · 준비/모델 로딩 ${state.load_seconds.toFixed(1)}초 · 전체 ${state.total_seconds.toFixed(1)}초`);
  }catch(e){notify(e.message||'검사 실패');}
  finally{busy=false;const button=root.querySelector('#inspect-run');if(button)button.disabled=false;root.querySelectorAll('#inspect-files,#inspect-clear,#inspect-model,#inspect-threshold,[data-inspect-target]').forEach(x=>x.disabled=false);render();}
 };
 render();
}
