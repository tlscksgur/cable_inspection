// Client logic tests only: no browser, GPU, network, or user database.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

class Element {
  constructor(value='') { this.value=value; this.innerHTML=''; this.style={}; this.dataset={}; }
  addEventListener() {}
  focus() {}
}
class FormDataMock {
  constructor(form) { this.values=Object.entries(form.values||{}); }
  get(key) { return this.values.find(([k])=>k===key)?.[1]??null; }
  has(key) { return this.values.some(([k])=>k===key); }
  [Symbol.iterator]() { return this.values[Symbol.iterator](); }
}
async function harness(storage=new Map()) {
  const elements=new Map(['#main','#header','#modal','#toast','#board-columns','#upload-results','label[for=files]'].map(id=>[id,new Element()]));
  const upload=new Element(); upload.values={batch:'새 배치',tags:'확인,센서A',split:'valid'};
  elements.set('#upload-meta',upload);
  const document={querySelector:s=>elements.get(s)||null,querySelectorAll:()=>[],addEventListener(){},documentElement:{dataset:{}}};
  const location={hash:'#/board',replace(value){this.replaced=value;}};
  const localStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)};
  const context=vm.createContext({document,location,localStorage,window:{addEventListener(){}},URLSearchParams,FormData:FormDataMock,Date,Map,Set,console,setTimeout:()=>0,clearTimeout(){},createImageBitmap:async()=>({width:1600,height:2160,close(){}})});
  let source=fs.readFileSync(path.join(__dirname,'web/app.js'),'utf8');
  source=source.replace(/^import .*;$/m,'const closeEditor=async()=>{};const openEditor=()=>{};').replace(/^import .*;$/gm,'')
    .replace(/\bexport\s+(?=(?:const|let|function|async)\b)/g,'')
    .replace(/^export \{predictionForm\};$/m,'');
  source=source.slice(0,source.indexOf('\ntry{document.documentElement.dataset.theme'));
  const shortcuts=fs.readFileSync(path.join(__dirname,'web/shortcuts.js'),'utf8').replace(/\bexport\s+/g,'');
  await vm.runInContext(`(async()=>{${shortcuts}\n${source}\nglobalThis.client={appendImages,observeImageList,visibleImageLimit,setImageSelected,handleImageCardClick,validationFromLog,syncValidationProgress,rememberLastEditor,resumeLabelingButton,imagesPage,copyJobLog,jobProgress,syncJobCenter,syncTrainingMode,trainingForm,gpuStatus,settingsPage,boardColumns,trainBatchChoices,versionPreviewHTML,modelTable,comparisonChart,comparisonVersion,comparedModels,importedModelDetails,syncUploadedBoard,uploadFiles,rememberTrainingForm,restoreTrainingForm,renderPage,setParams(v){params=new URLSearchParams(v);},setState(v){state=v;},setRoute(v){route=v;},setPending(v){pendingTrainingVersion=v;}};})()`,context);
  const state={images:[],batches:[],classes:[],versions:[],models:[],jobs:[],events:[],settings:{},connection:{demo:true,ml:{ready:false}}};
  context.fetch=async()=>({ok:true,json:async()=>state});context.client.setState(state);context.client.setRoute('board');
  return {context,client:context.client,elements,upload,location,state};
}

test('image test opens in place without refetching the full state or reloading the page',async()=>{
  const h=await harness();
  h.location.hash='#/test';h.location.pathname='/cable/';h.location.origin='http://server:7777';
  h.context.inspectionPage=()=>'<div>test-view</div>';
  let target;
  h.context.mountInspection=options=>{target=options.baseUrl;};
  h.context.fetch=async()=>{throw Error('navigation must not fetch state');};
  await h.client.renderPage();
  assert.equal(h.elements.get('#main').innerHTML,'<div>test-view</div>');
  assert.equal(target,'http://server:7777/cable/test');
  assert.equal(h.location.hash,'#/test');
});

test('upload refresh adds the batch while preserving the page and upload form',async()=>{
  const h=await harness();h.elements.get('#main').innerHTML='page-must-stay';
  h.state.batches.push({id:'new-batch',name:'업로드된 배치',stage:'new',created:'2026-10-16T00:00:00Z'});
  h.state.images.push({id:'uploaded-image',batch:'new-batch',file:'uploaded.jpg',status:'todo',deleted:false});
  await h.client.syncUploadedBoard();
  assert.match(h.elements.get('#board-columns').innerHTML,/업로드된 배치/);
  assert.equal(h.elements.get('#main').innerHTML,'page-must-stay');
  assert.equal(h.upload.values.batch,'새 배치');
});

test('upload uses the side-panel fields, retains original dimensions, and reports completion',async()=>{
  const h=await harness();const uploads=[];
  h.context.fetch=async(url,options)=>{
    if(url==='/api/upload'){
      const metadata=JSON.parse(options.headers['X-Upload-Meta']);uploads.push(metadata);
      h.state.batches=[{id:'uploaded',name:metadata.batch,stage:'new',created:'2026-10-16T00:00:00Z'}];
      h.state.images=[{id:'image-id',batch:'uploaded',file:'uploaded.png',status:'todo',deleted:false}];
      return {ok:true,json:async()=>({id:'image-id'})};
    }
    return {ok:true,json:async()=>h.state};
  };
  await h.client.uploadFiles([{name:'사진_SensorA.png',size:1024}]);
  assert.equal(uploads.length,1);
  assert.deepEqual(JSON.parse(JSON.stringify(uploads[0])),{name:'사진_SensorA.png',width:1600,height:2160,batch:'새 배치',split:'valid',tags:['확인','센서A'],allow_duplicates:false});
  assert.match(h.elements.get('#upload-results').innerHTML,/추가 1장.*실패 0장/);
  assert.match(h.elements.get('#board-columns').innerHTML,/새 배치/);
  assert.equal(h.upload.values.tags,'확인,센서A');
  assert.equal(h.elements.get('label[for=files]').style.pointerEvents,'');
});

test('creating a version selects it while retaining the entered training options',async()=>{
  const h=await harness();const fields={
    version_id:{tagName:'SELECT',value:'old',options:[{value:'old'},{value:'new'}]},
    epochs:{tagName:'INPUT',value:'73'},name:{tagName:'INPUT',value:'설정 유지 확인'},
  };
  const form={values:{version_id:'old',epochs:'73',name:'설정 유지 확인'},elements:{namedItem:name=>fields[name]}};
  h.elements.set('[data-form="training"]',form);
  h.client.rememberTrainingForm();
  fields.epochs.value='40';fields.name.value='';fields.version_id.value='';
  h.client.setPending('new');h.client.restoreTrainingForm();
  assert.equal(fields.version_id.value,'new');assert.equal(fields.epochs.value,'73');assert.equal(fields.name.value,'설정 유지 확인');
});

test('old upload and version links route to the combined workspaces',async()=>{
  const h=await harness();
  h.location.hash='#/upload';await h.client.renderPage();assert.equal(h.location.replaced,'#/board?upload=1');
  h.location.hash='#/versions';await h.client.renderPage();assert.equal(h.location.replaced,'#/train');
});


test('imported models display their source version and saved evaluation scores',async()=>{
 const h=await harness();
 const model={id:'import-one',name:'rtmins_v27',size:'l',classes:[],version_name:'v27',version_id:'external:cksgur:v27',created:'2026-10-16T00:00:00Z',imported:'2026-10-16T01:00:00Z',training_info:{img:[640,1536],epochs:40},metrics:{best_mask_mAP50:.654},evaluations:{v27:{source:'imported',version_name:'v27',metrics:{'coco/segm_mAP_50':.654,'coco/segm_mAP':.362}}}};
 h.state.models.push(model);
 assert.match(h.client.modelTable(),/v27/);
 assert.match(h.client.modelTable(),/0.654/);
 assert.match(h.client.importedModelDetails(model),/0.362/);
 assert.match(h.client.importedModelDetails(model),/640/);
});


test('board hides empty and trash-only batches unless explicitly shown',async()=>{
 const h=await harness();
 h.state.batches=[{id:'empty',name:'EMPTY_CARD',stage:'new'},{id:'trash',name:'TRASH_ONLY_CARD',stage:'review'},{id:'occupied',name:'OCCUPIED_CARD',stage:'done'}];
 h.state.images=[{id:'deleted',batch:'trash',deleted:true},{id:'visible',batch:'occupied',deleted:false,file:'real.jpg',status:'reviewed'}];
 let html=h.client.boardColumns();
 assert.ok(!html.includes('EMPTY_CARD'));assert.ok(!html.includes('TRASH_ONLY_CARD'));assert.ok(html.includes('OCCUPIED_CARD'));
 h.client.setParams('empty=1');html=h.client.boardColumns();assert.ok(html.includes('EMPTY_CARD'));assert.ok(html.includes('TRASH_ONLY_CARD'));
});


test('only the maximum displayed score is green and comparison uses the selected version',async()=>{
 const h=await harness();
 h.state.versions=[{id:'v1',name:'v1'},{id:'v2',name:'v2'}];
 h.state.models=[.6,.8,.7,null].map((score,i)=>({id:'m'+i,name:'model'+i,size:'l',version_id:'v1',metrics:{best_mask_mAP50:score},evaluations:{v2:{metrics:{'coco/segm_mAP_50':[.9,.5,.6,null][i]}}}}));
 let html=h.client.modelTable();assert.equal((html.match(/class="metric good"/g)||[]).length,1);assert.match(html,/class="metric good">0.800/);
 html=h.client.modelTable(true);assert.equal((html.match(/class="metric good"/g)||[]).length,1);assert.match(html,/class="metric good">0.900/);
});

test('settings show the connected database and include class management',async()=>{
 const h=await harness();const html=h.client.settingsPage();
 assert.ok(!html.includes('원본 DB 전달 대기'));assert.ok(html.includes('DB 연결'));assert.ok(html.includes('클래스 관리'));assert.ok(html.includes('GPU 서버 연결'));
 h.location.hash='#/classes';await h.client.renderPage();assert.equal(h.location.replaced,'#/settings?section=classes');
});


test('GPU header shows server-wide utilization, GiB memory and temperature, with stale status',async()=>{
 const h=await harness();const data={available:true,gpus:[{index:0,name:'RTX PRO 6000',utilization:12,memory_used_mib:2093,memory_total_mib:97887,temperature:45}]};
 const html=h.client.gpuStatus(data);assert.ok(html.includes('12%'));assert.ok(html.includes('2.0 / 95.6 GiB'));assert.ok(html.includes('45°C'));
 assert.ok(h.client.gpuStatus({...data,stale:true}).includes('갱신 지연'));
 assert.ok(!h.client.gpuStatus({available:false,reason:'로그인 필요'}).includes('0%'));
});


test('training offers a fresh model or existing model weights without a COCO prerequisite',async()=>{
 const h=await harness();h.state.models=[{id:'own-model',name:'my-rtmdet',size:'l'}];
 const html=h.client.trainingForm();assert.ok(html.includes('처음부터 학습'));assert.ok(html.includes('기존 모델에서 추가 학습'));assert.ok(html.includes('my-rtmdet'));assert.ok(!html.includes('COCO 사전학습'));
});


test('existing model selection enables the selector and follows the selected model size',async()=>{
 const h=await harness();h.state.models=[{id:'my-model',size:'s'}];
 const fields={start_mode:{value:'finetune'},resume_model:{value:'my-model'},size:{value:'l'}};const panel={hidden:true};
 h.elements.set('[data-form="training"]',{elements:{namedItem:n=>fields[n]},querySelector:()=>panel});
 h.client.syncTrainingMode();assert.equal(panel.hidden,false);assert.equal(fields.resume_model.required,true);assert.equal(fields.size.value,'s');assert.equal(fields.size.disabled,true);
 fields.start_mode.value='scratch';h.client.syncTrainingMode();assert.equal(panel.hidden,true);assert.equal(fields.resume_model.disabled,true);assert.equal(fields.size.disabled,false);
});


test('transfer progress and GPU work progress are shown as distinct stages',async()=>{
 const h=await harness();const p=h.client.jobProgress({mode:'train',progress:0,step:0,message:'GPU 서버로 전송 중 · 3474/4861개 · 752/1052 MB'});
 assert.ok(p.percent>71&&p.percent<72);assert.equal(p.label,'파일 전송 71.5%');
 const running=h.client.jobProgress({mode:'eval',progress:50,step:50,total_steps:100});assert.equal(running.label,'평가 50%');assert.ok(!running.detail.includes('epoch'));
 assert.equal(h.client.jobProgress({mode:'eval',message:'GPU 작업 실행 중'}).percent,null);
});

test('job center updates while open and preserves scroll without replacing other modals',async()=>{
 const h=await harness();const dialog=h.elements.get('#modal');dialog.open=true;dialog.dataset.view='jobs';dialog.scrollTop=120;
 const body=new Element();h.elements.set('#job-center-content',body);
 h.state.jobs=[{id:'job',mode:'train',name:'model',status:'running',created:'2026-10-16',message:'GPU 서버로 전송 중 · 4/10개 · 4/10 MB'}];
 h.client.syncJobCenter();assert.ok(body.innerHTML.includes('파일 전송 40.0%'));
 h.state.jobs[0].message='GPU 서버로 전송 중 · 7/10개 · 7/10 MB';h.client.syncJobCenter();assert.ok(body.innerHTML.includes('파일 전송 70.0%'));assert.equal(dialog.scrollTop,120);
 dialog.dataset.view='log';body.innerHTML='log stays';h.client.syncJobCenter();assert.equal(body.innerHTML,'log stays');
});

test('log copy uses the complete displayed text and reports clipboard errors',async()=>{
 const h=await harness(),el=new Element();el.textContent='Traceback\n한글 로그\nRuntimeError';h.elements.set('#job-log-text',el);
 let copied;h.context.navigator={clipboard:{writeText:async text=>{copied=text;}}};
 await h.client.copyJobLog();assert.equal(copied,el.textContent);assert.match(h.elements.get('#toast').textContent,/복사했습니다/);
 let selected=false;h.context.navigator.clipboard.writeText=async()=>{throw Error('denied');};
 h.context.document.createRange=()=>({selectNodeContents(value){assert.equal(value,el);}});
 h.context.window.getSelection=()=>({removeAllRanges(){},addRange(){selected=true;}});
 await h.client.copyJobLog();assert.equal(selected,true);assert.match(h.elements.get('#toast').textContent,/Ctrl\+C/);
});

test('resume labeling remembers the last editor image through reload and ignores list filters',async()=>{
 const storage=new Map(),h=await harness(storage);
 const first={id:'photo-one',name:'first.jpg',deleted:false,tags:[],note:'',annotations:[]},second={id:'photo-two',name:'second.jpg',deleted:false,tags:[],note:'',annotations:[]};
 h.state.images=[first,second];h.client.setParams('q=no-matching-photo');
 h.client.rememberLastEditor(first);assert.match(h.client.imagesPage(),/href="#\/annotate\/photo-one"[^>]*title="first.jpg"/);
 h.client.rememberLastEditor(second);assert.match(h.client.resumeLabelingButton(),/photo-two/);
 const reloaded=await harness(storage);reloaded.state.images=[first,second];
 assert.match(reloaded.client.resumeLabelingButton(),/photo-two/);
 second.deleted=true;assert.equal(reloaded.client.resumeLabelingButton(),'');
 reloaded.client.rememberLastEditor(second);assert.equal(storage.get('studio-last-editor-image'),'photo-two');
 reloaded.state.images=[];assert.equal(reloaded.client.resumeLabelingButton(),'');
 assert.doesNotMatch(h.client.imagesPage(true),/이어서 라벨링/);
});

test('opening the editor via a direct route records the resume target',async()=>{
 const storage=new Map(),h=await harness(storage);h.state.images=[{id:'last-open',name:'last.jpg',deleted:false}];
 h.location.hash='#/annotate/last-open';await h.client.renderPage();
 assert.equal(storage.get('studio-last-editor-image'),'last-open');
});

test('card clicks toggle selection after the first checkbox without opening the editor',async()=>{
 const h=await harness();h.client.setRoute('images');h.elements.set('#bulkbar',new Element());
 const marks={},card={classList:{toggle(name,value){marks[name]=value;}},querySelector(){return checkbox;}};
 const checkbox={dataset:{select:'photo'},checked:false,closest:()=>card};
 let prevented=false;const event={preventDefault(){prevented=true;},target:{closest:selector=>selector==='.imagecard'?card:null}};
 assert.equal(h.client.handleImageCardClick(event),false);assert.equal(prevented,false);
 h.client.setImageSelected(checkbox,true);assert.equal(checkbox.checked,true);
 assert.equal(h.client.handleImageCardClick(event),true);assert.equal(checkbox.checked,false);assert.equal(marks.selected,false);assert.equal(prevented,true);
 prevented=false;assert.equal(h.client.handleImageCardClick(event),false);assert.equal(prevented,false);
 h.client.setImageSelected(checkbox,true);
 const controlEvent={preventDefault(){throw Error('native controls must retain their action');},target:{closest:selector=>selector==='.imagecard'?card:{}}};
 assert.equal(h.client.handleImageCardClick(controlEvent),false);
});

test('validation progress reflects the current phase and resets at the next training epoch',async()=>{
 const h=await harness();const text='Epoch(train)  [1][1700/1731]\nEpoch(val)  [1][ 50/963]\nEpoch(val)  [1][800/963]';
 const validation=h.client.validationFromLog(text);assert.equal(validation.step,800);assert.equal(validation.total,963);
 const progress=h.client.jobProgress({mode:'train',progress:2.5,validation});
 assert.match(progress.label,/valid 검증 83.1%/);assert.match(progress.detail,/800 \/ 963장/);
 assert.equal(h.client.validationFromLog(text+'\nEpoch(train)  [2][ 50/1731]'),null);
 const direct=h.client.jobProgress({mode:'train',progress:2.5,message:'valid 검증 중 · epoch 1 · 800/963'});assert.equal(direct.label,progress.label);
 h.state.jobs=[{id:'running',mode:'train',status:'running',step:1731}];
 h.context.fetch=async url=>{assert.equal(url,'/api/jobs/running/log');return {ok:true,json:async()=>({text})};};
 await h.client.syncValidationProgress();assert.equal(h.state.jobs[0].validation.step,800);
});

test('scrolling near the end appends photos without replacing cards or changing the URL',async()=>{
 const h=await harness();h.client.setRoute('images');
 h.state.images=Array.from({length:101},(_,i)=>({id:'p'+i,name:String(i).padStart(3,'0')+'.jpg',file:i+'.jpg',width:100,height:100,status:'todo',split:'',annotations:[],tags:[],deleted:false}));
 const html=h.client.imagesPage();assert.equal((html.match(/class="card imagecard/g)||[]).length,48);assert.doesNotMatch(html,/load-more/);assert.match(html,/image-list-end/);
 const grid=new Element();grid.innerHTML='existing-cards';let appended='';grid.insertAdjacentHTML=(where,value)=>{assert.equal(where,'beforeend');appended+=value;};h.elements.set('.imagegrid',grid);
 const sentinel=new Element();sentinel.remove=()=>h.elements.delete('#image-list-end');h.elements.set('#image-list-end',sentinel);h.elements.set('#image-count',new Element());h.elements.set('#select-all',new Element());
 let notify,disconnected=false;
 h.context.IntersectionObserver=class{constructor(callback,options){notify=callback;assert.equal(options.rootMargin,'400px 0px');}observe(el){assert.equal(el,sentinel);}disconnect(){disconnected=true;}};
 h.client.observeImageList();notify([{isIntersecting:false}]);assert.equal(appended,'');
 notify([{isIntersecting:true}]);assert.equal(h.client.visibleImageLimit(),96);assert.equal((appended.match(/class="card imagecard/g)||[]).length,48);
 notify([{isIntersecting:true}]);assert.equal(h.client.visibleImageLimit(),101);assert.equal((appended.match(/class="card imagecard/g)||[]).length,53);assert.equal(disconnected,true);assert.equal(h.elements.has('#image-list-end'),false);
 assert.equal(grid.innerHTML,'existing-cards');assert.equal(h.location.hash,'#/board');
 h.client.setParams('status=todo');assert.equal(h.client.visibleImageLimit(),48);
});

test('status tabs retain the chosen board and other filters and only reset pagination',async()=>{
 const h=await harness();h.client.setParams('batch=board-A&sensor=A&cls=1&split=train&q=cable&sort=updated&view=gray&status=reviewed&page=3');
 const html=h.client.imagesPage(),pills=html.match(/<div class="pills">(.*?)<\/div>/)[1];
 const links=[...pills.matchAll(/href="([^"]+)"/g)].map(m=>new URLSearchParams(m[1].replaceAll('&amp;','&').split('?')[1]));
 assert.equal(links.length,6);
 for(const [i,q] of links.entries()){
  for(const [key,value] of Object.entries({batch:'board-A',sensor:'A',cls:'1',split:'train',q:'cable',sort:'updated',view:'gray'}))assert.equal(q.get(key),value);
  assert.equal(q.has('page'),false);assert.equal(q.get('status'),[null,'todo','reviewed','ambiguous','auto','unlabeled'][i]);
 }
});

test('selected comparison chart uses the same evaluated split, preserves zero and omits missing values',async()=>{
 const h=await harness();
 h.client.setState({versions:[{id:'v1'},{id:'v2'}],models:[{id:'a',name:'Alpha',size:'l',evaluations:{v1:{metrics:{'coco/segm_mAP_50':0,'coco/segm_mAP':.25,'coco/bbox_mAP_50':.9}}}},{id:'b',name:'Beta',size:'s',evaluations:{v2:{metrics:{'coco/segm_mAP_50':.99}}}}]});
 h.client.setParams({version:'v1'});h.client.comparedModels.set('v1',new Set(['a','b']));
 const html=h.client.comparisonChart();assert.match(html,/Alpha/);assert.doesNotMatch(html.match(/<svg[\s\S]*?<\/svg>/)[0],/Beta/);assert.match(html,/현재 기준의 평가 결과 없음/);assert.match(html,/0.0/);assert.match(html,/25.0/);assert.match(html,/90.0/);
 h.client.setParams({version:'v2'});assert.doesNotMatch(h.client.comparisonChart(),/Alpha/);
});

test('each metric highlights its own best selected value and all ties',async()=>{
 const h=await harness(),row=(id,a,b,c)=>({id,name:id,size:'l',evaluations:{v:{metrics:{'coco/segm_mAP_50':a,'coco/segm_mAP':b,'coco/bbox_mAP_50':c}}}});
 h.client.setState({versions:[{id:'v'}],models:[row('A',.618,.335,.683),row('B',.602,.319,.656),row('C',.618,.333,.686),row('unselected',.99,.99,.99)]});h.client.setParams({version:'v'});h.client.comparedModels.set('v',new Set(['A','B','C']));
 const html=h.client.comparisonChart();assert.equal((html.match(/data-best-metric=/g)||[]).length,4);assert.equal((html.match(/data-best-metric="coco\/segm_mAP_50"/g)||[]).length,2);assert.match(html,/33.5점 · 최고/);assert.match(html,/68.6점 · 최고/);assert.doesNotMatch(html,/99.0/);
});

test('latest completed evaluation selects its dataset and a different dataset explains missing results without disabling model selection',async()=>{
 const h=await harness();h.client.setState({versions:[{id:'v27',name:'v27'},{id:'v31',name:'v31'}],jobs:[{mode:'eval',status:'completed',version_id:'v31',finished:'2026-10-19T02:00:00Z'}],models:[{id:'f',name:'f390a',size:'l',evaluations:{v31:{metrics:{'coco/segm_mAP_50':.596}}}}]});
 h.client.setParams({});assert.equal(h.client.comparisonVersion(),'v31');assert.match(h.client.modelTable(true),/0.596/);
 h.client.setParams({version:'v27'});const html=h.client.modelTable(true);assert.match(html,/이 기준 평가 없음/);assert.match(html,/v31 결과 보기/);assert.doesNotMatch(html,/<input[^>]+data-compare-model[^>]+disabled/);
});

test('train batch choices show only populated done batches and bind actual IDs',async()=>{
 const h=await harness();h.client.setState({batches:[{id:'review-first',name:'검수 배치',stage:'review'},{id:'done-real',name:'완료 배치',stage:'done'},{id:'done-empty',name:'빈 완료',stage:'done'}],images:[{id:'r',batch:'review-first',split:'train',status:'reviewed'},{id:'d',batch:'done-real',split:'train',status:'reviewed'}]});
 const html=h.client.trainBatchChoices();assert.match(html,/완료 배치/);assert.match(html,/value="done-real"/);assert.doesNotMatch(html,/검수 배치|빈 완료|review-first/);
});


test('pending done batches stay selectable and version preview explains omitted new uploads',async()=>{
 const h=await harness();h.client.setState({batches:[{id:'new',name:'newData <serial>',stage:'done'},{id:'review',name:'not-done',stage:'review'}],images:[{batch:'new',split:'',status:'reviewed'},{batch:'review',split:'',status:'reviewed'}]});
 const choices=h.client.trainBatchChoices();assert.match(choices,/value="new"/);assert.match(choices,/미분할 1장/);assert.doesNotMatch(choices,/not-done/);
 const html=h.client.versionPreviewHTML({counts:{train:3465,valid:963,test:440},pending_count:80,pending_batches:[{id:'new',name:'newData <serial>',count:52},{id:'mix',name:'newData - mix',count:28}],excluded:{automatic_label:37}});
 assert.match(html,/80장/);assert.match(html,/52장/);assert.match(html,/28장/);assert.match(html,/분할 적용/);assert.match(html,/3,465/);assert.match(html,/newData &lt;serial&gt;/);assert.doesNotMatch(html,/<serial>/);
});
