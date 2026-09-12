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
