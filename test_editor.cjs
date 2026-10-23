const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function harness(status='todo',custom={}){
 const requests=[],navigated=[],messages=[],listeners={};
 class Element{
  constructor(){this.innerHTML='';this.textContent='';this.style={};this.dataset={};this.clientWidth=1000;this.clientHeight=600;this.handlers={};this.attrs={};}
  addEventListener(name,fn){this.handlers[name]=fn;}
  setAttribute(name,value){this.attrs[name]=value;} focus(options){this.focusOptions=options;}
  setPointerCapture(){} hasPointerCapture(){return false;} releasePointerCapture(){}
  createSVGPoint(){return {x:0,y:0,matrixTransform(){return {x:this.x,y:this.y};}};} getScreenCTM(){return {inverse:()=>({})};}
 }
 const elements=new Map();
 const document={querySelector(selector){if(!elements.has(selector))elements.set(selector,new Element());return elements.get(selector);},querySelectorAll(){return [];},addEventListener(name,fn,options={}){(listeners[name]??=[]).push({fn,signal:options.signal});}};
 const image={id:'first',name:'photo.jpg',file:'first.jpg',width:4096,height:2160,batch:'batch',split:'train',status,annotations:[],tags:[],note:'',deleted:false,revision:1};
 const state={images:[image,{...image,id:'second',name:'photo2.jpg',file:'second.jpg'}],classes:[{id:'1',name:'bulge',color:'#aeff00',shortcut:'1'}],batches:[{id:'batch',name:'my batch'}],models:[],settings:{shortcuts:custom}};
 const context=vm.createContext({document,window:{addEventListener(){}},structuredClone,AbortController,ResizeObserver:class{observe(){}disconnect(){}},crypto:require('node:crypto').webcrypto,setTimeout:()=>0,clearTimeout(){},location:{hash:''},console,
  esc:v=>String(v??''),icon:()=>'',toast:(v)=>messages.push(v),goImage:id=>navigated.push(id),predictionForm(){},
  api:async(url,body)=>{requests.push({url,body:structuredClone(body)});if(context.failSave)throw Error('save failed');return {...image,...body,revision:body.revision+1};}});
 const shortcuts=fs.readFileSync(path.join(__dirname,'web/shortcuts.js'),'utf8').replace(/\bexport\s+/g,'');
 const editor=fs.readFileSync(path.join(__dirname,'web/editor.js'),'utf8').replace(/^import .*;$/gm,'').replace(/\bexport\s+/g,'');
 vm.runInContext(`${shortcuts}\n${editor}\nglobalThis.editor={openEditor,closeEditor,eventShortcut,validateShortcuts,resolvedShortcuts};`,context);
 context.editor.openEditor(image,state,async()=>{});
 const target={tagName:'svg',closest:()=>null};
 async function key(key,code,extra={}){const event={key,code,target,preventDefault(){},...extra};for(const {fn,signal} of listeners.keydown||[])if(!signal?.aborted)await fn(event);}
 async function click(action){await elements.get('#main').handlers.click({target:{closest(selector){return selector==='[data-action^="editor-"]'?{dataset:{action:'editor-'+action}}:null;}}});}
 return {context,state,elements,requests,navigated,messages,key,click};
}

test('skip saves edits and advances without marking an image reviewed',async()=>{
 const h=harness();h.elements.get('#main').handlers.input({target:{name:'note',value:'a note'}});
 await h.click('next');assert.equal(h.requests[0].body.status,'todo');assert.equal(h.requests[0].body.note,'a note');assert.deepEqual(h.navigated,['second']);
});

test('review and ambiguous persist separate states before navigation',async()=>{
 for(const [action,status] of [['review','reviewed'],['ambiguous','ambiguous']]){
  const h=harness();await h.click(action);assert.equal(h.requests[0].body.status,status);assert.equal(h.state.images[0].status,status);assert.deepEqual(h.navigated,['second']);assert.equal(h.elements.get('#main').dataset.reviewState,status);
 }
});

test('review can be undone without moving to another image',async()=>{
 const h=harness('reviewed');await h.click('unreview');assert.equal(h.requests[0].body.status,'todo');assert.deepEqual(h.navigated,[]);
});

test('Enter no longer marks an image reviewed; custom review key is used',async()=>{
 const h=harness('todo',{review:'K'});await h.key('Enter','Enter');await h.key('r','KeyR');assert.equal(h.requests.length,0);assert.deepEqual(h.navigated,[]);
 await h.key('k','KeyK');assert.equal(h.requests[0].body.status,'reviewed');assert.deepEqual(h.navigated,['second']);
});

test('failed review save does not advance or change the server state',async()=>{
 const h=harness();h.context.failSave=true;await h.click('review');assert.deepEqual(h.navigated,[]);assert.equal(h.state.images[0].status,'todo');assert.ok(h.messages.includes('save failed'));
});

test('shortcut validation rejects duplicate and class keys and supports modifiers',()=>{
 const h=harness();const keys=h.context.editor.resolvedShortcuts();
 assert.throws(()=>h.context.editor.validateShortcuts({...keys,review:'G'}),/겹칩니다/);
 assert.throws(()=>h.context.editor.validateShortcuts({...keys,review:'1'},h.state.classes),/클래스 선택/);
 assert.equal(h.context.editor.eventShortcut({key:'s',code:'KeyS',ctrlKey:true}),'Ctrl+S');
 assert.equal(h.context.editor.eventShortcut({key:'r',code:'KeyR',shiftKey:true}),'Shift+R');
});

test('review toolbar is centered separately from delete controls and states have text',()=>{
 const h=harness('ambiguous');const html=h.elements.get('#main').innerHTML;
 assert.ok(html.includes('class="editor-review-actions"'));assert.ok(html.includes('그냥 다음'));assert.ok(html.includes('class="editor-utilities"'));assert.equal(h.elements.get('#editor-review-state').textContent,'? 애매');
});


test('first polygon click focuses without scrolling and keeps the image viewBox fixed',()=>{
 const h=harness(),svg=h.elements.get('#editor-svg'),before=svg.attrs.viewBox;
 svg.handlers.pointerdown({button:0,clientX:50,clientY:50,detail:1,target:{closest:()=>null,hasAttribute:()=>false,dataset:{}}});
 assert.equal(svg.focusOptions.preventScroll,true);assert.equal(svg.attrs.viewBox,before);
});

function pointer(h,x,y,label){return {button:0,pointerId:1,clientX:x,clientY:y,detail:1,target:{closest:()=>null,hasAttribute:()=>false,dataset:label?{label}:{}}};}
async function reopen(h,image){await h.context.editor.closeEditor();h.context.editor.openEditor(image,h.state,async()=>{});}
async function classClick(h,id){await h.elements.get('#main').handlers.click({target:{closest:selector=>selector==='[data-editor-class]'?{dataset:{editorClass:id}}:null}});}

for(const method of ['Enter','first-point','double-click'])test(`polygon closes and saves over HTTP without crypto.randomUUID: ${method}`,async()=>{
 const h=harness(),svg=h.elements.get('#editor-svg');
 const webcrypto=require('node:crypto').webcrypto;
 h.context.crypto={getRandomValues:webcrypto.getRandomValues.bind(webcrypto)};
 for(const [x,y] of [[50,50],[150,50],[150,150]])svg.handlers.pointerdown(pointer(h,x,y));
 if(method==='Enter')await h.key('Enter','Enter');
 else if(method==='first-point')svg.handlers.pointerdown(pointer(h,50,50));
 else svg.handlers.dblclick({preventDefault(){}});
 await h.click('save');
 const annotations=h.requests.at(-1)?.body.annotations;
 assert.equal(annotations?.length,1,h.messages.join('; '));
 assert.equal(annotations[0].points.length,3);
 assert.match(annotations[0].id,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
 assert.equal(h.elements.get('#draft').innerHTML,'');
});

test('boxes also save over HTTP without crypto.randomUUID',async()=>{
 const h=harness(),svg=h.elements.get('#editor-svg'),webcrypto=require('node:crypto').webcrypto;
 h.context.crypto={getRandomValues:webcrypto.getRandomValues.bind(webcrypto)};
 await h.click('box');svg.handlers.pointerdown(pointer(h,50,50));svg.handlers.pointermove(pointer(h,150,150));svg.handlers.pointerup({pointerId:1});
 await h.click('save');assert.equal(h.requests.at(-1)?.body.annotations[0].points.length,4);
});

test('double pointer click closes even when SVG repaint suppresses native dblclick',async()=>{
 const h=harness(),svg=h.elements.get('#editor-svg');
 for(const [x,y,timeStamp] of [[50,50,100],[150,50,200],[150,150,300],[150,150,350]])
  svg.handlers.pointerdown({...pointer(h,x,y),detail:0,timeStamp});
 await h.click('save');
 assert.equal(h.requests.at(-1)?.body.annotations.length,1);
 assert.equal(h.requests.at(-1).body.annotations[0].points.length,3);
 assert.equal(h.elements.get('#draft').innerHTML,'');
});

test('review advance retains drawing tool and class but does not copy labels',async()=>{
 const h=harness();h.state.classes.push({id:'2',name:'dent',color:'#ff0000',shortcut:'2'});
 await h.click('box');await classClick(h,'2');await h.click('review');
 await reopen(h,h.state.images[1]);
 const svg=h.elements.get('#editor-svg');svg.handlers.pointerdown(pointer(h,50,50));svg.handlers.pointermove(pointer(h,100,100));svg.handlers.pointerup({pointerId:1});
 await h.click('save');const saved=h.requests.at(-1).body;
 assert.equal(saved.annotations.length,1);assert.equal(saved.annotations[0].class_id,'2');assert.equal(saved.annotations[0].points.length,4);assert.equal(saved.status,'todo');
});

test('existing shapes can be clicked, reclassified and deleted while drawing',async()=>{
 for(const tool of ['polygon','box']){
  const h=harness();h.state.classes.push({id:'2',name:'dent',color:'#ff0000',shortcut:'2'});
  h.state.images[0].annotations=[{id:'shape',class_id:'1',points:[[10,10],[80,10],[80,80]],source:'human'}];
  await reopen(h,h.state.images[0]);await h.click(tool);
  h.elements.get('#editor-svg').handlers.pointerdown(pointer(h,30,30,'shape'));
  assert.equal(h.elements.get('#selected-label-actions').hidden,false);
  await classClick(h,'2');await h.click('save');
  assert.equal(h.requests.at(-1).body.annotations.length,1);assert.equal(h.requests.at(-1).body.annotations[0].class_id,'2');
  await h.click('delete-label');await h.click('save');assert.equal(h.requests.at(-1).body.annotations.length,0);
 }
});
