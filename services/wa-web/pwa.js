'use strict';
(() => {
 let promptEvent;
 const standalone=()=>matchMedia('(display-mode: standalone)').matches||navigator.standalone===true;
 const buttons=document.querySelectorAll('[data-install]');
 function refresh(){buttons.forEach(b=>b.hidden=standalone());}
 window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();promptEvent=e;refresh();});
 window.addEventListener('appinstalled',()=>{promptEvent=null;refresh();$('#install-dialog').close();toast('Aplicativo instalado.');});
 buttons.forEach(button=>button.addEventListener('click',async()=>{
  if(promptEvent){const event=promptEvent;promptEvent=null;await event.prompt();await event.userChoice;return;}
  const ios=/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
  $('#install-instructions').textContent=ios?'No Safari, toque em Compartilhar, escolha “Adicionar à Tela de Início” e confirme em “Adicionar”. Depois, abra pelo ícone na tela inicial.':'Abra o menu do Chrome ou Edge e escolha “Instalar aplicativo” ou “Adicionar à tela inicial”. Se a opção ainda não aparecer, aguarde o carregamento e tente novamente.';
  $('#account-dialog').close();$('#install-dialog').showModal();
 }));
 if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{/* Manual installation instructions remain available. */});
 refresh();
})();

// Push permission is requested only from the user's explicit button click.
(() => {
 const status=()=>document.querySelector('#push-status');
 const supported=()=>('serviceWorker' in navigator)&&('PushManager' in window)&&('Notification' in window);
 let busy=false,target=new URL(location.href).searchParams.get('chat');
 function openTarget(){if(!target)return false;const c=chats.find(c=>c.jid===target||(c.jids||[]).includes(target));if(!c)return false;target=null;const url=new URL(location.href);url.searchParams.delete('chat');history.replaceState(history.state,'',url);openChat(c);return true;}
 async function refresh(){
  if(!session)return;
  if(!supported()){status().textContent='No iPhone, instale pela Tela de Início e abra pelo ícone para ativar notificações.';return;}
  try{
   const registration=await navigator.serviceWorker.ready,subscription=await registration.pushManager.getSubscription();
   document.querySelector('#push-enable').hidden=Boolean(subscription);document.querySelector('#push-disable').hidden=!subscription;
   const config=await api('/api/push');
   status().textContent=subscription?(config.lastError||'Notificações ativadas neste aparelho.'):'Ative para receber avisos mesmo com o aplicativo fechado.';
   if(subscription&&!localOnly)await post('/api/push/subscribe',subscription.toJSON());
  }catch{status().textContent='Conecte-se para verificar as notificações.';}
 }
 async function disable(){
  if(!supported())return;
  try{
   const registration=await navigator.serviceWorker.ready,subscription=await registration.pushManager.getSubscription();
   if(subscription){
    try{localStorage.setItem('wa-push-remove',subscription.endpoint);}catch{}
    await subscription.unsubscribe();
    try{await post('/api/push/unsubscribe',{endpoint:subscription.endpoint});localStorage.removeItem('wa-push-remove');}catch{}
   }
   for(const notification of await registration.getNotifications())notification.close();
  }catch{/* Browser subscription can also be revoked in device settings. */}
 }
 async function enable(){
  if(busy)return;busy=true;
  try{
   if(!supported())throw new Error('Instale o aplicativo na Tela de Início e abra pelo ícone para ativar.');
   if(localOnly)throw new Error('Conecte-se para ativar as notificações.');
   const permission=await Notification.requestPermission();
   if(permission!=='granted')throw new Error('Permita as notificações nas configurações deste aplicativo no celular.');
   const config=await api('/api/push');if(!config.available)throw new Error('Notificações indisponíveis no servidor.');
   const registration=await navigator.serviceWorker.ready;
   const key=Uint8Array.from(atob(config.publicKey.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-config.publicKey.length%4)%4)),c=>c.charCodeAt(0));
   const subscription=await registration.pushManager.getSubscription()||await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
   try{await post('/api/push/subscribe',subscription.toJSON());}catch(e){await subscription.unsubscribe();throw e;}
   await refresh();
  }catch(e){status().textContent=e.message;}finally{busy=false;}
 }
 window.waPush={disable,openTarget};
 document.querySelector('#push-enable').onclick=enable;
 document.querySelector('#push-disable').onclick=async()=>{await disable();await refresh();};
 document.querySelector('#account').addEventListener('click',refresh);
 navigator.serviceWorker?.addEventListener('message',e=>{if(e.data?.type==='wa-open-chat'){target=String(e.data.jid||'');if(session)loadList().then(openTarget);}});
 window.addEventListener('online',async()=>{const endpoint=localStorage.getItem('wa-push-remove');if(endpoint&&session)try{await post('/api/push/unsubscribe',{endpoint});localStorage.removeItem('wa-push-remove');}catch{}});
})();
