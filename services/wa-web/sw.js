// Public shell only. API responses, media and credentials never enter CacheStorage.
const CACHE='wa-public-v3',VERSION='20260913-6';
const SHELL=['/','/offline.html','/manifest.webmanifest','/icon-192.png','/icon-512.png','/apple-touch-icon.png',
 ...['style.css','cache.js','app.js','voice.js','pwa.js'].map(name=>'/'+name+'?v='+VERSION)];
self.addEventListener('install',event=>event.waitUntil((async()=>{
 const cache=await caches.open(CACHE);
 await cache.addAll(SHELL.map(url=>new Request(url,{cache:'reload'})));
 // No skipWaiting: existing recording/sending tabs retain their current worker.
})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
 for(const name of await caches.keys())if(name.startsWith('wa-public-')&&name!==CACHE)await caches.delete(name);
 await self.clients.claim();
})()));
self.addEventListener('fetch',event=>{
 const request=event.request,url=new URL(request.url);
 if(request.method!=='GET'||url.origin!==self.location.origin||url.pathname.startsWith('/api/'))return;
 if(request.mode==='navigate'&&url.pathname==='/'){
  event.respondWith((async()=>{
   const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),4000);
   try{const response=await fetch(request,{signal:controller.signal});if(response.ok)return response;}catch{}
   finally{clearTimeout(timer);}
   return (await (await caches.open(CACHE)).match('/'))||Response.error();
  })());return;
 }
 if(!SHELL.includes(url.pathname+url.search))return;
 event.respondWith((async()=>{
  const saved=await (await caches.open(CACHE)).match(url.pathname+url.search);
  return saved||fetch(request);
 })());
});
