import {openEditor, closeEditor} from './editor.js';
import {shortcutActions,eventShortcut,resolvedShortcuts,validateShortcuts,shortcutLabel} from './shortcuts.js';

export const icons = {
 grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
 board:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16m6-16v16M5.5 8h1m5 0h1m5 0h1"/>',
 image:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-7 5 8"/>',
 upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/>',
 layers:'<path d="m12 3 10 5-10 5L2 8Zm-9 10 9 5 9-5M3 18l9 5 9-5"/>',
 tag:'<path d="M3 3h8l10 10-8 8L3 11Z"/><circle cx="7.5" cy="7.5" r="1"/>',
 train:'<rect x="6" y="6" width="12" height="12" rx="3"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4"/>',
 model:'<path d="m12 3 9 5v9l-9 5-9-5V8Zm0 9 9-4m-9 4L3 8m9 4v10"/>',
 settings:'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="var(--surface)"/><circle cx="15" cy="17" r="3" fill="var(--surface)"/>',
 trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
 search:'<circle cx="10.5" cy="10.5" r="7"/><path d="m16 16 5 5"/>',
 arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
 chevron:'<path d="m9 5 7 7-7 7"/>',
 check:'<path d="m5 12 4 4L19 6"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 close:'<path d="m6 6 12 12M6 18 18 6"/>',
 sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
 download:'<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/>',
 polygon:'<path d="m5 5 13-2 4 12-10 7-9-8Z"/>',
 box:'<rect x="3" y="5" width="18" height="14" rx="1"/>',
 pointer:'<path d="m5 3 14 10-7 1-3 7Z"/>',
 undo:'<path d="m8 4-5 5 5 5M3 9h11a6 6 0 0 1 0 12"/>',
 save:'<path d="M4 3h13l4 4v14H3V3Zm3 0v7h10V3M7 21v-7h10v7"/>',
 eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
};
export const icon=(name,cls='')=>`<svg class="ico ${cls}" viewBox="0 0 24 24" aria-hidden="true">${icons[name]||icons.grid}</svg>`;
export const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const num=v=>Number(v||0).toLocaleString('ko-KR');
export const date=v=>v?new Date(v).toLocaleString('ko-KR',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Seoul'}):'—';
export const btn=(text,action,ico='',style='')=>`<button class="btn ${style}" data-action="${action}">${ico?icon(ico):''}${text}</button>`;
export async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json();if(!r.ok)throw Error(j.error||'요청 실패');return j;}
let toastTimer;
export function toast(message,error=false){const el=document.querySelector('#toast');el.textContent=message;el.className='visible'+(error?' error':'');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.className='',4500);}
export function modal(title,content){const el=document.querySelector('#modal');el.dataset.view='';document.querySelector('#modal-body').innerHTML=`<div class="modalhead"><h2>${esc(title)}</h2><button class="iconbtn" data-action="close-modal" aria-label="닫기">${icon('close')}</button></div>${content}`;if(!el.open)el.showModal();}
async function copyJobLog(){
 const el=document.querySelector('#job-log-text');if(!el)return;
 try{await navigator.clipboard.writeText(el.textContent);toast('작업 로그를 복사했습니다');}
 catch{const range=document.createRange();range.selectNodeContents(el);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);toast('자동 복사에 실패했습니다. 선택된 로그를 Ctrl+C로 복사하세요',true);}
}
export function closeModal(){document.querySelector('#modal').close();}
export let state;
let route='',params=new URLSearchParams(),selected=new Set(),splitPreview=null,renderToken=0;
let trainingDraft=null,pendingTrainingVersion=null,uploading=false,uploadDraft=null,uploadResultHtml='';
const stages={new:'새로 올림',labeling:'라벨링 중',review:'검수',done:'완료'};
const statuses={todo:'검수 전',reviewed:'검수 완료',ambiguous:'애매',auto:'자동 라벨',ai_reviewed:'AI 검수'};
const jobNames={running:'진행 중',queued:'대기',completed:'완료',failed:'실패',interrupted:'중단됨',cancelled:'취소됨'};
const nav=[['','대시보드','grid'],['board','보드 · 사진 추가','board'],['images','전체 사진','image'],['|'],['train','버전 · 분할 · 학습','train'],['models','모델 · 자동 라벨','model'],['test','이미지 테스트','image'],['|'],['settings','설정','settings'],['trash','휴지통','trash']];
const activeImages=()=>state.images.filter(x=>!x.deleted);
const activeModels=()=>state.models.filter(x=>!x.deleted);
const classOf=id=>state.classes.find(x=>x.id===id);
const badge=(text,type='')=>`<span class="badge ${type}">${esc(text)}</span>`;
const label=(text,control,full=false)=>`<label class="field ${full?'full':''}">${text}${control}</label>`;
const input=(name,value='',type='text',extra='')=>`<input name="${name}" type="${type}" value="${esc(value)}" ${extra}>`;
const select=(name,options,value='',extra='')=>`<select name="${name}" ${extra}>${options.map(([v,t])=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(t)}</option>`).join('')}</select>`;
const check=(name,text,checked=false)=>`<label class="checkline"><input type="checkbox" name="${name}" ${checked?'checked':''}>${text}</label>`;
const options=items=>items.map(x=>[x.id,x.name]);
const empty=(title,text='',action='')=>`<div class="empty">${icon('layers')}<b>${esc(title)}</b><p>${esc(text)}</p>${action}</div>`;
function head(title,sub,action='',section='WORKSPACE'){return `<div class="pagehead"><div><div class="eyebrow">${section}</div><h1>${title}</h1><p>${sub}</p></div><div class="actions">${action}</div></div>`;}
let gpuSnapshot=null,gpuRequestPending=false;
function gpuStatus(data=gpuSnapshot){
 if(!data?.available)return `<a class="gpu-telemetry muted" href="#/settings">${esc(data?.reason||'GPU 상태 확인 중')}</a>`;
 return data.gpus.map(g=>{const pct=g.utilization===null?'—':Math.round(g.utilization)+'%',used=g.memory_used_mib===null?'—':(g.memory_used_mib/1024).toFixed(1),total=g.memory_total_mib===null?'—':(g.memory_total_mib/1024).toFixed(1),temp=g.temperature===null?'—':Math.round(g.temperature)+'°C';return `<span class="gpu-telemetry ${data.stale?'muted':''}" title="${esc(g.name)} · 서버 전체 사용량${data.stale?' · 갱신 지연':''}"><span>서버 GPU <b>${pct}</b></span><span>VRAM <b>${used} / ${total} GiB</b></span><span>${temp}</span>${data.stale?'<span>갱신 지연</span>':''}</span>`;}).join('');
}
async function refreshGPU(){
 if(gpuRequestPending||document.hidden)return;
 gpuRequestPending=true;
 try{gpuSnapshot=await api('/api/gpu');}catch{gpuSnapshot=gpuSnapshot?.available?{...gpuSnapshot,stale:true}:{available:false,reason:'GPU 상태 확인 불가'};}
 finally{gpuRequestPending=false;const el=document.querySelector('#gpu-status');if(el)el.innerHTML=gpuStatus();}
}
function header(){
 const jobs=state.jobs.filter(j=>['running','queued'].includes(j.status)).length;
 document.querySelector('#header').innerHTML=`<div class="brandbar"><a class="brand" href="#/"><span class="brandmark">d</span><span class="brandname">dxel <span>Studio</span></span><span class="workspace">${esc(state.settings.project_name||"케이블 표면 검사")}</span></a><div class="header-actions"><div id="gpu-status">${gpuStatus()}</div><span class="connection"><span class="dot ${state.connection.demo?'amber':''}"></span>${state.connection.demo?'샘플 데이터 · DB 연결 전':'로컬 작업 공간'}</span><button class="btn small" data-action="jobs">${icon('clock','small')}작업 센터 ${jobs?badge(jobs,'blue'):''}</button><button class="iconbtn" data-action="theme" aria-label="밝게/어둡게 바꾸기">${icon('sun')}</button><a class="avatar" href="#/settings" aria-label="설정">신</a></div></div><div class="navwrap"><nav class="topnav" aria-label="주 메뉴">${nav.map(([id,text,ico])=>id==='|'?'<span class="navsep"></span>':`<a href="#/${id}" class="${(route.split('/')[0]===id||route.startsWith('annotate')&&id==='images')?'active':''}" ${route===id?'aria-current="page"':''}>${icon(ico)}${text}</a>`).join('')}</nav></div>`;
}
export async function refresh(render=true){if(render)await closeEditor();state=await api('/api/state');await syncValidationProgress();header();syncJobCenter();if(render)await renderPage();}
function setQuery(changes){const q=new URLSearchParams(params);Object.entries(changes).forEach(([k,v])=>v?q.set(k,v):q.delete(k));q.delete('page');location.hash='/'+route+(q.size?'?'+q:'');}
export function goImage(id){location.hash='/annotate/'+encodeURIComponent(id);}
function summaryCount(list,key,value){return list.filter(x=>x[key]===value).length;}
function thumb(x,labels=true){return `<img src="/media/${esc(x.file)}" alt="${esc(x.name)}" loading="lazy">${labels&&x.annotations.length?`<svg viewBox="0 0 ${x.width} ${x.height}" preserveAspectRatio="xMidYMid meet">${x.annotations.map(a=>`<polygon points="${a.points.map(p=>p.join(',')).join(' ')}" fill="${classOf(a.class_id)?.color||'#888'}22" stroke="${classOf(a.class_id)?.color||'#888'}" stroke-width="3"/>`).join('')}</svg>`:''}`;}
function dashboard(){
 const images=activeImages(),reviewed=summaryCount(images,'status','reviewed'),labeled=images.filter(x=>x.annotations.length).length;
 const counts=[['전체 사진',images.length,'장','image',`${state.batches.length}개의 배치`],['라벨 있음',labeled,'장','tag',images.length?`전체의 ${Math.round(labeled/images.length*100)}%`:'사진을 추가해 시작하세요'],['검수 완료',reviewed,'장','check',images.length?`전체의 ${Math.round(reviewed/images.length*100)}%`:'검수한 사진이 여기에 표시됩니다'],['데이터셋 버전',state.versions.length,'개','layers',state.versions.at(-1)?.name||'아직 만든 버전 없음']];
 const tasks=[['ambiguous','애매한 사진','판단이 필요한 사진을 다시 확인하세요','amber'],['auto','자동 라벨 검수','모델이 붙인 라벨을 확인하세요',''],['todo','검수 전 사진','라벨을 확인하고 학습 데이터를 완성하세요','green']];
 const split=['train','valid','test'].map(s=>summaryCount(images,'split',s)),splitTotal=split.reduce((a,b)=>a+b,0);
 const countsByClass=state.classes.map(c=>({...c,count:images.reduce((n,x)=>n+x.annotations.filter(a=>a.class_id===c.id).length,0)}));const max=Math.max(...countsByClass.map(x=>x.count),1);
 const model=activeModels().find(x=>x.active);
 const recent=[...state.batches].reverse().slice(0,4);
 return head('대시보드','사진에서 학습까지, 작업 현황을 한눈에 확인하세요.',`<a class="btn primary" href="#/board?upload=1">${icon('plus')}사진 추가</a>`,'OVERVIEW')+
 `<div class="stats">${counts.map(([t,n,u,i,sub])=>`<div class="card stat"><div><label>${t}</label><div class="num metric">${num(n)}<span class="unit">${u}</span></div><small>${esc(sub)}</small></div><span class="stat-icon">${icon(i)}</span></div>`).join('')}</div>
 <div class="dashgrid"><div class="stack"><section class="card pad"><div class="cardhead"><div><h2>지금 할 일</h2><p>확인이 필요한 사진부터 이어서 작업하세요</p></div>${badge('WORK QUEUE')}</div>${tasks.map(([s,t,sub,c])=>`<a class="taskrow" href="#/images?status=${s}"><span class="taskbadge ${c}">${icon(s==='ambiguous'?'eye':s==='auto'?'model':'check')}</span><div class="taskbody"><b>${t}</b><p>${sub}</p></div><span class="taskcount">${num(summaryCount(images,'status',s))}</span>${icon('chevron')}</a>`).join('')}</section>
 <section class="card pad"><div class="cardhead"><div><h2>클래스별 라벨</h2><p>클래스의 분포와 검수 현황을 살펴보세요</p></div><a class="textlink" href="#/settings?section=classes">클래스 관리 ${icon('arrow','small')}</a></div><div class="tablewrap"><table class="table"><thead><tr><th>클래스</th><th>라벨 수</th><th style="width:35%">분포</th><th>구분</th></tr></thead><tbody>${countsByClass.map(c=>`<tr><td><a href="#/images?cls=${c.id}"><i class="swatch" style="background:${c.color}"></i>${esc(c.name)}</a></td><td class="metric">${num(c.count)}</td><td><div class="classbar"><span style="width:${c.count/max*100}%;background:${c.color}"></span></div></td><td>${badge(c.normal?'정상 요소':'결함',c.normal?'green':'')}</td></tr>`).join('')}</tbody></table></div></section></div>
 <div class="stack"><section class="card darkcard pad"><div class="row between"><div class="eyebrow" style="margin:0">ACTIVE MODEL</div>${badge('RTMDet-Ins')}</div><h3>${model?esc(model.name):'학습할 준비가 되면'}</h3><p class="model-placeholder">${model?`RTMDet-Ins ${model.size.toUpperCase()} · 마스크 기반 표면 검사`:'데이터셋을 고정하고<br>RTMDet-Ins 모델을 학습하세요.'}</p><div class="divider" style="background:#ffffff20"></div><div class="row between"><span class="mlstatus"><span class="dot ${state.connection.ml.ready?'':'amber'}"></span>${state.connection.ml.ready?'학습 환경 연결됨':'학습 환경 연결 대기'}</span><a class="btn small" href="#/train">학습으로 ${icon('arrow','small')}</a></div></section>
 <section class="card pad"><div class="cardhead"><h2>데이터 분할</h2><a class="textlink" href="#/train">버전 관리 ${icon('arrow','small')}</a></div><div class="row between"><span class="smalltext muted">분할된 사진</span><b class="metric">${num(splitTotal)} <span class="tiny muted">/ ${num(images.length)}장</span></b></div><div class="segmentedbar">${split.map(n=>`<span style="width:${n/Math.max(splitTotal,1)*100}%"></span>`).join('')}</div><div class="legend">${split.map((n,i)=>`<span><i style="background:${['#5a78d7','#7db2a8','#c9d2e8'][i]}"></i>${['train','valid','test'][i]} <b>${num(n)}</b></span>`).join('')}</div></section>
 <section class="card pad"><div class="cardhead"><h2>최근 배치</h2><a class="textlink" href="#/board">보드 보기 ${icon('arrow','small')}</a></div>${recent.length?recent.map(b=>{const xs=images.filter(x=>x.batch===b.id);return `<a class="batchrow" href="#/images?batch=${b.id}">${xs[0]?`<img src="/media/${xs[0].file}" alt="" loading="lazy">`:`<span class="taskbadge">${icon('image')}</span>`}<div class="info"><b>${esc(b.name)}</b><small>${num(xs.length)}장 · ${date(b.created)}</small></div>${badge(stages[b.stage],b.stage==='done'?'green':'')}</a>`;}).join(''):empty('아직 배치가 없습니다','사진을 추가하면 배치가 만들어집니다')}</section></div></div>
 <section class="card pad" style="margin-top:22px"><div class="cardhead"><h2>최근 변경</h2><span class="tiny muted">최근 ${Math.min(state.events.length,5)}개 기록</span></div>${state.events.length?state.events.slice(0,5).map(x=>`<div class="activity"><span class="point"></span><div><p>${esc(x.action)} <span class="muted">· ${esc(x.detail)}</span></p><small>${date(x.created)}</small></div></div>`).join(''):empty('아직 변경 기록이 없습니다')}</section><div class="footerline"><span>dxel Studio · 케이블 표면 검사</span><span>${state.connection.demo?'합성 예제 데이터로 기능을 확인하는 중':'사진과 라벨은 로컬 DB에 저장됩니다'}</span></div>`;
}

function filteredImages(trash=false){
 let images=state.images.filter(x=>!!x.deleted===trash),q=(params.get('q')||'').toLowerCase(),status=params.get('status');
 if(status==='labeled')images=images.filter(x=>x.annotations.length);else if(status==='unlabeled')images=images.filter(x=>!x.annotations.length);else if(status)images=images.filter(x=>x.status===status);
 for(const key of ['batch','sensor','split'])if(params.get(key))images=images.filter(x=>x[key]===(params.get(key)==='none'?'':params.get(key)));
 if(params.get('cls'))images=images.filter(x=>x.annotations.some(a=>a.class_id===params.get('cls')));
 if(q)images=images.filter(x=>[x.name,x.note,...x.tags].join(' ').toLowerCase().includes(q));
 images.sort((a,b)=>params.get('sort')==='updated'?b.updated.localeCompare(a.updated):params.get('sort')==='created'?b.created.localeCompare(a.created):a.name.localeCompare(b.name));return images;
}
let lastEditorId=null;
function rememberLastEditor(image){
 if(image.deleted)return;
 lastEditorId=image.id;
 try{localStorage.setItem('studio-last-editor-image',image.id);}catch{}
}
function resumeLabelingButton(){
 let id=lastEditorId;
 if(!id){try{id=localStorage.getItem('studio-last-editor-image');}catch{}}
 const image=state.images.find(x=>x.id===id&&!x.deleted);
 return image?`<a class="btn" href="#/annotate/${encodeURIComponent(image.id)}" title="${esc(image.name)}">${icon('pointer')}이어서 라벨링</a>`:'';
}
let imageListObserver=null,imageListLimit=48,imageListKey='';
function visibleImageLimit(trash=false){
 const key=(trash?'trash':'images')+'?'+params.toString();
 if(key!==imageListKey){imageListKey=key;imageListLimit=Math.max(48,Number(params.get('page')||1)*48||48);}
 return imageListLimit;
}
function imageCard(x,trash=false){return `<article class="card imagecard review-state-${x.status} ${selected.has(x.id)?'selected':''}"><input type="checkbox" class="select-image" data-select="${x.id}" aria-label="${esc(x.name)} 선택" ${selected.has(x.id)?'checked':''}><button class="iconbtn card-delete" data-action="${trash?'image-restore':'image-trash'}" data-id="${x.id}" aria-label="${esc(x.name)} ${trash?'복원':'삭제'}">${icon(trash?'undo':'trash')}</button><a href="#/annotate/${x.id}" class="thumb"><span style="filter:var(--image-filter);display:contents">${thumb(x)}</span>${badge(statuses[x.status],x.status==='reviewed'?'green':x.status==='ambiguous'?'amber':'')}</a><div class="meta"><div class="filename" title="${esc(x.name)}">${esc(x.name)}</div><div class="tags">${badge(x.split||'미배정')}${[...new Set(x.annotations.map(a=>a.class_id))].slice(0,3).map(id=>{const c=classOf(id);return `<span class="badge" style="color:${c?.color}">${esc(c?.name)}</span>`;}).join('')}${!x.annotations.length?'<span class="tiny muted">라벨 없음</span>':''}</div></div></article>`;}
function appendImages(){
 const trash=route==='trash',grid=document.querySelector('.imagegrid'),sentinel=document.querySelector('#image-list-end');
 if(!grid||!sentinel||!['images','trash'].includes(route))return;
 const images=filteredImages(trash),from=visibleImageLimit(trash),to=Math.min(from+48,images.length);
 grid.insertAdjacentHTML('beforeend',images.slice(from,to).map(x=>imageCard(x,trash)).join(''));
 imageListLimit=to;
 const count=document.querySelector('#image-count');if(count)count.textContent=num(images.length)+'장 · '+num(to)+'장 표시';
 const all=document.querySelector('#select-all');if(all){all.checked=to>0&&images.slice(0,to).every(x=>selected.has(x.id));all.indeterminate=images.slice(0,to).some(x=>selected.has(x.id))&&!all.checked;}
 if(to>=images.length){imageListObserver?.disconnect();sentinel.remove();}
}
function observeImageList(){
 const sentinel=document.querySelector('#image-list-end');if(!sentinel)return;
 imageListObserver=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting))appendImages();},{rootMargin:'400px 0px'});
 imageListObserver.observe(sentinel);
}
function imageStatusHref(status){
 const query=new URLSearchParams(params);
 if(status)query.set('status',status);else query.delete('status');
 query.delete('page');
 return '#/images'+(query.size?'?'+query.toString():'');
}
function imagesPage(trash=false){
 const images=filteredImages(trash),limit=visibleImageLimit(trash);
 return head(trash?'휴지통':'전체 사진',trash?'삭제한 사진과 모델을 확인하고 복원할 수 있습니다.':'사진을 골라 보고, 라벨을 붙이고, 여러 장을 한 번에 관리하세요.',trash?'':resumeLabelingButton()+btn('같은 사진 찾기','duplicates','search')+`<a class="btn primary" href="#/board?upload=1">${icon('plus')}사진 추가</a>`,'DATA LIBRARY')+
 (trash?trashTabs():'')+
 (!trash?`<div class="pills">${[['','전체'],['todo','할 일'],['reviewed','검수 완료'],['ambiguous','애매'],['auto','자동 라벨'],['unlabeled','라벨 없음']].map(([v,t])=>`<a href="${esc(imageStatusHref(v))}" class="${(params.get('status')||'')===v?'active':''}">${t}</a>`).join('')}</div>`:'')+
 `<form data-form="filters" class="filters"><label class="searchfield">${icon('search')}<input name="q" aria-label="이름·메모 검색" placeholder="이름·메모·태그 검색" value="${esc(params.get('q'))}"></label>${select('cls',[['','모든 클래스'],...options(state.classes)],params.get('cls'), 'aria-label="클래스 필터"')}${select('sensor',[['','모든 센서'],...['A','B','C','D','E','F'].map(x=>[x,'센서 '+x])],params.get('sensor'),'aria-label="센서 필터"')}${select('split',[['','모든 분할'],['none','미배정'],['train','train'],['valid','valid'],['test','test']],params.get('split'),'aria-label="분할 필터"')}${select('batch',[['','모든 배치'],...options(state.batches)],params.get('batch'),'aria-label="배치 필터"')}${select('sort',[['','이름순'],['updated','최근 수정'],['created','최근 추가']],params.get('sort'),'aria-label="정렬"')}${select('view',[['','원본 보기'],['gray','흑백'],['contrast','흑백 + 대비'],['invert','반전']],params.get('view'),'aria-label="사진 보기"')}<button class="btn" type="submit">검색</button></form>
 <div class="row between" style="margin-bottom:15px"><span id="image-count" class="tiny muted">${num(images.length)}장${images.length>48?' · '+Math.min(limit,images.length)+'장 표시':''}</span><label class="checkline" style="margin:0"><input type="checkbox" id="select-all" ${images.slice(0,limit).length&&images.slice(0,limit).every(x=>selected.has(x.id))?'checked':''}>현재 화면 전체 선택</label></div>
 ${images.length?`<div class="imagegrid ${selected.size?'selecting':''}" style="--image-filter:${({gray:'grayscale(1)',contrast:'grayscale(1) contrast(1.6)',invert:'invert(1)'})[params.get('view')]||'none'}">${images.slice(0,limit).map(x=>imageCard(x,trash)).join('')}</div>`:empty(trash?'휴지통에 사진이 없습니다':'조건에 맞는 사진이 없습니다',trash?'사진을 삭제하면 이곳에서 복원할 수 있습니다.':'필터를 바꾸거나 새로운 사진을 추가하세요.',!trash?'<a class="btn primary" href="#/board?upload=1">사진 추가</a>':'')}
 ${images.length>limit?'<div id="image-list-end" aria-label="다음 사진 자동 불러오기" style="height:2px;margin-top:24px"></div>':''}<div id="bulkbar">${bulkbar(trash)}</div>`;
}
function trashTabs(){return `<div class="pills" aria-label="휴지통 종류"><a href="#/trash" class="${params.get('type')!=='models'?'active':''}">사진 ${num(state.images.filter(x=>x.deleted).length)}</a><a href="#/trash?type=models" class="${params.get('type')==='models'?'active':''}">모델 ${num(state.models.filter(x=>x.deleted).length)}</a></div>`;}
function trashedModelsPage(){const models=state.models.filter(x=>x.deleted);return head('휴지통','삭제한 사진과 모델을 확인하고 복원할 수 있습니다.','','DATA LIBRARY')+trashTabs()+`<section class="card">${models.length?`<div class="tablewrap"><table class="table"><thead><tr><th>모델</th><th>종류</th><th>삭제한 때</th><th></th></tr></thead><tbody>${models.map(m=>`<tr><td><div class="modelname">${esc(m.name)}</div></td><td>RTMDet-Ins ${m.size.toUpperCase()}</td><td>${date(m.deleted_at)}</td><td><button class="btn small" data-action="model-restore" data-id="${m.id}" aria-label="${esc(m.name)} 복원">${icon('undo','small')}복원</button></td></tr>`).join('')}</tbody></table></div>`:empty('휴지통에 모델이 없습니다','모델을 삭제하면 이곳에서 복원할 수 있습니다.')}</section><p class="tiny muted">체크포인트와 학습 설정 파일은 보존됩니다. 복원한 모델은 모델 목록에서 다시 선택해 사용하세요.</p>`;}
function bulkbar(trash){return selected.size?`<div class="bulkbar"><b class="smalltext">${selected.size}장 선택</b>${btn('선택 해제','deselect','','small')}${trash?btn('복원','restore','undo','small'):`${btn('검수 완료','review','check','small')}${btn('애매 표시','ambiguous','eye','small')}${select('bulk-split',[['','분할 변경'],['none','미배정'],['train','train'],['valid','valid'],['test','test']],'','aria-label="선택한 사진 분할 변경"')}${select('bulk-batch',[['','배치 이동'],...options(state.batches)],'','aria-label="선택한 사진 배치 이동"')}${btn('태그 추가','bulk-tags','tag','small')}${btn('자동 라벨','bulk-predict','model','small')}${btn('휴지통','trash','trash','small')}`}</div>`:'';}
function uploadPanel(){return `<section class="card pad"><div class="cardhead"><div><h2>사진 추가</h2><p>올린 사진은 새 배치로 바로 나타납니다.</p></div></div><form data-form="upload-meta" id="upload-meta"><div class="formgrid three">${label('배치 이름',input('batch','','text','placeholder="비우면 자동 생성"'))}${label('태그',input('tags','','text','placeholder="쉼표로 구분"'))}${label('분할',select('split',[['','미배정 · 나중에 자동 분할'],['train','train'],['valid','valid'],['test','test']]))}</div>${check('allow_duplicates','중복 사진도 새 사진으로 추가')}</form><div class="dropzone" id="dropzone">${icon('upload')}<div><p><b>사진을 여기에 끌어다 놓으세요</b></p><p class="tiny muted" style="margin-top:6px">JPG · PNG · WEBP · BMP / 파일당 최대 80MB</p></div><label class="btn primary" for="files">${icon('plus')}파일 고르기</label><input id="files" type="file" accept="image/jpeg,image/png,image/webp,image/bmp" multiple hidden></div><div id="upload-results" aria-live="polite">${uploadResultHtml}</div><div class="hint">같은 이름이나 같은 내용의 사진은 중복으로 추가하지 않습니다. 원본 크기를 그대로 보관합니다.</div></section>`;}
function boardColumns(){const images=activeImages(),occupied=new Set(images.map(x=>x.batch)),showEmpty=params.get('empty')==='1';return `<div class="kanban">${Object.entries(stages).map(([key,title],i)=>{const batches=state.batches.filter(b=>b.stage===key&&(showEmpty||occupied.has(b.id)));return `<section class="kanban-column" data-stage="${key}" aria-label="${title}"><div class="columnhead"><span><i class="swatch" style="background:${['#98a6bd','#7088d5','#d3ad69','#6aa18c'][i]}"></i>${title} <small>${batches.length}</small></span><small>0${i+1}</small></div>${batches.map(b=>{const xs=images.filter(x=>x.batch===b.id),review=xs.filter(x=>x.status==='reviewed').length;return `<article class="card boardcard" draggable="true" data-batch="${b.id}"><div class="row between"><h3><a href="#/images?batch=${b.id}">${esc(b.name)}</a></h3><button class="iconbtn" data-action="rename-batch" data-id="${b.id}" aria-label="${esc(b.name)} 이름 변경">···</button></div><span class="tiny muted">${num(xs.length)}장 · ${date(b.created)}</span><a class="previews" href="#/images?batch=${b.id}">${xs.slice(0,3).map(x=>`<img src="/media/${x.file}" alt="" loading="lazy">`).join('')}</a><div class="row between tiny muted"><span>검수 ${num(review)} / ${num(xs.length)}</span><span>${Math.round(review/Math.max(xs.length,1)*100)}%</span></div><div class="progress" style="margin-top:7px"><span style="width:${review/Math.max(xs.length,1)*100}%"></span></div>${select('stage',Object.entries(stages),b.stage,`data-stage-select="${b.id}" aria-label="${esc(b.name)} 단계"`)}</article>`;}).join('')||'<div class="empty tiny">여기로 배치를 끌어 놓으세요</div>'}</section>`;}).join('')}</div>`;}
function boardPage(){return head('보드 · 사진 추가','사진을 추가하고, 배치를 옮기며 작업을 이어가세요.',`<a class="btn" href="#/board${params.get('empty')==='1'?'':'?empty=1'}">${params.get('empty')==='1'?'빈 배치 숨기기':'빈 배치 보기'}</a>`+btn('배치 합치기','merge-batches','layers')+btn('새 배치','new-batch','plus','primary'),'WORKFLOW')+`<div class="board-workspace"><section class="board-lanes" aria-label="배치 보드"><div id="board-columns">${boardColumns()}</div></section><aside class="board-upload" aria-label="사진 추가">${uploadPanel()}</aside></div>`;}
function classesSection(){return `<div id="class-settings" style="margin-top:26px"><div class="cardhead"><h2>클래스 관리</h2>${btn('클래스 추가','new-class','plus','primary')}</div>`+`<section class="card"><div class="tablewrap"><table class="table"><thead><tr><th>클래스</th><th>구분</th><th>단축키</th><th>라벨 수</th><th></th></tr></thead><tbody>${state.classes.map(c=>`<tr><td><i class="swatch" style="background:${c.color}"></i>${esc(c.name)}</td><td>${badge(c.normal?'정상 요소':'결함',c.normal?'green':'')}</td><td><kbd>${esc(c.shortcut)||'—'}</kbd></td><td>${num(activeImages().reduce((n,x)=>n+x.annotations.filter(a=>a.class_id===c.id).length,0))}</td><td><button class="btn small" data-action="edit-class" data-id="${c.id}">수정</button></td></tr>`).join('')}</tbody></table></div></section><p class="tiny muted" style="margin-top:15px">물방울(water)과 인쇄·각인(SerialNumber)은 정상 요소로 표시합니다. 기존 버전의 클래스는 변경되지 않습니다.</p></div>`;}
function classForm(c={}){modal(c.id?'클래스 수정':'클래스 추가',`<form data-form="class"><input type="hidden" name="id" value="${esc(c.id)}"><div class="formgrid">${label('이름',input('name',c.name||'','text','required maxlength="80"'))}${label('단축키',input('shortcut',c.shortcut||'','text','maxlength="1"'))}${label('색상',input('color',c.color||'#6881ab','color'))}</div>${check('normal','정상 요소 · 결함으로 집계하지 않음',c.normal)}<div class="actions" style="margin-top:22px"><button class="btn primary">저장</button></div></form>`);}
function trainBatchChoices(){
 const counts=new Map();for(const x of activeImages())if(x.split==='train'&&!['auto','ai_reviewed','ambiguous'].includes(x.status))counts.set(x.batch,(counts.get(x.batch)||0)+1);
 const batches=state.batches.filter(b=>b.stage==='done'&&counts.has(b.id));
 return batches.length?batches.map(b=>`<label class="checkline"><input type="checkbox" name="train_batches" value="${esc(b.id)}">${esc(b.name)} <span class="muted">· train 최대 ${num(counts.get(b.id))}장</span></label>`).join(''):'<p class="tiny muted">train 사진이 있는 완료 배치가 없습니다. 보드에서 완료로 옮긴 뒤 확인하세요.</p>';
}
function versionBatchUsage(v){
 const used=(v.batch_snapshot||[]).filter(b=>b.counts.train>0);if(!used.length)return '';
 return `<details style="margin:12px 0"><summary class="tiny muted">사용한 완료 train 배치 ${used.length}개</summary>${used.map(b=>`<p class="tiny muted">${esc(b.name)} · train ${num(b.counts.train)}장</p>`).join('')}</details>`;
}
function versionsPanel(){const versionRows=[...state.versions].reverse();return `<div class="split-grid"><section class="card pad"><div class="cardhead"><div><h2>새 버전 만들기</h2><p>현재 라벨 상태를 고정합니다. 이후의 편집은 버전에 영향을 주지 않습니다.</p></div></div><form data-form="version"><div class="formgrid">${label('이름',input('name','','text',`placeholder="v${state.versions.length+1}"`))}${label('메모',input('note','','text','placeholder="무엇을 바꿨는지"'))}</div><input type="hidden" name="done_only" value="true"><p class="tiny muted"><b>보드의 완료 배치만 사용합니다.</b> 검수·라벨링 중·새로 올림은 제외됩니다.</p>${check('exclude_ambiguous','애매한 사진 제외',true)}${check('reviewed_only','사람이 검수 완료한 사진만 포함')}${check('include_background','라벨 없는 정상 배경 사진 포함',true)}<details style="margin:14px 0"><summary class="tiny muted">train에 사용할 배치 선택</summary><p class="tiny muted">선택하지 않으면 완료 배치 전체의 train 사진만 사용합니다. 선택하면 해당 완료 배치의 train만 사용하고, valid·test는 선택 여부에 따라 줄이지 않습니다.</p>${trainBatchChoices()}</details><p class="tiny muted">미배정 사진과 사람이 검수하지 않은 자동 라벨은 제외됩니다.</p><button class="btn primary">${icon('layers')}버전 만들기</button></form></section>
 <section class="card pad"><div class="cardhead"><div><h2>자동 분할</h2><p>연속 촬영한 사진은 같은 세트에 묶습니다.</p></div>${badge('SEED 42')}</div><form data-form="split" id="split-form"><div class="formgrid three">${label('train %',input('train',70,'number','min="0" max="100" required'))}${label('valid %',input('valid',20,'number','min="0" max="100" required'))}${label('test %',input('test',10,'number','min="0" max="100" required'))}${label('대상',select('scope',[['done','완료 배치의 미배정 사진'],['unassigned','미배정 사진 전체'],['all','전체 다시 나누기']]))}${label('연속 촬영 간격 (초)',input('gap',10,'number','min="0" max="86400"'))}</div><div class="actions" style="margin-top:20px"><button class="btn" name="operation" value="preview">미리 보기</button><button class="btn primary" name="operation" value="apply" id="apply-split" disabled>분할 적용</button></div><div id="split-preview" style="margin-top:15px"></div></form><p class="tiny muted">원본 단위로 먼저 분할합니다. 기존 버전의 분할은 그대로 유지됩니다.</p></section></div>
 <div class="row between" style="margin-top:30px"><h2 style="font-size:16px">버전 목록</h2><span class="tiny muted">${num(state.versions.length)}개 버전</span></div>${versionRows.length?versionRows.map((v,i)=>`<article class="card versioncard"><div class="row between"><div class="row"><h3>${esc(v.name)}</h3>${i===0?badge('최신','blue'):''}<span class="tiny muted">${date(v.created)}</span></div><span class="smalltext">총 ${num(Object.values(v.counts).reduce((a,b)=>a+b,0))}장</span></div>${v.note?`<p>${esc(v.note)}</p>`:''}${versionBatchUsage(v)}<div class="splitnums">${['train','valid','test'].map(k=>`<div><small>${k}</small><b class="metric">${num(v.counts[k])}</b></div>`).join('')}</div><div class="actions"><a class="btn small" href="/api/versions/${v.id}/export?format=coco">${icon('download','small')}COCO 라벨</a><a class="btn small" href="/api/versions/${v.id}/export?format=yolo">YOLO 세그먼트 라벨</a><a class="btn small" href="/api/versions/${v.id}/export?format=coco&images=1">사진 포함 ZIP</a>${versionRows[i+1]?`<button class="btn small" data-action="compare-version" data-id="${v.id}" data-with="${versionRows[i+1].id}">${esc(versionRows[i+1].name)}와 비교</button>`:''}</div></article>`).join(''):empty('아직 버전이 없습니다','사진을 분할한 뒤 첫 버전을 만들어 보세요.')}`;}
function trainingForm(){return `<section class="card pad" id="training-form" style="margin-bottom:22px"><div class="cardhead"><h2>새 학습</h2>${badge('RTMDet-Ins · MMDetection','blue')}</div><form data-form="training"><fieldset class="formsection"><legend><span>1</span>학습 방식 · 데이터</legend><div class="formgrid">${label('학습 방식',select('start_mode',[['finetune','기존 모델에서 추가 학습 · 빠름'],['scratch','새 모델을 처음부터 학습']],activeModels().length?'finetune':'scratch'))}${label('데이터셋 버전',select('version_id',[['','버전 선택'],...options([...state.versions].reverse())]),false)}</div><div data-existing-model hidden style="margin-top:14px">${label('추가 학습할 내 모델',select('resume_model',[['','모델을 선택하세요'],...activeModels().map(m=>{const score=m.evaluations?.[m.version_id]?.metrics?.['coco/segm_mAP_50']??m.metrics?.best_mask_mAP50;return [m.id,m.name+' · '+(state.versions.find(v=>v.id===m.version_id)?.name||m.version_name||'외부 모델')+' · valid mAP50 '+(typeof score==='number'?score.toFixed(3):'평가 전')];})],'','disabled'))}<p class="tiny muted">앞쪽 특징층은 유지하고 뒤쪽 층과 마스크를 추가 학습합니다. 기존 정상·결함도 포함한 버전을 선택하세요.</p></div></fieldset><fieldset class="formsection"><legend><span>2</span>모델</legend><div class="formgrid three">${label('모델 종류','<input value="RTMDet-Ins · 마스크" readonly aria-label="모델 종류">')}${label('모델 크기',select('size',[['s','S · 빠름'],['m','M'],['l','L · 기본'],['x','X · 가장 큼']],'l'))}${label('입력 크기',select('input_size',[['640x1536','640 × 1536'],['704x1472','704 × 1472'],['1024x1024','1024 × 1024'],['768x768','768 × 768']]))}</div></fieldset><fieldset class="formsection"><legend><span>3</span>학습 설정</legend><div class="formgrid three">${label('최대 epoch',input('epochs',activeModels().length?20:40,'number','min="1" max="1000" required'))}${label('조기 종료 · 개선 없는 epoch',input('patience',10,'number','min="1" max="200" required'))}${label('배치 크기',input('batch_size',4,'number','min="1" max="64" required'))}${label('학습률',input('lr',.0002,'number','step="any" min="0.000001" max="1" required'))}${label('이름 · 비우면 자동',input('name','','text','placeholder="예: rtmins_v1_l"'))}</div></fieldset><div class="row between"><p class="tiny muted">AMP 학습 · 5 epoch마다 전체 valid 검증 · 마지막 epoch 검증 · 마스크 mAP50 기준 저장</p><button class="btn primary" ${!state.connection.ml.ready||!state.versions.length?'disabled':''}>${icon('train')}학습 시작</button></div></form></section>`;}
const comparedModels=(()=>{try{return new Map(JSON.parse(localStorage.getItem('studio-model-comparison')||'[]').filter(x=>Array.isArray(x)&&typeof x[0]==='string'&&Array.isArray(x[1])).map(([v,ids])=>[v,new Set(ids.filter(id=>typeof id==='string'))]));}catch{return new Map();}})();
function saveComparisonSelections(){try{localStorage.setItem('studio-model-comparison',JSON.stringify([...comparedModels].map(([v,ids])=>[v,[...ids]])));}catch{}}
function comparisonVersion(){
 const latest=[...(state.jobs||[])].filter(j=>j.mode==='eval'&&j.status==='completed').sort((a,b)=>String(b.finished||b.created).localeCompare(String(a.finished||a.created)))[0];
 return params.get('version')||latest?.version_id||[...state.versions].sort((a,b)=>activeModels().filter(m=>m.evaluations?.[b.id]?.metrics).length-activeModels().filter(m=>m.evaluations?.[a.id]?.metrics).length)[0]?.id;
}
function evaluationVersions(m){return Object.keys(m.evaluations||{}).filter(v=>m.evaluations[v]?.metrics);}
function updateEvaluationSummary(){
 const form=document.querySelector('[data-form=evaluate]');if(!form)return;
 const m=state.models.find(m=>m.id===form.elements.namedItem('model_id').value),v=state.versions.find(v=>v.id===form.elements.namedItem('version_id').value);
 document.querySelector('#evaluation-summary').textContent=`${m?.name||''} → ${v?.name||''} · valid ${v?.counts.valid||0}장`;
}
function comparisonChart(){
 const ver=comparisonVersion(),ids=comparedModels.get(ver)||new Set(),selected=activeModels().filter(m=>ids.has(m.id));
 if(!selected.length)return '<p class="tiny muted">비교할 모델을 체크하세요. 같은 평가 데이터로 계산한 점수만 선으로 표시합니다.</p>';
 const models=selected.filter(m=>m.evaluations?.[ver]?.metrics),missing=selected.filter(m=>!m.evaluations?.[ver]?.metrics);
 const metrics=[['coco/segm_mAP_50','마스크 mAP50'],['coco/segm_mAP','마스크 mAP50–95'],['coco/bbox_mAP_50','박스 mAP50']];
 const colors=['#4263eb','#df6832','#159b8a','#9b59b6','#ca4585','#91732b','#267fa7'];
 const valid=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=1;
 const best=metrics.map(([key])=>{const values=models.map(m=>m.evaluations[ver].metrics[key]).filter(valid);return values.length?Math.max(...values):null;});
 const winners=metrics.map(([key,label],j)=>`<div class="metric-winner"><span>${label}</span><strong>${best[j]===null?'자료 없음':(best[j]*100).toFixed(1)+'점 · 최고'}</strong><small>${models.filter(m=>valid(m.evaluations[ver].metrics[key])&&m.evaluations[ver].metrics[key]===best[j]).map(m=>esc(m.name)).join('<br>')}</small></div>`).join('');
 const waiting=missing.map(m=>`<div class="comparison-wait"><b>${esc(m.name)}</b> · 현재 기준의 평가 결과 없음 <button class="btn small" data-action="evaluate-model" data-id="${m.id}">이 기준으로 평가</button>${evaluationVersions(m).map(v=>`<button class="btn small" data-action="view-evaluation" data-id="${m.id}" data-version="${esc(v)}">${esc(state.versions.find(x=>x.id===v)?.name||v)} 결과 보기</button>`).join('')}</div>`).join('');
 const chart=models.length?`<div class="metric-winners">${winners}</div><div class="chart-legend">${models.map((m,i)=>`<span><i class="chart-color" style="background:${colors[i%colors.length]}"></i>${esc(m.name)}</span>`).join('')}</div><svg class="comparison-lines" viewBox="0 0 720 310" role="img" aria-label="선택 모델별 평가 지표 선 그래프">${[0,20,40,60,80,100].map(v=>`<line x1="55" y1="${260-v*2.2}" x2="685" y2="${260-v*2.2}" stroke="var(--border)"/><text x="42" y="${264-v*2.2}" text-anchor="end">${v}</text>`).join('')}${metrics.map(([,label],i)=>`<text x="${130+i*240}" y="292" text-anchor="middle">${label}</text>`).join('')}${models.map((m,i)=>{
 const vals=metrics.map(([key])=>m.evaluations[ver].metrics[key]);
 return vals.map((v,j)=>valid(v)?`${j>0&&valid(vals[j-1])?`<line x1="${130+(j-1)*240}" y1="${260-vals[j-1]*220}" x2="${130+j*240}" y2="${260-v*220}" stroke="${colors[i%colors.length]}" stroke-width="2.5"/>`:''}<circle cx="${130+j*240}" cy="${260-v*220}" r="${v===best[j]?8:5}" stroke="${v===best[j]?'#d69b1f':'none'}" stroke-width="3" fill="${colors[i%colors.length]}"><title>${esc(m.name)} · ${metrics[j][1]} ${(v*100).toFixed(1)}점</title></circle>`:'').join('');
 }).join('')}</svg><div class="tablewrap"><table class="table"><thead><tr><th>선택한 모델</th>${metrics.map(([,label])=>`<th>${label}</th>`).join('')}</tr></thead><tbody>${models.map((m,i)=>`<tr><td style="color:${colors[i%colors.length]}">${esc(m.name)}</td>${metrics.map(([key],j)=>{const v=m.evaluations[ver].metrics[key],win=valid(v)&&v===best[j];return `<td ${win?'class="metric-best" data-best-metric="'+key+'"':''}>${valid(v)?(v*100).toFixed(1):'자료 없음'}${win?' <span class="best-tag">최고</span>':''}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div>`:'';
 return `<div class="comparison-chart" role="region" aria-label="선택 모델 평가 그래프">${waiting}${chart}<p class="tiny muted">가로축은 평가 지표, 세로축은 0–100점(mAP × 100)입니다. 높을수록 좋으며 실제 결함 탐지율(%)과는 다른 지표입니다.</p></div>`;
}
function modelTable(compare=false){
 if(!activeModels().length)return empty('등록된 RTMDet-Ins 모델이 없습니다','학습을 완료하거나 기존 체크포인트를 등록하세요.');
 const ver=compare?comparisonVersion():params.get('version')||state.versions.at(-1)?.id;
 const scoreFor=m=>compare?m.evaluations?.[ver]?.metrics?.['coco/segm_mAP_50']:(m.evaluations?.[m.version_id]?.metrics?.['coco/segm_mAP_50']??m.metrics?.best_mask_mAP50);
 const best=Math.max(...activeModels().map(scoreFor).filter(v=>typeof v==='number'&&Number.isFinite(v)));
 return `<div class="tablewrap"><table class="table"><thead><tr><th>${compare?'비교':'사용'}</th><th>모델</th><th>학습 데이터</th><th>valid 마스크 mAP50</th><th>상태</th><th></th></tr></thead><tbody>${activeModels().map(m=>{const score=scoreFor(m);return `<tr><td>${compare?`<input type="checkbox" data-compare-model="${m.id}" ${comparedModels.get(ver)?.has(m.id)?'checked':''} aria-label="${esc(m.name)} 비교">`:`<input type="radio" name="active-model" value="${m.id}" ${m.active?'checked':''} aria-label="${esc(m.name)} 사용">`}</td><td><div class="modelname">${esc(m.name)}</div><small class="muted">RTMDet-Ins ${m.size.toUpperCase()}</small></td><td>${esc(state.versions.find(v=>v.id===m.version_id)?.name||m.version_name||'외부 등록')}</td><td class="metric ${typeof score==='number'&&Number.isFinite(score)&&score===best?'good':''}">${score!==undefined&&score!==null?Number(score).toFixed(3):(compare?'이 기준 평가 없음':'평가 전')}${compare&&!m.evaluations?.[ver]?.metrics?`<small class="muted" style="display:block">${evaluationVersions(m).map(v=>`<button class="textlink" data-action="view-evaluation" data-id="${m.id}" data-version="${esc(v)}">${esc(state.versions.find(x=>x.id===v)?.name||v)} 결과 보기</button>`).join(' ')||'평가 실행 필요'}</small>`:''}</td><td>${m.active?badge('사용 중','green'):badge('등록됨')}</td><td><div class="actions"><button class="btn small" data-action="model-detail" data-id="${m.id}">자세히</button><button class="btn small" data-action="evaluate-model" data-id="${m.id}">평가</button><a class="btn small" href="/api/models/${m.id}/download?bundle=1">${icon('download','small')}ZIP</a><button class="btn small danger" data-action="model-trash" data-id="${m.id}" aria-label="${esc(m.name)} 삭제">${icon('trash','small')}삭제</button></div></td></tr>`;}).join('')}</tbody></table></div>`;
}
function validationFromLog(text){
 const rows=[...String(text).matchAll(/Epoch\((train|val)\)\s+\[\s*(\d+)\]\[\s*(\d+)\/\s*(\d+)\]/g)];
 const last=rows.at(-1);if(!last||last[1]!=='val')return null;
 return {epoch:Number(last[2]),step:Number(last[3]),total:Number(last[4])};
}
async function syncValidationProgress(){
 await Promise.all(state.jobs.filter(j=>j.status==='running'&&j.mode==='train'&&j.step>0&&!String(j.message).includes('valid 검증')).map(async j=>{
  try{const log=await api(`/api/jobs/${j.id}/log`);j.validation=validationFromLog(log.text);}catch{}
 }));
}
function jobProgress(j){
 const match=String(j.message||'').match(/valid 검증 중 · epoch (\d+) · (\d+)\/(\d+)/);
 const validation=match?{epoch:Number(match[1]),step:Number(match[2]),total:Number(match[3])}:j.validation;
 if(validation)return {percent:Math.min(100,validation.step/Math.max(validation.total,1)*100),label:'valid 검증 '+(validation.step/Math.max(validation.total,1)*100).toFixed(1)+'%',detail:`epoch ${validation.epoch} · valid ${num(validation.step)} / ${num(validation.total)}장 · 전체 학습 ${Number(j.progress)||0}%`};
 const upload=String(j.message||'').match(/GPU 서버로 전송 중 · (\d+)\/(\d+)개 · (\d+)\/(\d+) MB/);
 if(upload){const sent=Number(upload[3]),total=Number(upload[4]),pct=total>0?Math.min(100,sent/total*100):Number(upload[1])/Math.max(Number(upload[2]),1)*100;return {percent:pct,label:'파일 전송 '+pct.toFixed(1)+'%',detail:`${upload[1]} / ${upload[2]}개 · ${sent} / ${total} MB`};}
 if(String(j.message||'').includes('무결성'))return {percent:null,label:'파일 검증 중',detail:'전송 파일 확인 후 GPU 작업을 시작합니다'};
 if(!j.total_steps&&!j.step)return {percent:null,label:j.mode==='train'?'학습 준비 중':j.mode==='eval'?'평가 준비 중':'예측 준비 중',detail:'파일 전송·모델 준비가 끝나면 처리 수가 표시됩니다'};
 return {percent:Math.min(100,Math.max(0,Number(j.progress)||0)),label:(j.mode==='train'?'학습':j.mode==='eval'?'평가':'예측')+' '+(Number(j.progress)||0)+'%',detail:`step ${num(j.step)} / ${j.total_steps?num(j.total_steps):'—'}${j.mode==='train'?' · epoch '+(j.epoch||0):''}`};
}
function jobProgressHtml(j){const p=jobProgress(j);return `<div class="progress ${p.percent===null?'indeterminate':''}"><span style="width:${p.percent===null?35:p.percent}%"></span></div><div class="jobstats"><span>${esc(p.detail)}</span><b>${esc(p.label)}</b></div>`;}
function syncJobCenter(){const dialog=document.querySelector('#modal'),body=document.querySelector('#job-center-content');if(dialog?.open&&dialog.dataset.view==='jobs'&&body){const top=dialog.scrollTop;body.innerHTML=jobsHtml();dialog.scrollTop=top;}}
function jobsHtml(jobs=state.jobs){return jobs.length?[...jobs].reverse().map(j=>`<article class="job"><div class="row between"><h4>${j.mode==='train'?'학습 · ':''}${esc(j.name)}</h4>${badge(jobNames[j.status]||j.status,j.status==='completed'?'green':j.status==='running'?'blue':'')}</div><p>${esc(j.validation?'RTMDet-Ins valid 검증 중':j.message)}</p>${j.status==='running'?jobProgressHtml(j):''}<div class="row between" style="margin-top:12px"><span class="tiny muted">${date(j.created)}</span><div class="actions"><button class="btn small" data-action="job-log" data-id="${j.id}">로그</button>${j.status==='running'?`<button class="btn small danger" data-action="cancel-job" data-id="${j.id}">중단</button>`:''}${j.status==='completed'&&j.mode==='eval'?`<a class="btn small primary" href="#/train?version=${encodeURIComponent(j.version_id)}&model=${encodeURIComponent(state.models.find(m=>j.name==='평가 · '+m.name)?.id||'')}">평가 결과 보기</a>`:''}${j.status==='completed'&&j.mode==='predict'?`<button class="btn small primary" data-action="accept-predictions" data-id="${j.id}">예측 검토</button>`:''}</div></div></article>`).join(''):empty('아직 실행한 작업이 없습니다','학습과 평가의 실제 진행 상황이 여기에 표시됩니다.');}
function trainingPanel(){return (!state.connection.ml.ready?`<div class="hint amber" style="margin-bottom:20px"><span class="dot amber" style="margin-right:8px"></span>${esc(state.connection.ml.reason)} <a class="textlink" href="#/settings">연결 설정</a></div>`:'')+trainingForm()+`<section class="card pad"><div class="cardhead"><div><h2>모델 비교</h2><p>선택 모델을 같은 평가 데이터로 비교합니다.</p></div><label class="field">평가 데이터 · valid ${select('compare-version',state.versions.map(v=>[v.id,v.name+' · valid '+(v.counts.valid||0)+'장']),comparisonVersion())}</label></div><p class="comparison-context">현재 기준: <b>${esc(state.versions.find(v=>v.id===comparisonVersion())?.name||comparisonVersion())}</b> · valid ${num(state.versions.find(v=>v.id===comparisonVersion())?.counts.valid||0)}장</p>${modelTable(true)}<div id="model-comparison">${comparisonChart()}</div></section><section class="card pad" style="margin-top:22px"><div class="cardhead"><h2>학습 · 평가 기록</h2><span class="tiny muted">실제 작업 기록</span></div>${jobsHtml(state.jobs.filter(x=>x.mode!=='predict'))}</section>`;}
function trainingWorkspacePage(){return head('버전 · 분할 · 학습','데이터를 준비하고 같은 화면에서 RTMDet-Ins 학습을 시작하세요.',btn('새 학습','toggle-training','train','primary'),'DATASET & TRAINING')+`<div class="training-workspace"><section class="training-column dataset-column" aria-label="버전과 분할"><div class="workspace-column-title"><h2>버전 · 분할</h2></div>${versionsPanel()}</section><section class="training-column model-column" aria-label="모델 학습"><div class="workspace-column-title"><h2>모델 학습</h2></div>${trainingPanel()}</section></div>`;}
function syncTrainingMode(){
 const form=document.querySelector('[data-form="training"]');if(!form)return;
 const mode=form.elements.namedItem('start_mode'),model=form.elements.namedItem('resume_model'),size=form.elements.namedItem('size');
 if(!mode||!model)return;
 const existing=mode.value==='finetune',panel=form.querySelector?.('[data-existing-model]');if(panel)panel.hidden=!existing;
 model.disabled=!existing;model.required=existing;
 if(size){size.disabled=existing;const chosen=state.models.find(m=>m.id===model.value);if(existing&&chosen)size.value=chosen.size;}
}
function rememberTrainingForm(){const form=document.querySelector('[data-form="training"]');if(form)trainingDraft=Object.fromEntries(new FormData(form));}
function restoreTrainingForm(){const form=document.querySelector('[data-form="training"]');if(!form)return;for(const [name,value] of Object.entries(trainingDraft||{})){const el=form.elements.namedItem(name);if(el&&(el.tagName!=='SELECT'||[...el.options].some(o=>o.value===value)))el.value=value;}if(pendingTrainingVersion){form.elements.namedItem('version_id').value=pendingTrainingVersion;pendingTrainingVersion=null;}syncTrainingMode();}
function importedModelDetails(m){
 if(!m.imported)return '';
 const t=m.training_info||{},rows=Object.entries(m.evaluations||{}).map(([id,e])=>({...e,version_name:e.version_name||state.versions.find(v=>v.id===id)?.name||id}));
 return `<div class="divider"></div><dl class="detail-list"><div><dt>학습 데이터</dt><dd>${esc(m.version_name||'—')}</dd></div><div><dt>학습 설정</dt><dd>${esc((t.img||[]).join(' × '))} · 최대 ${esc(t.epochs)} epoch</dd></div><div><dt>가져온 날짜</dt><dd>${date(m.imported)}</dd></div></dl>${rows.length?`<h3 style="margin:20px 0 12px">평가 결과 · valid</h3><div class="tablewrap"><table class="table"><thead><tr><th>버전</th><th>마스크 mAP50</th><th>마스크 mAP50–95</th></tr></thead><tbody>${rows.map(e=>`<tr><td>${esc(e.version_name)}</td><td>${e.metrics['coco/segm_mAP_50']?.toFixed(3)??'—'}</td><td>${e.metrics['coco/segm_mAP']?.toFixed(3)??'—'}</td></tr>`).join('')}</tbody></table></div>`:''}<p class="tiny muted" style="margin-top:14px">원본 모델 파일과 설정·평가 자료를 보존했습니다. 추론은 RTMDet-Ins 실행 환경 연결 후 사용할 수 있습니다.</p>`;
}
function modelsPage(){return head('모델 · 자동 라벨','사용할 모델을 고르고, 예측 결과를 사람이 확인해 라벨로 적용하세요.',btn('기존 모델 등록','register-model','plus','primary'),'MODEL REGISTRY')+`<section class="card pad"><div class="cardhead"><h2>사용할 모델</h2><a class="textlink" href="#/train">학습 · 비교 ${icon('arrow','small')}</a></div>${modelTable()}</section><section class="card pad" style="margin-top:22px"><div class="cardhead"><div><h2>자동 라벨</h2><p>예측은 원본 라벨을 바로 덮어쓰지 않습니다.</p></div><a class="btn" href="#/images">${icon('image')}사진 선택</a></div><div class="hint">전체 사진에서 대상을 선택하고 ‘자동 라벨’을 실행하세요. 완료된 예측을 검토한 뒤 적용하면 검수 대기 상태로 저장됩니다.</div>${jobsHtml(state.jobs.filter(x=>x.mode==='predict'))}</section>`;}
function shortcutsSettings(){const keys=resolvedShortcuts(state.settings);return `<section class="card pad"><div class="cardhead"><h2>편집기 단축키</h2></div><p class="tiny muted">입력란을 누르고 원하는 키 조합을 누르세요. Backspace로 해제합니다. 클래스 숫자키는 클래스 관리에서 바꿉니다.</p><form data-form="shortcuts"><div class="shortcuts">${shortcutActions.map(([id,label])=>`<label class="field">${label}<input readonly name="${id}" data-shortcut-key value="${esc(keys[id])}" placeholder="미지정" aria-label="${label} 단축키"></label>`).join('')}</div><div class="actions" style="margin-top:16px"><button class="btn primary">단축키 저장</button><button type="button" class="btn" data-action="reset-shortcuts">기본값 복원</button></div></form></section>`;}
function settingsPage(){return head('설정','작업 공간과 데이터 연결 상태를 관리하세요.','','WORKSPACE SETTINGS')+`<div class="split-grid"><div class="stack"><section class="card pad"><div class="cardhead"><h2>작업 공간</h2></div><form data-form="settings"><div class="formgrid">${label('프로젝트 이름',input('project_name',state.settings.project_name||'케이블 표면 검사'))}${label('데이터 저장소','<input value="로컬 SQLite" readonly>')}</div><div class="actions" style="margin-top:20px"><button class="btn primary">저장</button><a class="btn" href="/api/backup">${icon('download')}데이터 백업</a></div></form></section><section class="card pad"><div class="cardhead"><h2>DB 연결</h2>${badge('연결됨','green')}</div><p class="smalltext muted">${state.connection.demo?'예제 데이터':'cksgur에서 가져온 실제 데이터'}를 사용 중입니다.</p><dl class="detail-list"><div><dt>사진</dt><dd>${num(activeImages().length)}장 · 휴지통 ${num(state.images.filter(x=>x.deleted).length)}장</dd></div><div><dt>보드 / 버전</dt><dd>${state.batches.length}개 / ${state.versions.length}개</dd></div></dl></section></div><div class="stack"><section class="card pad"><div class="cardhead"><h2>RTMDet-Ins · GPU 서버</h2>${badge(state.connection.ml.ready?'연결됨':'로그인 필요',state.connection.ml.ready?'green':'amber')}</div><p class="smalltext muted">${esc(state.connection.ml.reason)}</p><form data-form="gpu-connect"><div class="formgrid">${label('서버','<input value="gpu.example.internal" readonly>')}${label('계정','<input value="cable" readonly>')}${label('서버 비밀번호',input('password','','password','autocomplete="off" required'))}</div><div class="actions" style="margin-top:16px"><button class="btn primary">${state.connection.ml.ready?'다시 연결':'GPU 서버 연결'}</button></div></form><p class="tiny muted">비밀번호는 연결할 때만 사용하며 파일이나 DB에 저장하지 않습니다.</p></section>${shortcutsSettings()}</div></div>`+classesSection();}

async function renderPage(){
 imageListObserver?.disconnect();imageListObserver=null;
 const token=++renderToken;rememberTrainingForm();rememberUploadForm();await closeEditor();document.querySelector('#main').className='';
 const [r,q]=(location.hash.slice(2)||'').split('?');route=r;params=new URLSearchParams(q||'');header();
 const main=document.querySelector('#main');
 if(route==='classes'){location.replace('#/settings?section=classes');return;}
 if(route==='upload'||route==='versions'){location.replace(route==='upload'?'#/board?upload=1':'#/train');return;}
 if(route.startsWith('annotate/')){const image=state.images.find(x=>x.id===route.split('/')[1]);if(image){main.className='editor-main';openEditor(image,state,refresh);rememberLastEditor(image);return;}main.innerHTML=empty('사진을 찾을 수 없습니다');return;}
 const pages={'':dashboard,board:boardPage,images:()=>imagesPage(false),trash:()=>params.get('type')==='models'?trashedModelsPage():imagesPage(true),train:trainingWorkspacePage,models:modelsPage,test:()=>'',settings:settingsPage};
 main.innerHTML=(pages[route]||(()=>head('페이지를 찾을 수 없습니다','상단 메뉴에서 작업을 선택하세요.')))();
 if(route==='test'){location.assign('http://127.0.0.1:8899/');return;}
 if(route==='train'){const model=params.get('model'),ver=comparisonVersion();if(model&&activeModels().some(m=>m.id===model)){const ids=comparedModels.get(ver)||new Set();ids.add(model);comparedModels.set(ver,ids);saveComparisonSelections();main.querySelector('#model-comparison').innerHTML=comparisonChart();const box=main.querySelector(`[data-compare-model="${model}"]`);if(box)box.checked=true;}splitPreview=null;restoreTrainingForm();}
 if(route==='settings'&&params.get('section')==='classes')document.querySelector('#class-settings')?.scrollIntoView({block:'start'});
 if(route==='board'){setupUpload();if(params.get('upload')==='1')document.querySelector('#upload-meta [name=batch]').focus({preventScroll:true});}
 if(token!==renderToken)return;
 if(route==='images'||route==='trash')observeImageList();
}

async function bulk(changes){await api('/api/images/bulk',{ids:[...selected],changes});selected.clear();await refresh();toast('저장했습니다');}
function predictionForm(ids){if(!activeModels().length){toast('먼저 RTMDet-Ins 모델을 등록하세요',true);return;}modal('RTMDet-Ins 자동 라벨',`<form data-form="predict"><input type="hidden" name="ids" value="${esc(JSON.stringify(ids))}"><div class="formgrid">${label('모델',select('model_id',options(activeModels()),activeModels().find(x=>x.active)?.id))}${label('예측 점수 기준',input('threshold',.4,'number','min="0" max="1" step="0.05" required'))}</div><p class="hint">${ids.length}장에 대해 마스크를 예측합니다. 결과를 확인한 후에만 라벨에 반영합니다.</p><button class="btn primary" ${state.connection.ml.ready?'':'disabled'}>예측 실행</button>${!state.connection.ml.ready?'<p class="tiny muted">RTMDet-Ins 실행 환경 연결이 필요합니다.</p>':''}</form>`);}
export {predictionForm};
async function actions(action,el){
 const id=el.dataset.id;
 switch(action){
  case 'close-modal':closeModal();break;
  case 'theme':{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;localStorage.setItem('studio-theme',theme);break;}
  case 'jobs':modal('작업 센터','<div id="job-center-content">'+jobsHtml()+'</div>');document.querySelector('#modal').dataset.view='jobs';break;
  case 'deselect':selected.clear();await renderPage();break;
  case 'review':await bulk({status:'reviewed'});break;
  case 'ambiguous':await bulk({status:'ambiguous'});break;
  case 'trash':await bulk({deleted:true});break;
  case 'restore':await bulk({deleted:false});break;
  case 'image-trash':case 'image-restore':{await api('/api/images/bulk',{ids:[id],changes:{deleted:action==='image-trash'}});selected.delete(id);await refresh();toast(action==='image-trash'?'사진을 휴지통으로 옮겼습니다':'사진을 복원했습니다');break;}
  case 'model-trash':case 'model-restore':{await api('/api/models/'+id,{deleted:action==='model-trash'});closeModal();await refresh();toast(action==='model-trash'?'모델을 휴지통으로 옮겼습니다':'모델을 복원했습니다. 사용하려면 모델 목록에서 다시 선택하세요.');break;}
  case 'bulk-tags':modal('태그 추가',`<form data-form="bulk-tags">${label('태그 · 쉼표로 구분',input('tags','','text','required'))}<p class="tiny muted">${selected.size}장의 기존 태그에 추가합니다.</p><button class="btn primary">적용</button></form>`);break;
  case 'bulk-predict':predictionForm([...selected]);break;
  case 'new-batch':modal('새 배치',`<form data-form="batch">${label('배치 이름',input('name','','text','required'))}<button class="btn primary" style="margin-top:20px">만들기</button></form>`);break;
  case 'rename-batch':{const b=state.batches.find(x=>x.id===id);modal('배치 수정',`<form data-form="batch"><input type="hidden" name="id" value="${b.id}">${label('배치 이름',input('name',b.name,'text','required'))}<button class="btn primary" style="margin-top:20px">저장</button></form>`);break;}
  case 'merge-batches':modal('배치 합치기',`<form data-form="merge"><div class="formgrid">${label('사진을 받을 배치',select('target',options(state.batches)))}</div><p class="tiny muted">선택한 배치의 사진을 대상 배치로 이동합니다. 기존 버전은 유지합니다.</p>${state.batches.map(b=>`<label class="checkline"><input type="checkbox" name="sources" value="${b.id}">${esc(b.name)}</label>`).join('')}<button class="btn primary">배치 합치기</button></form>`);break;
  case 'new-class':classForm();break;
  case 'edit-class':classForm(state.classes.find(x=>x.id===id));break;
  case 'reset-shortcuts':await api('/api/settings',{shortcuts:{}});await refresh();toast('기본 단축키로 복원했습니다');break;
  case 'toggle-training':document.querySelector('#training-form').scrollIntoView({behavior:'smooth',block:'center'});document.querySelector('[name=start_mode]').focus();break;
  case 'compare-version':{const v=await api(`/api/versions/${id}/compare?with=${el.dataset.with}`);modal('버전 비교',`<div class="stats" style="grid-template-columns:repeat(3,1fr)">${[['추가',v.added],['제외',v.removed],['라벨·분할 변경',v.changed]].map(([t,xs])=>`<div class="card stat"><div><label>${t}</label><div class="num">${xs.length}</div></div></div>`).join('')}</div>${Object.entries(v).map(([k,xs])=>`<details><summary class="smalltext">${({added:'추가',removed:'제외',changed:'변경'})[k]} · ${xs.length}장</summary><pre>${esc(xs.join('\n')||'없음')}</pre></details>`).join('')}`);break;}
  case 'duplicates':{const map=new Map();for(const x of activeImages()){for(const k of ['name','sha256']){const key=k+':'+x[k];if(!map.has(key))map.set(key,[]);map.get(key).push(x);}}const groups=[...map.values()].filter(xs=>xs.length>1);modal('같은 사진 찾기',groups.length?groups.map(xs=>`<div class="hint" style="margin-bottom:12px">${xs.map(x=>`<a class="textlink" href="#/annotate/${x.id}" data-action="close-modal">${esc(x.name)}</a>`).join('<br>')}</div>`).join(''):empty('중복 사진이 없습니다','이름 또는 SHA-256이 같은 사진을 확인했습니다.'));break;}
  case 'register-model':modal('기존 RTMDet-Ins 모델 등록',`<form data-form="register-model"><div class="hint amber" style="margin-bottom:18px">현재 클래스의 순서와 체크포인트의 클래스 순서가 같아야 합니다. 서버에서 접근 가능한 파일 경로를 입력하세요.</div><div class="formgrid">${label('모델 이름',input('name','','text','required'))}${label('모델 크기',select('size',[['s','S'],['m','M'],['l','L'],['x','X']],'l'))}${label('체크포인트 (.pth)',input('checkpoint','','text','required'),true)}${label('MMDetection 설정 (.py)',input('config','','text','required'),true)}</div><button class="btn primary" style="margin-top:22px">등록</button></form>`);break;
  case 'model-detail':{const m=state.models.find(x=>x.id===id);modal(m.name,`<form data-form="rename-model"><input type="hidden" name="id" value="${m.id}">${label('모델 이름',input('name',m.name,'text','required'))}<div class="actions" style="margin-top:16px"><button class="btn">이름 저장</button><a class="btn primary" href="/api/models/${id}/download?bundle=1">모델 + 설정 ZIP</a></div></form><div class="actions" style="margin-top:12px"><button class="btn danger" data-action="model-trash" data-id="${m.id}">${icon('trash')}모델 삭제 · 휴지통으로</button></div><div class="divider"></div><dl class="detail-list"><div><dt>종류</dt><dd>RTMDet-Ins ${m.size.toUpperCase()}</dd></div><div><dt>등록</dt><dd>${date(m.created)}</dd></div><div><dt>클래스</dt><dd>${esc(m.classes.map(c=>c.name).join(', '))}</dd></div></dl>${importedModelDetails(m)}`);break;}
  case 'view-evaluation':{const ver=el.dataset.version,ids=comparedModels.get(ver)||new Set();ids.add(id);comparedModels.set(ver,ids);saveComparisonSelections();closeModal();location.hash='#/train?version='+encodeURIComponent(ver);if(route==='train'&&params.get('version')===ver)await renderPage();break;}
  case 'evaluate-model':{const m=state.models.find(x=>x.id===id);modal('모델 평가',`<form data-form="evaluate"><input type="hidden" name="model_id" value="${id}"><p>평가할 모델: <b>${esc(m.name)}</b></p>${label('평가할 데이터 버전 · valid',select('version_id',state.versions.filter(v=>v.counts.valid>0).map(v=>[v.id,v.name+' · valid '+num(v.counts.valid)+'장']),comparisonVersion()))}<p class="tiny muted" id="evaluation-summary"></p><p class="tiny muted">이 모델의 예측을 선택한 valid 이미지의 정답과 비교합니다. 가중치는 바뀌지 않습니다.</p>${!state.connection.ml.ready?'<div class="hint amber">GPU 서버 로그인이 필요합니다. <a class="textlink" href="#/settings">설정에서 연결</a></div>':''}<button class="btn primary" ${state.connection.ml.ready&&state.versions.length?'':'disabled'}>이 모델 평가 시작</button></form>`);updateEvaluationSummary();break;}
  case 'job-log':{const x=await api(`/api/jobs/${id}/log`);modal('작업 로그',`<div class="actions" style="margin-bottom:12px"><button class="btn" data-action="copy-job-log">로그 복사</button></div><pre id="job-log-text" tabindex="0">${esc(x.text)}</pre>`);break;}
  case 'copy-job-log':await copyJobLog();break;
  case 'cancel-job':await api(`/api/jobs/${id}/cancel`,{});closeModal();await refresh();toast('이 앱의 작업을 중단했습니다');break;
  case 'accept-predictions':{const job=state.jobs.find(j=>j.id===id),xs=job.result.predictions;modal('예측 결과 검토',`<div class="hint">${xs.length}장 · ${xs.reduce((n,x)=>n+x.annotations.length,0)}개 마스크. 적용한 라벨은 사람 검수 전까지 버전에 들어가지 않습니다.</div><div class="tablewrap" style="max-height:260px;overflow:auto"><table class="table"><tbody>${xs.map(x=>`<tr><td>${esc(state.images.find(i=>i.id===x.image_id)?.name)}</td><td>${x.annotations.length}개</td></tr>`).join('')}</tbody></table></div><form data-form="accept-predictions"><input type="hidden" name="job_id" value="${id}">${check('append','기존 라벨에 추가')}<button class="btn primary" style="margin-top:16px">라벨로 적용 · 검수 대기</button></form>`);break;}
 }
}

function setImageSelected(checkbox,checked){
 checkbox.checked=checked;
 checked?selected.add(checkbox.dataset.select):selected.delete(checkbox.dataset.select);
 checkbox.closest('.imagecard').classList.toggle('selected',checked);
 document.querySelector('.imagegrid')?.classList.toggle('selecting',selected.size>0);
 document.querySelector('#bulkbar').innerHTML=bulkbar(route==='trash');
}
function handleImageCardClick(event){
 if(!selected.size||!['images','trash'].includes(route))return false;
 const card=event.target.closest('.imagecard');
 if(!card||event.target.closest('input,button,select,textarea,label,[data-action]'))return false;
 const checkbox=card.querySelector('[data-select]');if(!checkbox)return false;
 event.preventDefault();setImageSelected(checkbox,!selected.has(checkbox.dataset.select));return true;
}
document.addEventListener('click',async event=>{if(handleImageCardClick(event))return;const el=event.target.closest('[data-action]');if(!el||el.dataset.action.startsWith('editor-'))return;try{await actions(el.dataset.action,el);}catch(e){toast(e.message,true);}});
document.addEventListener('change',async event=>{
 const el=event.target;
 try{
  if(el.matches('[data-select]')){setImageSelected(el,el.checked);}
  else if(el.id==='select-all'){const xs=filteredImages(route==='trash').slice(0,visibleImageLimit(route==='trash'));xs.forEach(x=>el.checked?selected.add(x.id):selected.delete(x.id));await renderPage();}
  else if(el.name==='bulk-split')await bulk({split:el.value==='none'?'':el.value});
  else if(el.name==='bulk-batch')await bulk({batch:el.value});
  else if(el.dataset.stageSelect){await api('/api/batches',{id:el.dataset.stageSelect,stage:el.value});await refresh();}
  else if(el.name==='active-model'){await api('/api/models/'+el.value,{active:true});await refresh();toast('사용할 모델을 변경했습니다');}
  else if(el.name==='start_mode'||el.name==='resume_model'){syncTrainingMode();rememberTrainingForm();}
  else if(el.closest('[data-form=evaluate]')&&el.name==='version_id')updateEvaluationSummary();
  else if(el.name==='compare-version')setQuery({version:el.value});
  else if(el.matches('[data-compare-model]')){const ver=comparisonVersion(),ids=comparedModels.get(ver)||new Set();el.checked?ids.add(el.dataset.compareModel):ids.delete(el.dataset.compareModel);comparedModels.set(ver,ids);saveComparisonSelections();document.querySelector('#model-comparison').innerHTML=comparisonChart();}
  else if(el.closest('[data-form=filters]')&&el.tagName==='SELECT')el.closest('form').requestSubmit();
  else if(el.closest('#split-form')){splitPreview=null;document.querySelector('#apply-split').disabled=true;document.querySelector('#split-preview').textContent='설정이 바뀌었습니다. 미리 보기를 다시 실행하세요.';}
 }catch(e){toast(e.message,true);}
});

document.addEventListener('submit',async event=>{
 const form=event.target;if(!form.dataset.form)return;event.preventDefault();const fd=new FormData(form),data=Object.fromEntries(fd),kind=form.dataset.form;
 const submit=event.submitter;if(submit)submit.disabled=true;
 try{
  if(kind==='filters'){setQuery(data);return;}
  if(kind==='shortcuts'){validateShortcuts(data,state.classes);await api('/api/settings',{shortcuts:data});}
  else if(kind==='gpu-connect'){const password=fd.get('password');form.querySelector('[name=password]').value='';await api('/api/ml/connect',{password});}
  else if(kind==='class'){if(data.shortcut&&Object.values(resolvedShortcuts(state.settings)).includes(data.shortcut.toUpperCase()))throw Error('편집기에서 사용 중인 단축키입니다. 다른 키를 선택하세요.');data.normal=fd.has('normal');if(!data.id)delete data.id;await api('/api/classes',data);}
  else if(kind==='batch'){if(!data.id)delete data.id;await api('/api/batches',data);if(!data.id){params.set('empty','1');location.hash='#/board?empty=1';}}
  else if(kind==='merge'){data.sources=fd.getAll('sources');await api('/api/batches/merge',data);}
  else if(kind==='version'){for(const key of ['done_only','exclude_ambiguous','reviewed_only','include_background'])data[key]=fd.has(key);data.train_batches=fd.getAll('train_batches');const version=await api('/api/versions',data);pendingTrainingVersion=version.id;}
  else if(kind==='split'){
   const apply=submit?.value==='apply';if(apply&&!splitPreview)throw Error('먼저 분할을 미리 보세요');
   if(apply)data.fingerprint=splitPreview.fingerprint;
   const result=await api('/api/split/'+(apply?'apply':'preview'),data);
   if(apply){await refresh();toast(`${result.total}장의 분할을 저장했습니다`);return;}
   splitPreview=result;document.querySelector('#split-preview').innerHTML=`<div class="hint blue">${result.total}장 · 연속 촬영 ${result.groups}개 묶음<br>train ${result.counts.train} · valid ${result.counts.valid} · test ${result.counts.test}</div>`;document.querySelector('#apply-split').disabled=!result.total;return;
  }
  else if(kind==='training'){if(data.start_mode==='scratch')delete data.resume_model;else{const model=activeModels().find(m=>m.id===data.resume_model);if(!model)throw Error('추가 학습할 모델을 선택하세요.');data.size=model.size;}const [h,w]=data.input_size.split('x').map(Number);Object.assign(data,{height:h,width:w,mode:'train',model_type:'RTMDet-Ins'});await api('/api/jobs',data);}
  else if(kind==='register-model')await api('/api/models/register',data);
  else if(kind==='rename-model')await api('/api/models/'+data.id,{name:data.name});
  else if(kind==='predict'){await api('/api/jobs',{mode:'predict',model_id:data.model_id,image_ids:JSON.parse(data.ids),threshold:Number(data.threshold)});}
  else if(kind==='evaluate'){await api('/api/jobs',{mode:'eval',...data});const ids=comparedModels.get(data.version_id)||new Set();ids.add(data.model_id);comparedModels.set(data.version_id,ids);saveComparisonSelections();location.hash='#/train?version='+encodeURIComponent(data.version_id);}
  else if(kind==='accept-predictions'){data.append=fd.has('append');await api('/api/predictions/accept',data);}
  else if(kind==='settings')await api('/api/settings',data);
  else if(kind==='bulk-tags'){const tags=data.tags.split(',').map(x=>x.trim()).filter(Boolean);for(const id of selected){const x=state.images.find(x=>x.id===id);await api('/api/images/'+id,{revision:x.revision,tags:[...new Set([...x.tags,...tags])]});}selected.clear();}
  else return;
  closeModal();await refresh();toast('저장했습니다');
 }catch(e){toast(e.message,true);}finally{if(submit)submit.disabled=false;}
});

let dragBatch;
document.addEventListener('dragstart',e=>{const card=e.target.closest('[data-batch]');if(card){dragBatch=card.dataset.batch;e.dataTransfer.setData('text/plain',dragBatch);e.dataTransfer.effectAllowed='move';}});
document.addEventListener('dragover',e=>{if(e.target.closest('[data-stage]')&&dragBatch)e.preventDefault();});
document.addEventListener('drop',async e=>{const col=e.target.closest('[data-stage]');if(col&&dragBatch){e.preventDefault();const id=dragBatch;dragBatch=null;try{await api('/api/batches',{id,stage:col.dataset.stage});await refresh();}catch(err){toast(err.message,true);}}});
document.addEventListener('dragend',()=>dragBatch=null);

function rememberUploadForm(){const form=document.querySelector('#upload-meta');if(form){const fd=new FormData(form);uploadDraft={...Object.fromEntries(fd),allow_duplicates:fd.has('allow_duplicates')};}}
function reportUpload(html){uploadResultHtml=html;const box=document.querySelector('#upload-results');if(box)box.innerHTML=html;}
function setupUpload(){
 const drop=document.querySelector('#dropzone'),files=document.querySelector('#files');
 const form=document.querySelector('#upload-meta');
 for(const [key,value] of Object.entries(uploadDraft||{})){const el=form.elements.namedItem(key);if(el){if(el.type==='checkbox')el.checked=!!value;else el.value=value;}}
 document.querySelector('label[for=files]').style.pointerEvents=uploading?'none':'';
 for(const type of ['dragenter','dragover'])drop.addEventListener(type,e=>{e.preventDefault();drop.classList.add('dragover');});
 for(const type of ['dragleave','drop'])drop.addEventListener(type,e=>{e.preventDefault();drop.classList.remove('dragover');});
 drop.addEventListener('drop',e=>uploadFiles(e.dataTransfer.files));files.addEventListener('change',()=>uploadFiles(files.files));
}
async function syncUploadedBoard(){await refresh(false);const board=document.querySelector('#board-columns');if(route==='board'&&board)board.innerHTML=boardColumns();}
async function uploadFiles(files){
 if(!files.length)return;
 if(uploading){toast('사진을 올리는 중입니다. 완료 후 다시 추가하세요.');return;}
 const form=document.querySelector('#upload-meta');if(!form)return;
 rememberUploadForm();uploading=true;let lastBoardUpdate=0;const fd=new FormData(form);let added=0,skipped=0,failed=0;
 const batchName=String(fd.get('batch')||'').trim()||'업로드 '+new Date().toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});
 const choice=document.querySelector('label[for=files]');choice.style.pointerEvents='none';
 try{for(const [i,file] of [...files].entries()){
  reportUpload(`<div class="hint blue">업로드 중 ${i+1} / ${files.length} · ${esc(file.name)}</div>`);
  try{
   if(file.size>80*1024*1024)throw Error('80MB 초과');
   const bitmap=await createImageBitmap(file),width=bitmap.width,height=bitmap.height;bitmap.close();
   const meta={name:file.name,width,height,batch:batchName,split:fd.get('split'),tags:String(fd.get('tags')).split(',').map(x=>x.trim()).filter(Boolean),allow_duplicates:fd.has('allow_duplicates')};
   // HTTP header values are ASCII; JSON's escaped Unicode keeps Korean filenames intact.
   const header=JSON.stringify(meta).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
   const r=await fetch('/api/upload',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Upload-Meta':header},body:file}),j=await r.json();if(!r.ok)throw Error(j.error);j.skipped?skipped++:added++;
   if(Date.now()-lastBoardUpdate>1000){try{await syncUploadedBoard();}catch{toast('사진은 저장됐지만 보드 갱신에 실패했습니다. 다시 열어 확인하세요.',true);}lastBoardUpdate=Date.now();}
  }catch(e){failed++;toast(file.name+': '+e.message,true);}
 }reportUpload(`<div class="hint ${failed?'amber':'blue'}" style="margin-bottom:15px">완료 · 추가 ${added}장 · 중복 제외 ${skipped}장 · 실패 ${failed}장</div>`);try{await syncUploadedBoard();}catch{toast('보드를 다시 열어 업로드 결과를 확인하세요.',true);}}finally{uploading=false;choice.style.pointerEvents='';const currentChoice=document.querySelector('label[for=files]');if(currentChoice)currentChoice.style.pointerEvents='';}
}

window.addEventListener('hashchange',async()=>{closeModal();selected.clear();try{await renderPage();window.scrollTo(0,0);}catch(e){toast(e.message,true);}});
document.querySelector('#modal').addEventListener('click',e=>{if(e.target===e.currentTarget){const r=e.currentTarget.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeModal();}});
try{document.documentElement.dataset.theme=localStorage.getItem('studio-theme')||'light';await refresh();}catch(e){document.querySelector('#main').innerHTML=empty('작업 공간에 연결할 수 없습니다',e.message);}
setInterval(async()=>{if(document.hidden||!state?.jobs.some(j=>['running','queued'].includes(j.status)))return;try{const fresh=await api('/api/state');state=fresh;await syncValidationProgress();header();syncJobCenter();if(['train','models'].includes(route)&&!document.querySelector('#modal').open&&!document.querySelector('#main').contains(document.activeElement))await renderPage();}catch{}},4000);

refreshGPU();setInterval(refreshGPU,5000);

document.addEventListener('keydown',event=>{if(!event.target.matches?.('[data-shortcut-key]')||event.key==='Tab')return;event.preventDefault();event.stopPropagation();if(event.key==='Backspace'&&!event.ctrlKey&&!event.altKey&&!event.shiftKey){event.target.value='';return;}const key=eventShortcut(event);if(key)event.target.value=key;});
