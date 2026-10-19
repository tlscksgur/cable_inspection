export const shortcutActions=[
 ['review','검수 완료 후 다음','R'],['next','그냥 다음으로','ArrowRight'],['prev','이전 사진','ArrowLeft'],
 ['ambiguous','애매로 표시 후 다음','U'],['unreview','검수 전으로 되돌리기','Q'],
 ['finish','그리던 다각형 완성','Enter'],['cancel','그리기·선택 취소','Escape'],
 ['polygon','다각형 도구','N'],['box','박스 도구','B'],['select','선택·이동 도구','V'],
 ['save','저장','Ctrl+S'],['undo','되돌리기','Ctrl+Z'],['redo','다시 실행','Ctrl+Shift+Z'],
 ['delete','선택 라벨·마지막 점 삭제','Delete'],['labels','라벨 표시','L'],
 ['gray','흑백','G'],['invert','반전','I'],['fit','전체 보기','0'],['pan','누른 채 화면 이동','Space']
];
export function eventShortcut(event){
 if(['Control','Meta','Alt','Shift','Tab'].includes(event.key)||event.isComposing)return '';
 let key=event.code?.startsWith('Key')?event.code.slice(3):event.code?.startsWith('Digit')?event.code.slice(5):event.key;
 if(key===' '||event.code==='Space')key='Space';
 if(!key)return '';
 if(key.length===1)key=key.toUpperCase();
 return [(event.ctrlKey||event.metaKey)?'Ctrl':'',event.altKey?'Alt':'',event.shiftKey?'Shift':'',key].filter(Boolean).join('+');
}
export function resolvedShortcuts(settings={}){
 const custom=settings.shortcuts||{};
 return Object.fromEntries(shortcutActions.map(([id,,key])=>[id,typeof custom[id]==='string'?custom[id]:key]));
}
export function validateShortcuts(values,classes=[]){
 const used=new Map();
 for(const [id,label] of shortcutActions){
  const key=values[id]||'';if(!key)continue;
  if(!/^(Ctrl\+)?(Alt\+)?(Shift\+)?([A-Z0-9]|ArrowLeft|ArrowRight|ArrowUp|ArrowDown|Enter|Escape|Space|Delete|Backspace|Home|End|PageUp|PageDown)$/.test(key))throw Error(label+': 지원하지 않는 키 조합입니다.');
  if(['Ctrl+R','Ctrl+W','Ctrl+T','Ctrl+L','Ctrl+N','Alt+F4'].includes(key))throw Error(key+'는 브라우저에서 사용하는 키입니다.');
  if(used.has(key))throw Error(key+': '+used.get(key)+' / '+label+' 단축키가 겹칩니다.');
  if(classes.some(c=>String(c.shortcut).toUpperCase()===key))throw Error(key+'는 클래스 선택에 사용 중입니다.');
  used.set(key,label);
 }
 return values;
}
export function shortcutLabel(key){return ({ArrowLeft:'←',ArrowRight:'→',Space:'Space',Escape:'Esc'})[key]||key||'미지정';}
