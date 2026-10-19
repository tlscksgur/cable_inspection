import {api,esc,icon,toast,goImage,predictionForm} from './app.js';
import {shortcutActions,eventShortcut,resolvedShortcuts,shortcutLabel} from './shortcuts.js';

let current=null;
const editorPreferences={tool:"polygon",classId:null};
export async function closeEditor(){
 if(!current)return;
 const old=current;
 if(old.dirty||old.saving)await old.save();
 old.abort.abort();clearTimeout(old.timer);current=null;
}

export function openEditor(source,state,refresh){
 const keys=resolvedShortcuts(state.settings);
 const image=structuredClone(source),abort=new AbortController(),signal=abort.signal;
 const c={image,state,abort,dirty:false,timer:null,saving:null,selected:null,tool:editorPreferences.tool,points:[],undo:[],redo:[],view:{x:-image.width*.06,y:-image.height*.22,w:image.width*1.12,h:image.height*1.44},show:true,filter:'',drag:null,space:false,classId:state.classes.find(x=>x.id===editorPreferences.classId)?.id??state.classes[0]?.id,save:null};current=c;
 const btn=(t,a,i='',cl='')=>`<button class="btn ${cl}" data-action="editor-${a}">${i?icon(i):''}${t}</button>`;
 const select=(name,options,value)=>`<select name="${name}" aria-label="${name==='split'?'분할':name==='batch'?'배치':'클래스'}">${options.map(([k,t])=>`<option value="${esc(k)}" ${k===value?'selected':''}>${esc(t)}</option>`).join('')}</select>`;
 const siblings=state.images.filter(x=>!x.deleted&&x.batch===image.batch).sort((a,b)=>a.name.localeCompare(b.name)),index=siblings.findIndex(x=>x.id===image.id);
 const main=document.querySelector('#main');
 main.innerHTML=`<div class="edithead"><div class="row"><a class="btn" href="#/images?batch=${image.batch}" aria-label="목록으로">←</a><div><div class="filename" title="${esc(image.name)}">${esc(image.name)}</div><span class="tiny muted">${image.width} × ${image.height} · ${index+1} / ${siblings.length}장 <span id="editor-review-state" class="review-indicator"></span> <span id="save-status" style="margin-left:8px">저장됨</span></span></div></div><div class="editor-review-actions" role="toolbar" aria-label="사진 검수">${btn('이전','prev')}${btn('그냥 다음','next')}${btn('애매','ambiguous','','review-ambiguous')}${btn('검수 완료','review','check','review-complete')}</div><div class="editor-utilities">${btn(image.deleted?'복원':'사진 삭제',image.deleted?'restore':'trash',image.deleted?'undo':'trash','danger')}<a class="btn small" href="#/settings">단축키 설정</a></div></div>
 <div class="toolstrip" role="toolbar" aria-label="편집 도구">${btn('선택 '+shortcutLabel(keys.select),'select','pointer')}${btn('박스 '+shortcutLabel(keys.box),'box','box')}${btn('다각형 '+shortcutLabel(keys.polygon),'polygon','polygon','active')}<span class="navsep" style="height:20px;margin:0 5px"></span>${btn('되돌리기','undo','undo')}${btn('전체 보기','fit')}${btn('라벨','labels','eye')}${btn('흑백','gray')}${btn('반전','invert')}${btn('저장','save','save')}</div>
 <div class="editor-classes" role="group" aria-label="클래스 빠른 선택">${state.classes.map(cls=>`<button type="button" class="class-choice" data-editor-class="${esc(cls.id)}" aria-label="${esc(cls.name)} 클래스 선택" aria-pressed="${cls.id===c.classId}" style="--class-color:${cls.color}"><i class="swatch" style="background:${cls.color}"></i>${esc(cls.name)}${cls.shortcut?`<kbd>${esc(cls.shortcut)}</kbd>`:''}</button>`).join('')}</div>
 <div class="editorlayout"><section class="editorstage" id="editor-stage" aria-label="사진과 라벨"><div id="selected-label-actions" class="selected-label-actions" hidden></div><div class="stage-label">${esc(image.name)}${image.name.startsWith('예제_')?' · SYNTHETIC SAMPLE':''}</div><svg id="editor-svg" xmlns="http://www.w3.org/2000/svg" tabindex="0" role="img" aria-label="사진에 점을 찍어 다각형 라벨을 그리세요"><image id="source-image" href="/media/${image.file}" x="0" y="0" width="${image.width}" height="${image.height}"/><g id="annotations"></g><g id="draft"></g></svg><div class="stagehelp" id="stage-help">클릭으로 점 추가 · ${shortcutLabel(keys.finish)} / 더블 클릭으로 완성 · 휠로 확대</div><div class="zoomcontrols"><button class="iconbtn" data-action="editor-zoom-out" aria-label="축소">−</button><span id="zoom-value">100%</span><button class="iconbtn" data-action="editor-zoom-in" aria-label="확대">+</button></div></section>
 <aside class="card editside" aria-label="사진 정보"><section><h3>사진 정보</h3><div class="formgrid"><label class="field">분할${select('split',[['','미배정'],['train','train'],['valid','valid'],['test','test']],image.split)}</label><label class="field">배치${select('batch',state.batches.map(x=>[x.id,x.name]),image.batch)}</label></div><label class="field" style="margin-top:12px">태그 · 쉼표로 구분<input name="tags" value="${esc(image.tags.join(', '))}"></label></section>
 <section><div class="actions" style="margin-bottom:12px">${btn('검수 전으로 되돌리기','unreview')}</div><div class="row between"><h3>라벨 <span class="muted" id="label-count"></span></h3><span class="badge" id="edit-status">${esc(({todo:'검수 전',reviewed:'검수 완료',ambiguous:'애매',auto:'자동 라벨'})[image.status]||image.status)}</span></div><div id="label-list"></div></section>
 <section><h3>모델 예측</h3><p class="tiny muted">${esc(state.models.find(x=>x.active&&!x.deleted)?.name||'사용할 모델을 먼저 등록하세요')}</p>${btn('예측 실행','predict','model')}</section>
 <section><label class="field">메모<textarea name="note" placeholder="판단 근거를 남겨 보세요">${esc(image.note)}</textarea></label></section>
 <section><h3>연속 프레임</h3><div class="neighbors">${siblings.slice(Math.max(0,index-1),index+2).map(x=>`<a class="neighbor review-state-${x.status}" href="#/annotate/${x.id}" title="${esc(x.name)}"><img src="/media/${x.file}" alt="${esc(x.name)}"><span>${x.status==='reviewed'?'검수 완료':x.status==='ambiguous'?'애매':'검수 전'}</span></a>`).join('')}</div><p class="tiny muted">같은 자리에 남는 결함인지 앞뒤 사진과 비교하세요.</p></section>
 <div class="editorhelp"><kbd>${esc(shortcutLabel(keys.review))}</kbd> 검수 완료 · <kbd>${esc(shortcutLabel(keys.next))}</kbd> 그냥 다음<br><kbd>${esc(shortcutLabel(keys.ambiguous))}</kbd> 애매 · <kbd>${esc(shortcutLabel(keys.finish))}</kbd> 다각형 완성<br><kbd>${esc(shortcutLabel(keys.pan))}</kbd> + 드래그 이동<br>정점을 선택해 드래그하면 모양을 수정합니다.</div></aside></div>`;
 const svg=document.querySelector('#editor-svg'),stage=document.querySelector('#editor-stage');
 const history=()=>{c.undo.push(JSON.stringify(image.annotations));if(c.undo.length>80)c.undo.shift();c.redo=[];};
 const mark=()=>{image.status='todo';c.dirty=true;clearTimeout(c.timer);document.querySelector('#save-status').textContent='저장 대기…';c.timer=setTimeout(()=>save().catch(()=>{}),700);};
 const markInfo=()=>{c.dirty=true;clearTimeout(c.timer);document.querySelector('#save-status').textContent='저장 대기…';c.timer=setTimeout(()=>save().catch(()=>{}),700);};
 async function save(){
  clearTimeout(c.timer);
  if(c.saving){await c.saving;if(c.dirty)return save();return;}
  if(!c.dirty)return;
  const body={revision:image.revision,annotations:structuredClone(image.annotations),note:image.note,tags:structuredClone(image.tags),split:image.split,batch:image.batch,status:image.status};
  c.dirty=false;document.querySelector('#save-status').textContent='저장 중…';
  c.saving=(async()=>{try{
    const result=await api('/api/images/'+image.id,body);image.revision=result.revision;
    const idx=state.images.findIndex(x=>x.id===image.id);state.images[idx]=result;
    if(current===c)document.querySelector('#save-status').textContent=c.dirty?'저장 대기…':'저장됨';
   }catch(e){c.dirty=true;if(current===c)document.querySelector('#save-status').textContent='저장 실패 · 다시 저장';toast(e.message,true);throw e;}finally{c.saving=null;}})();
  await c.saving;
  if(c.dirty)return save();
 }
 c.save=save;
 const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
 function position(e){const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());return [clamp(p.x,0,image.width),clamp(p.y,0,image.height)];}
 function rawPosition(e){const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());return [p.x,p.y];}
 function paint(){
  svg.setAttribute('viewBox',`${c.view.x} ${c.view.y} ${c.view.w} ${c.view.h}`);
  const pixel=c.view.w/Math.max(svg.clientWidth,1),radius=4*pixel;
  document.querySelector('#source-image').style.filter=c.filter;
  document.querySelector('#annotations').innerHTML=c.show?image.annotations.map(a=>{const cls=state.classes.find(x=>x.id===a.class_id),color=cls?.color||'#888';return `<g><polygon data-label="${a.id}" points="${a.points.map(p=>p.join(',')).join(' ')}" fill="${color}${a.id===c.selected?'44':'22'}" stroke="${color}" stroke-width="${a.id===c.selected?2.5:1.6}"/>${a.id===c.selected?a.points.map((p,i)=>`<circle data-vertex="${i}" cx="${p[0]}" cy="${p[1]}" r="${radius}" fill="white" stroke="${color}" stroke-width="1.5"/>`).join(''):''}</g>`;}).join(''):'';
  document.querySelector('#draft').innerHTML=c.points.length?`<polyline points="${c.points.map(p=>p.join(',')).join(' ')}" fill="#8ca6ff22" stroke="#b7c8ff" stroke-width="${pixel*2}"/>${c.points.map(p=>`<circle cx="${p[0]}" cy="${p[1]}" r="${radius}" fill="#b7c8ff"/>`).join('')}`:'';
  document.querySelector('#label-count').textContent=image.annotations.length;
  document.querySelector('#label-list').innerHTML=image.annotations.length?image.annotations.map(a=>{const cls=state.classes.find(x=>x.id===a.class_id);return `<div class="labelrow ${a.id===c.selected?'active':''}" data-label-row="${a.id}" tabindex="0"><span><i class="swatch" style="background:${cls?.color||'#888'}"></i>${esc(cls?.name||'알 수 없는 클래스')}</span><span class="row"><small class="muted">${a.points.length}점</small><button class="iconbtn" data-remove="${a.id}" aria-label="${esc(cls?.name)} 라벨 삭제">${icon('trash')}</button></span></div>`;}).join(''):'<p class="tiny muted">아직 라벨이 없습니다</p>';
  document.querySelector('#zoom-value').textContent=Math.round(image.width/c.view.w*100)+'%';
  document.querySelectorAll('.toolstrip [data-action]').forEach(el=>el.classList.toggle('active',el.dataset.action==='editor-'+c.tool));
  document.querySelectorAll('[data-editor-class]').forEach(el=>{const active=el.dataset.editorClass===c.classId;el.classList.toggle('active',active);el.setAttribute('aria-pressed',String(active));});
  const selected=image.annotations.find(a=>a.id===c.selected),selectedActions=document.querySelector('#selected-label-actions');
  selectedActions.hidden=!selected;
  selectedActions.innerHTML=selected?`<span>선택한 라벨 · <b>${esc(state.classes.find(x=>x.id===selected.class_id)?.name||'클래스')}</b> · 위 클래스 버튼으로 변경</span>${btn('라벨 삭제','delete-label','trash','danger small')}${btn('선택 해제','deselect','','small')}`:'';
  svg.style.cursor=c.space?'grab':c.tool==='select'?'default':'crosshair';
  const statusText=({todo:'검수 전',reviewed:'✓ 검수 완료',ambiguous:'? 애매',auto:'자동 라벨 · 검수 전',ai_reviewed:'AI 검수 · 확인 필요'})[image.status]||image.status;
  main.dataset.reviewState=image.status;
  for(const id of ['#edit-status','#editor-review-state']){const el=document.querySelector(id);el.textContent=statusText;el.className='review-indicator review-state-'+image.status;}
  document.querySelectorAll('.editor-review-actions [data-action]').forEach(el=>el.setAttribute('aria-pressed',String((el.dataset.action==='editor-review'&&image.status==='reviewed')||(el.dataset.action==='editor-ambiguous'&&image.status==='ambiguous'))));
 }
 function finish(){
  if(c.points.length<3)return;
  // Double-click repeats its final point; remove adjacent duplicate vertices.
  const pts=c.points.filter((p,i)=>!i||p[0]!==c.points[i-1][0]||p[1]!==c.points[i-1][1]);
  if(pts.length<3)return;
  const area=Math.abs(pts.reduce((n,p,i)=>n+p[0]*pts[(i+1)%pts.length][1]-pts[(i+1)%pts.length][0]*p[1],0))/2;
  if(area<1){toast('면적이 있는 다각형을 그려주세요',true);return;}
  history();const a={id:crypto.randomUUID(),class_id:c.classId,points:structuredClone(pts),source:'human'};image.annotations.push(a);c.selected=a.id;c.points=[];mark();paint();
 }
 function choose(tool){if(c.points.length){toast('Enter로 완성하거나 Esc로 취소하세요');return;}c.tool=tool;editorPreferences.tool=tool;paint();}
 function chooseClass(id){
  if(!state.classes.some(cls=>cls.id===id))return;
  c.classId=id;editorPreferences.classId=id;
  const annotation=image.annotations.find(a=>a.id===c.selected);
  if(annotation&&annotation.class_id!==id){history();annotation.class_id=id;mark();}
  paint();
 }
 function remove(id){history();image.annotations=image.annotations.filter(a=>a.id!==id);c.selected=null;mark();paint();}
 async function next(delta){if(c.points.length){toast('다각형을 완성하거나 취소한 뒤 이동하세요.');return;}await save();const x=siblings[index+delta];if(x)goImage(x.id);else toast(delta>0?'마지막 사진입니다':'첫 번째 사진입니다');}
 async function decide(status){
  if(c.deciding)return;c.deciding=true;
  try{if(c.points.length){finish();if(c.points.length){toast('다각형을 완성하거나 취소하세요.');return;}}image.status=status;markInfo();paint();if(status==='todo')await save();else await next(1);}finally{c.deciding=false;}
 }
 function zoom(factor,center){const [x,y]=center||[c.view.x+c.view.w/2,c.view.y+c.view.h/2];if(c.view.w*factor<image.width*.015||c.view.w*factor>image.width*4)return;c.view={x:x-(x-c.view.x)*factor,y:y-(y-c.view.y)*factor,w:c.view.w*factor,h:c.view.h*factor};paint();}
 function undo(redo=false){const from=redo?c.redo:c.undo,to=redo?c.undo:c.redo;if(!from.length)return;to.push(JSON.stringify(image.annotations));image.annotations=JSON.parse(from.pop());c.selected=null;c.points=[];mark();paint();}
 function fit(){const w=stage.clientWidth,h=stage.clientHeight,ratio=w/h,iw=image.width*1.12,ih=image.height*1.2;let vw=Math.max(iw,ih*ratio),vh=vw/ratio;c.view={x:(image.width-vw)/2,y:(image.height-vh)/2,w:vw,h:vh};paint();}
 stage.addEventListener('contextmenu',e=>e.preventDefault(),{signal});
 svg.addEventListener('pointerdown',e=>{
  if(e.target.closest('.zoomcontrols'))return;
  svg.focus({preventScroll:true});const pos=position(e),raw=rawPosition(e);
  if(e.button===2||e.button===1||c.space){c.drag={type:'pan',client:[e.clientX,e.clientY],view:{...c.view}};svg.setPointerCapture(e.pointerId);e.preventDefault();return;}
  if(e.button!==0)return;
  if(e.target.hasAttribute('data-vertex')){history();c.drag={type:'vertex',index:Number(e.target.dataset.vertex)};svg.setPointerCapture(e.pointerId);return;}
  const hit=!c.points.length&&image.annotations.find(a=>a.id===e.target.dataset.label);
  if(hit){
   c.selected=hit.id;c.classId=hit.class_id;editorPreferences.classId=hit.class_id;
   if(c.tool==='select'){history();c.drag={type:'label',start:pos,points:structuredClone(hit.points)};svg.setPointerCapture(e.pointerId);}
   paint();return;
  }
  if(c.tool==='select'){c.selected=null;paint();return;}
  c.selected=null;
  if(raw[0]<0||raw[0]>image.width||raw[1]<0||raw[1]>image.height)return;
  if(c.tool==='box'){c.drag={type:'box',start:pos};c.points=[pos,pos,pos,pos];svg.setPointerCapture(e.pointerId);paint();return;}
  if(c.tool==='polygon'){
   if(c.points.length>=3&&Math.hypot(pos[0]-c.points[0][0],pos[1]-c.points[0][1])<c.view.w/svg.clientWidth*10){finish();return;}
   if(e.detail<2)c.points.push(pos);paint();
  }
 },{signal});
 svg.addEventListener('pointermove',e=>{
  if(!c.drag)return;const p=position(e),d=c.drag;
  if(d.type==='pan'){const scale=c.view.w/svg.clientWidth;c.view.x=d.view.x-(e.clientX-d.client[0])*scale;c.view.y=d.view.y-(e.clientY-d.client[1])*scale;paint();}
  else if(d.type==='vertex'){const a=image.annotations.find(a=>a.id===c.selected);a.points[d.index]=p;mark();paint();}
  else if(d.type==='label'){const a=image.annotations.find(a=>a.id===c.selected),xs=d.points.map(p=>p[0]),ys=d.points.map(p=>p[1]),dx=clamp(p[0]-d.start[0],-Math.min(...xs),image.width-Math.max(...xs)),dy=clamp(p[1]-d.start[1],-Math.min(...ys),image.height-Math.max(...ys));a.points=d.points.map(p=>[p[0]+dx,p[1]+dy]);mark();paint();}
  else if(d.type==='box'){c.points=[d.start,[p[0],d.start[1]],p,[d.start[0],p[1]]];paint();}
 },{signal});
 svg.addEventListener('pointerup',e=>{if(c.drag?.type==='box')finish();c.drag=null;if(svg.hasPointerCapture(e.pointerId))svg.releasePointerCapture(e.pointerId);},{signal});
 svg.addEventListener('pointercancel',()=>{c.drag=null;c.points=[];paint();},{signal});
 svg.addEventListener('dblclick',e=>{e.preventDefault();if(c.tool==='polygon')finish();},{signal});
 svg.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?1.15:1/1.15,rawPosition(e));},{passive:false,signal});
 main.addEventListener('click',async e=>{
  const classEl=e.target.closest('[data-editor-class]');if(classEl){chooseClass(classEl.dataset.editorClass);svg.focus({preventScroll:true});return;}
  const removeEl=e.target.closest('[data-remove]');if(removeEl){remove(removeEl.dataset.remove);return;}
  const row=e.target.closest('[data-label-row]');if(row){c.selected=row.dataset.labelRow;c.tool='select';const a=image.annotations.find(a=>a.id===c.selected);c.classId=a.class_id;editorPreferences.classId=a.class_id;paint();return;}
  const el=e.target.closest('[data-action^="editor-"]');if(!el)return;
  const action=el.dataset.action.slice(7);
  try{
   if(['select','box','polygon'].includes(action))choose(action);
   else if(action==='save'){await save();toast('라벨을 저장했습니다');}
   else if(action==='delete-label'){if(c.selected)remove(c.selected);}
   else if(action==='deselect'){c.selected=null;paint();}
   else if(action==='undo')undo();
   else if(action==='labels'){c.show=!c.show;paint();}
   else if(action==='fit')fit();
   else if(action==='gray'){c.filter=c.filter==='grayscale(1)'?'':'grayscale(1)';paint();}
   else if(action==='invert'){c.filter=c.filter==='invert(1)'?'':'invert(1)';paint();}
   else if(action==='zoom-in')zoom(1/1.3);
   else if(action==='zoom-out')zoom(1.3);
   else if(action==='prev')await next(-1);
   else if(action==='next')await next(1);
   else if(action==='review')await decide('reviewed');
   else if(action==='ambiguous')await decide('ambiguous');
   else if(action==='unreview')await decide('todo');
   else if(action==='predict'){await save();predictionForm([image.id]);}
   else if(action==='trash'||action==='restore'){
    el.disabled=true;
    try{
     await save();
     const result=await api('/api/images/'+image.id,{revision:image.revision,deleted:action==='trash'});
     image.revision=result.revision;image.deleted=result.deleted;c.points=[];
     const idx=state.images.findIndex(x=>x.id===image.id);state.images[idx]=result;
     await refresh(false);
     const neighbor=action==='trash'?(siblings[index+1]||siblings[index-1]):null;
     if(neighbor)goImage(neighbor.id);else location.hash='/images?batch='+encodeURIComponent(image.batch);
     toast(action==='trash'?'사진을 휴지통으로 옮겼습니다':'사진을 복원했습니다');
    }finally{el.disabled=false;}
   }
  }catch(err){toast(err.message,true);}
 },{signal});
 main.addEventListener('change',e=>{const el=e.target;
  if(['split','batch'].includes(el.name)){image[el.name]=el.value;markInfo();}
  else if(el.name==='tags'){image.tags=el.value.split(',').map(t=>t.trim()).filter(Boolean);markInfo();}
 },{signal});
 main.addEventListener('input',e=>{if(e.target.name==='note'){image.note=e.target.value;markInfo();}},{signal});
 document.addEventListener('keydown',async e=>{
  if(document.querySelector('#modal').open||e.isComposing)return;
  const combo=eventShortcut(e),action=shortcutActions.find(([id])=>keys[id]&&keys[id]===combo)?.[0];
  if((['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)||e.target.isContentEditable)&&!(action==='save'&&(e.ctrlKey||e.metaKey||e.altKey)))return;
  if(e.target.closest('button')&&['Enter',' '].includes(e.key))return;
  if(e.repeat&&['review','ambiguous','unreview','next','prev','finish'].includes(action))return;
  try{
   if(action){e.preventDefault();
    if(action==='save')await save();
    else if(action==='pan'){c.space=true;c.panKey=e.code||e.key;paint();}
    else if(action==='cancel'){c.points=[];c.selected=null;paint();}
    else if(action==='finish')finish();
    else if(action==='review')await decide('reviewed');
    else if(action==='ambiguous')await decide('ambiguous');
    else if(action==='unreview')await decide('todo');
    else if(action==='next')await next(1);else if(action==='prev')await next(-1);
    else if(action==='delete'){if(c.points.length){c.points.pop();paint();}else if(c.selected)remove(c.selected);}
    else if(['select','box','polygon'].includes(action))choose(action);
    else if(action==='undo')undo();else if(action==='redo')undo(true);
    else if(action==='labels'){c.show=!c.show;paint();}
    else if(action==='gray'){c.filter=c.filter==='grayscale(1)'?'':'grayscale(1)';paint();}
    else if(action==='invert'){c.filter=c.filter==='invert(1)'?'':'invert(1)';paint();}
    else if(action==='fit')fit();
   }else if(!e.ctrlKey&&!e.altKey&&!e.metaKey&&!e.shiftKey){const cls=state.classes.find(x=>String(x.shortcut).toUpperCase()===combo);if(cls){e.preventDefault();chooseClass(cls.id);}}
  }catch(err){toast(err.message,true);}
 },{signal});
 document.addEventListener('keyup',e=>{if(c.panKey===(e.code||e.key)){c.space=false;c.panKey=null;paint();}},{signal});
 window.addEventListener('blur',()=>{c.space=false;c.drag=null;},{signal});
 window.addEventListener('beforeunload',e=>{if(c.dirty||c.saving){e.preventDefault();e.returnValue='';}},{signal});
 // Finish pending autosave before the app replaces the editor DOM.
 document.addEventListener('click',async e=>{const link=e.target.closest('a[href^="#/"]');if(link&&(c.dirty||c.saving)){e.preventDefault();try{await save();location.hash=link.getAttribute('href');}catch{}}},{signal,capture:true});
 const resize=new ResizeObserver(()=>{if(current===c)paint();});resize.observe(stage);signal.addEventListener('abort',()=>resize.disconnect());
 fit();
}
