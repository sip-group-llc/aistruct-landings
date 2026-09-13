'use strict';
// Private structured data only. Authentication must establish scope before use.
window.waCache=(()=>{
 let scope='',generation=0,opening;
 const TTL=7*86400000;
 function database(){
  if(!opening)opening=new Promise((resolve,reject)=>{
   let expired=false;
   const timer=setTimeout(()=>{expired=true;opening=null;reject(new Error('Armazenamento indisponível'));},1500);
   let request;try{request=indexedDB.open('wa-local-v1',1);}catch(error){clearTimeout(timer);opening=null;reject(error);return;}
   request.onupgradeneeded=()=>request.result.createObjectStore('entries',{keyPath:'id'}).createIndex('savedAt','savedAt');
   request.onsuccess=()=>{clearTimeout(timer);const db=request.result;if(expired){db.close();return;}db.onversionchange=()=>{db.close();opening=null;};resolve(db);};
   request.onerror=()=>{clearTimeout(timer);opening=null;reject(request.error);};
   request.onblocked=()=>{clearTimeout(timer);expired=true;opening=null;reject(new Error('Armazenamento ocupado em outra aba'));};
  });return opening;
 }
 async function get(key){
  const owner=scope,epoch=generation;if(!owner)return null;
  try{const db=await database();if(epoch!==generation)return null;return await new Promise(resolve=>{
   const tx=db.transaction('entries'),request=tx.objectStore('entries').get(owner+'|'+key);
   request.onsuccess=()=>{const entry=request.result;resolve(epoch===generation&&entry&&(key.startsWith('draft:')||Date.now()-entry.savedAt<TTL)?entry.value:null);};
   request.onerror=()=>resolve(null);tx.onabort=()=>resolve(null);
  });}catch{return null;}
 }
 async function put(key,value){
  const owner=scope,epoch=generation;if(!owner)return false;
  try{const db=await database();if(epoch!==generation)return false;
   return await new Promise(resolve=>{const tx=db.transaction('entries','readwrite'),store=tx.objectStore('entries');store.put({id:owner+'|'+key,owner,savedAt:Date.now(),value});
    const count=store.getAllKeys();count.onsuccess=()=>{let excess=count.result.filter(id=>!id.includes('|draft:')).length-60;if(excess<=0)return;const cursor=store.index('savedAt').openCursor();cursor.onsuccess=()=>{const c=cursor.result;if(c&&excess>0){if(!c.value.id.endsWith('|startup')&&!c.value.id.includes('|draft:')){c.delete();excess--;}c.continue();}};};
    tx.oncomplete=()=>resolve(true);tx.onerror=tx.onabort=()=>resolve(false);});
  }catch{return false;}
 }
 async function clear(){
  const owner=scope;scope='';generation++;
  try{const db=await database();return await new Promise(resolve=>{
   const tx=db.transaction('entries','readwrite'),request=tx.objectStore('entries').openCursor();
   request.onsuccess=()=>{const c=request.result;if(c){if(c.value.owner===owner)c.delete();c.continue();}};
   tx.oncomplete=()=>resolve(true);tx.onerror=tx.onabort=()=>resolve(false);
  });}catch{return false;}
 }
 async function init(value){scope=typeof value==='string'?value:'';const owner=scope,epoch=++generation;
  try{const db=await database();const tx=db.transaction('entries','readwrite'),request=tx.objectStore('entries').openCursor();
   request.onsuccess=()=>{const c=request.result;if(c&&epoch===generation){if(c.value.owner!==owner||(!c.value.id.includes('|draft:')&&Date.now()-c.value.savedAt>=TTL))c.delete();c.continue();}};
  }catch{/* Live mode still works without IndexedDB. */}
 }
 function messages(list){
  const result=[];let bytes=0;
  for(const m of list.slice().reverse()){
   if(m.cacheable!==true||m.localUrl||m.localStatus||String(m.id).startsWith('local-'))continue;
   const copy={...m};delete copy.localUrl;const size=new TextEncoder().encode(JSON.stringify(copy)).length;
   if(bytes+size>512*1024)break;result.unshift(copy);bytes+=size;if(result.length>=200)break;
  }return result;
 }
 return {init,get,put,clear,messages};
})();
