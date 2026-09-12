// Only a public offline page is cached. Conversations, media and credentials never enter CacheStorage.
const CACHE='wa-public-v1';
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(c=>c.add('/offline.html'))));
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('fetch',event=>{
 if(event.request.mode==='navigate'&&event.request.method==='GET'&&new URL(event.request.url).origin===self.location.origin){
  event.respondWith(fetch(event.request).catch(()=>caches.match('/offline.html')));
 }
});
