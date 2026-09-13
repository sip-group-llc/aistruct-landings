'use strict';
// One recorder; drafts belong to their original conversation, even after navigation.
(() => {
 const drafts = new Map();
 let recording = null, pendingPermission = false, permissionEpoch = 0, timer;
 const maxBytes = 12 * 1024 * 1024;
 const micIcon = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>';
 $('#record').innerHTML = micIcon;
 const elapsed = r => r.elapsed + (r.recorder.state === 'recording' ? performance.now() - r.started : 0);
 function sync() {
  const draft = current && drafts.get(current.key), active = recording && recording.state === current;
  $('#voice-panel').hidden = !draft && !active;
  $('#text-row').hidden = Boolean(draft || active);
  $('#record').disabled = !current || current.sending || pendingPermission;
  $('#attach-audio').disabled = !current || current.sending || pendingPermission;
  $('#record').hidden = Boolean($('#txt').value.trim());
  $('#send').hidden = !$('#txt').value.trim();
  if (!draft && !active) return;
  $('#voice-recipient').textContent = current.chat.name || current.chat.number;
  $('#voice-live').hidden = !active;
  $('#voice-preview').hidden = !draft;
  $('#voice-preview-player').hidden = !draft;
  $('#voice-pause').hidden = !active;
  $('#voice-stop').hidden = !active;
  $('#voice-send').hidden = !draft;
  $('#voice-download').hidden = !draft;
  $('#voice-discard').disabled = Boolean(current.sending);
  $('#voice-send').disabled = Boolean(current.sending || draft?.uncertain);
  $('#voice-send').textContent = current.sending ? 'Enviando…' : draft?.uncertain ? 'Verifique a conversa' : 'Enviar áudio';
  $('#voice-note').textContent = draft?.uncertain ? 'O envio não foi confirmado. Verifique a conversa antes de enviar novamente. Você pode baixar o áudio.' : active ? 'Até 10 minutos. Pare para ouvir antes de enviar.' : 'Ouça antes de enviar. Este áudio fica aqui enquanto a página estiver aberta.';
  if (active) {
   const paused = recording.recorder.state === 'paused';
   $('#voice-pause').textContent = paused ? 'Continuar' : 'Pausar';
   $('#voice-live').classList.toggle('paused', paused);
   $('#voice-time').textContent = duration(Math.floor(elapsed(recording)/1000));
   $('#voice-status').textContent = paused ? 'Pausado' : 'Gravando';
  }
  if (draft && $('#voice-preview').getAttribute('src') !== draft.url) {
   $('#voice-preview').dataset.duration = draft.seconds || 0;
   $('#voice-preview').src = draft.url;
   $('#voice-download').href = draft.url;
   $('#voice-download').download = draft.name || 'meu-audio.' + (draft.blob.type.includes('mp4') ? 'm4a' : draft.blob.type.includes('ogg') ? 'ogg' : 'webm');
  }
 }
 function release(r) {
  if(r.released)return;
  r.released=true;
  clearInterval(timer);
  r.stream.getTracks().forEach(track => track.stop());
 }
 function remember(state, blob, seconds=0, name='') {
  const previous = drafts.get(state.key);
  if (previous) URL.revokeObjectURL(previous.url);
  drafts.set(state.key, {blob, url:URL.createObjectURL(blob), seconds, name});
  if (current === state) sync();
 }
 async function begin() {
  if (!current || current.sending || recording || pendingPermission) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {toast('Este navegador não permite gravar. Use “Anexar áudio” ou abra no Safari/Chrome atualizado.');return;}
  const state=current, token=++permissionEpoch;
  pendingPermission=true; sync();
  try {
   const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});
   if (token!==permissionEpoch || current!==state || !session) {stream.getTracks().forEach(t=>t.stop());return;}
   let recorder;
   try {
    const mime=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(m=>MediaRecorder.isTypeSupported(m));
    recorder=new MediaRecorder(stream,{...(mime?{mimeType:mime}:{}),audioBitsPerSecond:64000});
   } catch(e) {stream.getTracks().forEach(t=>t.stop());throw e;}
   const r={state,recorder,stream,chunks:[],bytes:0,elapsed:0,started:performance.now(),discard:false};
   recording=r;
   recorder.ondataavailable=e=>{if(e.data.size){r.chunks.push(e.data);r.bytes+=e.data.size;if(r.bytes>maxBytes){r.discard=true;stop();toast('O áudio ficou muito grande. Grave um trecho menor.');}}};
   recorder.onstop=()=>{
    release(r);
    if(recording===r)recording=null;
    const blob=new Blob(r.chunks,{type:recorder.mimeType||r.chunks[0]?.type||'audio/webm'});
    if(!r.discard && blob.size && blob.size<=maxBytes)remember(state,blob,Math.round(r.elapsed/1000));
    sync();
   };
   recorder.onerror=()=>{toast('A gravação foi interrompida. Confira a prévia antes de enviar.');stop();};
   stream.getAudioTracks().forEach(t=>t.onended=()=>stop());
   document.querySelectorAll('audio').forEach(a=>a.pause());
   recorder.start(1000);
   timer=setInterval(()=>{if(recording===r){if(elapsed(r)>=600000){stop();toast('Limite de 10 minutos. Seu áudio está pronto para revisar.');}else sync();}},250);
   sync();
  } catch(e) {
   if(recording){release(recording);recording=null;}
   toast(e.name==='NotAllowedError' ? 'Permita o microfone nas configurações deste site e toque no microfone novamente.' : e.name==='NotFoundError' ? 'Nenhum microfone encontrado. Conecte um ou use “Anexar áudio”.' : 'Não foi possível iniciar o microfone. Feche outros gravadores e tente novamente.');
  } finally {pendingPermission=false;sync();}
 }
 function stop(discard=false) {
  const r=recording;
  if(!r)return;
  r.discard ||= discard;
  if(r.recorder.state==='inactive')return;
  r.elapsed=elapsed(r);
  r.recorder.stop();
  release(r);
 }
 function pause() {
  const r=recording;if(!r)return;
  if(r.recorder.state==='recording'){r.elapsed=elapsed(r);r.recorder.pause();}
  else if(r.recorder.state==='paused'){r.started=performance.now();r.recorder.resume();}
  sync();
 }
 function discard() {
  if(current?.sending)return;
  if(recording?.state===current)stop(true);
  const d=current&&drafts.get(current.key);
  if(d){$('#voice-preview').pause();URL.revokeObjectURL(d.url);drafts.delete(current.key);$('#voice-preview').removeAttribute('src');}
  sync();resizeComposer();
 }
 async function send() {
  const s=current,d=s&&drafts.get(s.key);
  if(!s||!d||s.sending||d.uncertain||!session)return;
  if(localOnly){toast('Conecte-se para enviar o áudio.');return;}
  const reply=s.replyTo?{...s.replyTo}:null;
  s.sending=true;$('#voice-preview').pause();sync();
  const requestId=crypto.randomUUID(),localId='local-'+requestId;
  const m={id:localId,type:'audio',text:'',fromMe:true,ts:Math.floor(Date.now()/1000),seconds:d.seconds,localUrl:d.url,localStatus:'Enviando…'};
  s.messages.set(localId,m);renderMessages(s);$('#msgs').scrollTop=$('#msgs').scrollHeight;
  try {
   const result=await api('/api/send-audio?'+new URLSearchParams({number:reply?.jid||s.chat.number||s.chat.jid,requestId,...(reply?{replyId:reply.id}:{})}),{method:'POST',headers:{'Content-Type':d.blob.type||'application/octet-stream'},body:d.blob,timeout:180000});
   if(!result.id)throw Object.assign(new Error('O servidor não confirmou o envio. Verifique a conversa.'),{uncertain:true});
   s.messages.delete(localId);s.nodes.get(localId)?.remove();s.nodes.delete(localId);
   m.id=result.id;m.localStatus='Enviada';m.status=result.status;s.messages.set(m.id,m);
   // Keep the object URL while the optimistic message is present, so playback is immediate.
   drafts.delete(s.key);
   if(s.replyTo?.id===reply?.id)setReply(s,null);
   if(reply)m.quote={id:reply.id,text:reply.text,type:reply.type};
   toast('Áudio enviado.');loadList();
  } catch(e) {
   if(e.uncertain){d.uncertain=true;m.localStatus='Envio não confirmado';}
   else{s.messages.delete(localId);s.nodes.get(localId)?.remove();s.nodes.delete(localId);}
   toast(e.message);
  } finally {
   s.sending=false;
   if(current===s){renderMessages(s);sync();resizeComposer();}
   if(session)loadChat(s);
  }
 }
 $('#record').onclick=begin;
 $('#voice-pause').onclick=pause;
 $('#voice-stop').onclick=()=>stop();
 $('#voice-discard').onclick=discard;
 $('#voice-send').onclick=send;
 let fileState;
 $('#attach-audio').onclick=()=>{if(!current||current.sending)return;fileState=current;$('#audio-file').click();};
 $('#audio-file').onchange=e=>{
  const file=e.target.files[0],s=fileState;e.target.value='';
  if(!file||!s||!session)return;
  if(file.size>maxBytes){toast('Escolha um áudio de até 12 MB.');return;}
  if(!file.size || !/^audio\//.test(file.type)&&! /\.(mp3|m4a|ogg|opus|wav|webm|aac)$/i.test(file.name)){toast('Escolha um arquivo de áudio.');return;}
  remember(s,file,0,file.name);
 };
 document.addEventListener('visibilitychange',()=>{if(document.hidden&&recording?.recorder.state==='recording')pause();});
 window.addEventListener('pagehide',()=>stop());
 window.addEventListener('beforeunload',e=>{if(recording||drafts.size){e.preventDefault();e.returnValue='';}});
 window.voiceUX={sync,leave(){permissionEpoch++;stop();$('#voice-preview').pause();},clear(){permissionEpoch++;stop(true);for(const d of drafts.values())URL.revokeObjectURL(d.url);drafts.clear();sync();}};
 sync();
})();
