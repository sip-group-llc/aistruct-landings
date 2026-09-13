'use strict';
(() => {
 let loadedEpoch=-1,busy=false,photo=null,photoUrl='',loadToken=0;
 const dialog=$('#my-profile-dialog'),fields=$('#my-profile-fields'),status=$('#my-profile-status');
 function preview(url){const box=$('#my-photo-preview');box.replaceChildren();if(url){const image=document.createElement('img');image.src=url;image.alt='Sua foto de perfil';box.append(image);}else box.textContent='Sem foto';}
 function releasePhoto(){if(photoUrl)URL.revokeObjectURL(photoUrl);photoUrl='';photo=null;$('#my-photo-file').value='';$('#save-my-photo').disabled=true;}
 async function load(){
  if(busy)return;const epoch=authEpoch,token=++loadToken;fields.disabled=true;status.textContent='Carregando seu perfil…';
  try{const data=await api('/api/me');if(epoch!==authEpoch||token!==loadToken)return;
   releasePhoto();$('#my-name').value=data.name||'';$('#my-about').value=data.about||'';$('#my-number').textContent=phone({number:data.number});preview(data.picture);loadedEpoch=epoch;fields.disabled=false;status.textContent='';
  }catch(e){if(epoch===authEpoch&&token===loadToken)status.textContent=e.message;}
 }
 async function save(field){
  if(busy||fields.disabled)return;if(localOnly){status.textContent='Conecte-se à internet para alterar seu perfil.';return;}
  const value=$('#my-'+field).value.trim(),input=$('#my-'+field);if(!value){status.textContent=field==='name'?'Preencha seu nome.':'Preencha seu recado.';input.focus();return;}
  busy=true;fields.disabled=true;$('#reload-my-profile').disabled=true;const epoch=authEpoch;status.textContent='Salvando…';
  try{await post('/api/me',{field,value});if(epoch===authEpoch)status.textContent=field==='name'?'Nome atualizado no WhatsApp.':'Recado atualizado no WhatsApp.';}
  catch(e){if(epoch===authEpoch)status.textContent=e.uncertain?'Não foi possível confirmar. Recarregue o perfil antes de tentar novamente.':e.message;}
  finally{busy=false;fields.disabled=epoch!==authEpoch;$('#reload-my-profile').disabled=false;}
 }
 $('#my-profile').onclick=()=>{$('#account-dialog').close();dialog.showModal();if(loadedEpoch!==authEpoch)load();};
 $('#reload-my-profile').onclick=load;
 $('#save-my-name').onclick=()=>save('name');$('#save-my-about').onclick=()=>save('about');
 $('#my-photo-file').onchange=()=>{
  const chosen=$('#my-photo-file').files[0];if(!chosen)return;
  if(!['image/png','image/jpeg'].includes(chosen.type)||chosen.size>5*1024*1024){releasePhoto();preview('');status.textContent='Escolha PNG ou JPEG de até 5 MB. Recarregue para ver sua foto atual.';return;}
  if(photoUrl)URL.revokeObjectURL(photoUrl);photo=chosen;photoUrl=URL.createObjectURL(chosen);preview(photoUrl);$('#save-my-photo').disabled=false;status.textContent='Prévia da nova foto. Toque em Salvar foto para aplicar no WhatsApp.';
 };
 $('#save-my-photo').onclick=async()=>{
  if(busy||!photo)return;if(localOnly){status.textContent='Conecte-se à internet para alterar sua foto.';return;}const selected=photo,epoch=authEpoch;busy=true;fields.disabled=true;$('#reload-my-profile').disabled=true;status.textContent='Enviando foto…';
  try{await api('/api/me/picture',{method:'POST',body:selected,headers:{'Content-Type':selected.type},timeout:120000});if(epoch===authEpoch){photo=null;$('#save-my-photo').disabled=true;status.textContent='Foto atualizada. O WhatsApp pode levar alguns instantes para mostrá-la em todos os aparelhos.';}}
  catch(e){if(epoch===authEpoch)status.textContent=e.uncertain?'Não foi possível confirmar. Recarregue o perfil antes de tentar novamente.':e.message;}
  finally{busy=false;fields.disabled=epoch!==authEpoch;$('#reload-my-profile').disabled=false;}
 };
 const size=$('#message-size');try{const saved=localStorage.getItem('wa-message-size');if(['15','17','19'].includes(saved))size.value=saved;}catch{}
 size.onchange=()=>{const value=size.value;if(value==='auto')document.documentElement.style.removeProperty('--message-size');else if(['15','17','19'].includes(value))document.documentElement.style.setProperty('--message-size',value+'px');try{localStorage.setItem('wa-message-size',value);}catch{toast('Tamanho aplicado nesta sessão.');}if(current)updateJump();};
})();
