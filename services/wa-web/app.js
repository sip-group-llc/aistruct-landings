'use strict';
const $ = s => document.querySelector(s);
const icons = {
 chat:'<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z"/>',
 search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
 close:'<path d="m6 6 12 12M6 18 18 6"/>',back:'<path d="m14 5-7 7 7 7"/>',
 up:'<path d="m6 15 6-6 6 6"/>',down:'<path d="m6 9 6 6 6-6"/>',
 send:'<path d="m22 2-7 20-4-9-9-4Z M22 2 11 13"/>',
 refresh:'<path d="M20 7v5h-5M4 17v-5h5M6.1 6a7 7 0 0 1 11.5-.5L20 9M4 15l2.4 3.5A7 7 0 0 0 18 18"/>',
 menu:'<circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>',
 eye:'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
 file:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z M14 2v6h6M8 13h8M8 17h5"/>'
};
const icon = name => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.chat}</svg>`;
document.querySelectorAll('[data-icon]').forEach(e => e.innerHTML = icon(e.dataset.icon));
const esc = s => String(s ?? '').replace(/[&<>"']/g,c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fold = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const fmtTime = ts => new Date(ts*1000).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
const dayKey = ts => new Date(ts*1000).toLocaleDateString('pt-BR');
function dayLabel(ts){const d=new Date(ts*1000),n=new Date();if(d.toDateString()===n.toDateString())return 'Hoje';n.setDate(n.getDate()-1);return d.toDateString()===n.toDateString()?'Ontem':d.toLocaleDateString('pt-BR',{day:'numeric',month:'long',year:'numeric'});}
function listTime(ts){return !ts?'':dayKey(ts)===dayKey(Date.now()/1000)?fmtTime(ts):new Date(ts*1000).toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'});}
const duration = seconds => `${Math.floor(Number(seconds || 0)/60)}:${String(Number(seconds || 0)%60).padStart(2,'0')}`;
const keyFor = c => String(c.number || c.jid);
function phone(c){const n=String(c.number || '').replace(/\D/g,'');if(c.group)return 'Grupo';if(n.length===13&&n.startsWith('55'))return `+55 (${n.slice(2,4)}) ${n.slice(4,9)}-${n.slice(9)}`;return c.number||'';}
function linkify(text){let out='',last=0;for(const m of String(text||'').matchAll(/https?:\/\/[^\s<>"']+/g)){out+=esc(text.slice(last,m.index));out+=`<a href="${esc(m[0])}" target="_blank" rel="noopener noreferrer">${esc(m[0])}</a>`;last=m.index+m[0].length;}return out+esc(String(text||'').slice(last));}
function loadStored(storage,key,fallback){try{return JSON.parse(storage.getItem(key))||fallback;}catch{return fallback;}}
let drafts=loadStored(sessionStorage,'wa-drafts-v2',{}), preferences=loadStored(localStorage,'wa-preferences-v2',{});
let chats=[],current=null,filter='all',session=false,canTranscribe=false,listBusy=false,stateBusy=false,lastSync=0,syncError='',connection='unknown';
let listTimer,chatTimer,stateTimer,readTimer,searchMatches=[],matchIndex=-1,toastTimer;
let authEpoch=0;
const states=new Map(),listNodes=new Map();
function persistDrafts(){try{sessionStorage.setItem('wa-drafts-v2',JSON.stringify(drafts));}catch{toast('Não foi possível guardar o rascunho nesta sessão.');}}
function persistPreferences(){try{localStorage.setItem('wa-preferences-v2',JSON.stringify(preferences));}catch{toast('Preferências disponíveis apenas enquanto esta página estiver aberta.');}}
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,6000);}
function showLogin(message=''){window.voiceUX?.leave();session=false;authEpoch++;clearInterval(listTimer);clearInterval(chatTimer);clearInterval(stateTimer);$('#app').hidden=true;$('#login').hidden=false;$('#login-error').hidden=!message;$('#login-error').textContent=message;document.querySelectorAll('dialog[open]').forEach(d=>d.close());}
async function api(path,options={}){
 const {timeout=30000,...fetchOptions}=options;let response;
 try{response=await fetch(path,{...fetchOptions,signal:AbortSignal.timeout(timeout)});}catch{const e=new Error('Sem conexão. Tente atualizar novamente.');e.uncertain=fetchOptions.method==='POST';throw e;}
 let data;try{data=await response.json();}catch{data={};}
 if(!response.ok){const e=new Error(typeof data.detail==='string'?data.detail:'Não foi possível concluir. Tente novamente.');e.status=response.status;e.uncertain=response.status>=500;
  if(response.status===401&&path!=='/api/login'&&session)showLogin('Sua sessão expirou. Entre para continuar; seus rascunhos foram preservados.');throw e;}
 return data;
}
const post=(path,body,extra={})=>api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),...extra});
function avatar(c){const el=document.createElement('span');el.className='avatar'+(c.group?' group':'');el.setAttribute('aria-hidden','true');el.textContent=c.group?'G':String(c.name||c.number||'?').trim().split(/\s+/).slice(0,2).map(x=>Array.from(x)[0]).join('').toUpperCase();
 if(c.pic&&/^https:\/\//i.test(c.pic)){const img=new Image();img.alt='';img.loading='lazy';img.width=46;img.height=46;img.referrerPolicy='no-referrer';img.onerror=()=>img.remove();img.src=c.pic;el.append(img);}return el;}
function preview(c){if(drafts[keyFor(c)])return 'Rascunho: '+drafts[keyFor(c)];const labels={audio:'Áudio'+(c.seconds?' · '+duration(c.seconds):''),image:'Foto',video:'Vídeo',sticker:'Figurinha',document:'Documento',contact:'Contato',reaction:'Reação',other:'Mensagem'};const prefix=c.fromMe?'Você: ':c.group?(c.who?c.who+': ':'Grupo · '):'';return prefix+(c.ptype==='text'?'':(labels[c.ptype]||'Mensagem')+(c.preview?' · ':''))+(c.preview||'');}
function reconcile(parent,nodes){nodes.forEach((node,i)=>{if(parent.children[i]!==node)parent.insertBefore(node,parent.children[i]||null);});while(parent.children.length>nodes.length)parent.lastElementChild.remove();}
function renderList(){
 const q=fold($('#q').value.trim()),digits=q.replace(/\D/g,'');$('#clear-search').hidden=!q;
 const unread=chats.filter(c=>Number(c.unread)>0).length;$('#inbox-summary').textContent=`${chats.length} conversas · ${unread} ${unread===1?'não lida':'não lidas'}`;
 document.title=(unread?`(${unread}) `:'')+'Conversas · WhatsApp';
 const rows=[];
 for(const c of chats){const key=keyFor(c),pref=preferences[key]||{};if(q&&!fold(c.name).includes(q)&&!fold(c.number).includes(q)&&!(digits.length>=3&&String(c.number).replace(/\D/g,'').includes(digits)))continue;
  if(filter==='unread'&&!c.unread||filter==='groups'&&!c.group||filter==='pending'&&!pref.pending||filter==='favorites'&&!pref.favorite)continue;
  let row=listNodes.get(key);if(!row){row=document.createElement('button');row.type='button';row.className='chat';row.dataset.key=key;row.onclick=()=>{const chat=chats.find(x=>keyFor(x)===key);if(chat)openChat(chat);};listNodes.set(key,row);}
  const signature=JSON.stringify([c.name,c.pic,c.ts,c.unread,c.group,preview(c),pref]);
  if(row.dataset.signature!==signature){row.dataset.signature=signature;row.replaceChildren(avatar(c));const b=document.createElement('span');b.className='chat-body';b.innerHTML=`<span class="chat-top"><span class="chat-name">${esc(c.name||c.number)}</span><span class="chat-time">${esc(listTime(c.ts))}</span></span><span class="chat-preview"><span class="preview-text">${esc(preview(c))}</span>${pref.pending?'<span class="chat-marker" aria-label="Pendente">Pendente</span>':pref.favorite?'<span class="chat-marker" aria-label="Favorita">★</span>':''}${c.unread?`<span class="badge" aria-label="${Number(c.unread)} mensagens não lidas">${c.unread>99?'99+':Number(c.unread)}</span>`:''}</span>`;row.append(b);}
  row.classList.toggle('on',current?.key===key);row.classList.toggle('unread',Boolean(c.unread));row.setAttribute('aria-pressed',String(current?.key===key));row.title=c.name||c.number;rows.push(row);
 }
 if(!rows.length){const empty=document.createElement('div');empty.className='list-empty';const p=document.createElement('p');p.textContent=!chats.length?(syncError?'Não foi possível carregar as conversas.':listBusy?'Carregando conversas…':'Nenhuma conversa disponível.'):(q?'Nenhuma conversa encontrada.':'Nenhuma conversa neste filtro.');empty.append(p);const btn=document.createElement('button');btn.textContent=syncError&&!chats.length?'Tentar novamente':'Ver todas as conversas';btn.onclick=()=>{if(syncError&&!chats.length){loadList();return;}$('#q').value='';setFilter('all');};empty.append(btn);rows.push(empty);}
 reconcile($('#list'),rows);
}
function setFilter(value){filter=value;document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.filter===filter)));renderList();}
function renderSync(){const st=$('#state');st.classList.toggle('off',Boolean(syncError)||connection!=='open');st.textContent=syncError?(lastSync?`Atualização falhou · última às ${fmtTime(lastSync/1000)}`:'Sem conexão com suas conversas'):connection==='open'?(lastSync?`WhatsApp conectado · atualizado às ${fmtTime(lastSync/1000)}`:'WhatsApp conectado · carregando…'):`WhatsApp ${connection==='unknown'?'não verificado':'desconectado'}${lastSync?' · lista às '+fmtTime(lastSync/1000):''}`;st.title=syncError;}
async function loadList(){if(listBusy||!session)return;listBusy=true;const epoch=authEpoch;$('#refresh-list').disabled=true;if(!chats.length)renderList();try{const data=await api('/api/chats',{timeout:120000});if(epoch!==authEpoch)return;chats=[...chats.filter(c=>c.shared&&!data.some(x=>keyFor(x)===keyFor(c))),...data];lastSync=Date.now();syncError='';if(current){const c=chats.find(x=>keyFor(x)===current.key);if(c)current.chat=c;}renderList();}catch(e){syncError=e.message;if(session)renderList();}finally{listBusy=false;$('#refresh-list').disabled=false;renderSync();}}
async function checkState(){if(stateBusy||!session)return;stateBusy=true;try{const data=await api('/api/state');connection=data.instance?.state||'unknown';}catch{connection='unknown';}finally{stateBusy=false;renderSync();}}
function getState(c){const key=keyFor(c);let s=states.get(key);if(!s){s={key,chat:c,messages:new Map(),nodes:new Map(),days:new Map(),cursor:'',hasMore:false,initialized:false,loading:false,older:false,sending:false,scroll:0,atBottom:true,newCount:0,read:new Set(),visible:new Set(),readBusy:false,readFailed:false};states.set(key,s);}s.chat=c;return s;}
function saveCurrent(){window.voiceUX?.leave();if(!current)return;current.scroll=$('#msgs').scrollTop;current.atBottom=atBottom();drafts[current.key]=$('#txt').value;persistDrafts();current.visible.clear();readObserver.disconnect();}
function openChat(c,push=true){saveCurrent();current=getState(c);const s=current;$('#main').hidden=false;$('#empty').hidden=true;$('#app').classList.add('chat-open');$('#hname').textContent=c.name||c.number;$('#hname').title=c.name||c.number;$('#hnum').textContent=phone(c);$('#header-avatar').replaceChildren(avatar(c));$('#txt').value=drafts[s.key]||'';$('#mq').value='';$('#message-search').hidden=true;$('#chat-error').hidden=true;$('#read-state').textContent=s.readFailed?'Leitura ainda não sincronizada.':'Rascunhos ficam nesta sessão do navegador.';s.visible.clear();readObserver.disconnect();renderMessages(s);resizeComposer();renderList();
 if(push&&history.state?.waKey!==s.key){if(history.state?.waKey)history.replaceState({waKey:s.key},'');else history.pushState({waKey:s.key},'');}
 requestAnimationFrame(()=>{if(current!==s)return;$('#msgs').scrollTop=s.initialized?(s.atBottom?$('#msgs').scrollHeight:s.scroll):0;updateJump();});
 loadChat(s);if(matchMedia('(min-width:960px)').matches)$('#txt').focus({preventScroll:true});
}
function closeChat(){saveCurrent();current=null;$('#app').classList.remove('chat-open');$('#main').hidden=true;$('#empty').hidden=false;renderList();$('#q').focus({preventScroll:true});}
function openSharedContact(contact,number){
 if(!/^[0-9]{7,15}$/.test(number))return;
 let c=chats.find(c=>!c.group&&String(c.number).replace(/\D/g,'')===number);
 if(!c){c={jid:number+'@s.whatsapp.net',jids:[],number,name:contact.name,group:false,unread:0,ts:0,preview:'',ptype:'text',shared:true};chats.unshift(c);}
 const previous=current?.key;
 if(previous&&previous!==keyFor(c))history.pushState({waKey:keyFor(c)},'');
 openChat(c,false);
}
const atBottom=()=>$('#msgs').scrollHeight-$('#msgs').scrollTop-$('#msgs').clientHeight<85;
function captureAnchor(){const box=$('#msgs'),top=box.getBoundingClientRect().top;const first=Array.from($('#messages').children).find(n=>n.getBoundingClientRect().bottom>top);return first?{node:first,offset:first.getBoundingClientRect().top-top}:null;}
function restoreAnchor(anchor){if(anchor?.node.isConnected){const box=$('#msgs');box.scrollTop+=anchor.node.getBoundingClientRect().top-box.getBoundingClientRect().top-anchor.offset;}}
function chatError(message){$('#chat-error span').textContent=message;$('#chat-error').hidden=false;}
function mergeMessages(s,list){let added=0;for(const m of list){if(!m.id)continue;const old=s.messages.get(m.id);if(!old)added++;s.messages.set(m.id,{...old,...m,localStatus:undefined,transcript:m.transcript??old?.transcript,transcription:m.transcription??old?.transcription});}return added;}
async function loadChat(s=current,older=false){if(!s||!session||s.loading||s.older||older&&!s.hasMore)return;
 s[older?'older':'loading']=true;const epoch=authEpoch,wasInitialized=s.initialized;
 if(current===s){$('#refresh-chat').disabled=true;$('#more').disabled=true;$('#more').textContent=older?'Carregando…':'Carregar anteriores';}
 const c=s.chat,query=new URLSearchParams({jid:c.jid,extra:(c.jids||[]).filter(j=>j!==c.jid).join(',')});if(older)query.set('cursor',s.cursor);
 try{const data=await api('/api/messages?'+query,{timeout:120000});if(epoch!==authEpoch)return;
  const active=current===s,bottom=active&&atBottom(),anchor=active?captureAnchor():null;
  const latestBefore=Math.max(0,...Array.from(s.messages.values()).map(m=>Number(m.ts)||0));
  const fresh=data.messages.filter(m=>!s.messages.has(m.id)&&Number(m.ts)>=latestBefore&&!m.fromMe).length;
  mergeMessages(s,data.messages);if(!wasInitialized||older){s.cursor=data.cursor||'';s.hasMore=Boolean(data.hasMore);}if(data.number&&!String(data.number).endsWith('@lid'))s.chat.number=data.number;s.initialized=true;
  if(active){$('#chat-error').hidden=true;renderMessages(s);if(!wasInitialized||(!older&&bottom))$('#msgs').scrollTop=$('#msgs').scrollHeight;else restoreAnchor(anchor);if(!older&&!bottom&&wasInitialized)s.newCount+=fresh;updateJump();}
 }catch(e){if(current===s){if(e.status===410){s.cursor='';s.initialized=false;chatError('O histórico expirou. Atualize para recomeçar a paginação; as mensagens exibidas serão preservadas.');}else chatError(e.message);} }
 finally{s[older?'older':'loading']=false;if(current===s){$('#refresh-chat').disabled=false;$('#more').disabled=false;$('#more').textContent='Carregar anteriores';}}
}
function msgStatus(m){if(m.localStatus)return m.localStatus;const statuses={PENDING:'Enviada',SERVER_ACK:'Enviada',DELIVERY_ACK:'Entregue',READ:'Lida',PLAYED:'Reproduzida',ERROR:'Falha no envio',0:'Falha no envio',1:'Enviada',2:'Enviada',3:'Entregue',4:'Lida',5:'Reproduzida'};return statuses[m.status]||'';}
function renderMessages(s){if(current!==s)return;const list=Array.from(s.messages.values()).sort((a,b)=>a.ts-b.ts||a.id.localeCompare(b.id)),nodes=[],reactions=new Map();let previous=null,lastDay='';
 for(const m of list){if(m.type==='reaction'&&m.to){const actor=m.fromMe?'me':m.participantJid||m.participant||m.who||m.id;const bucket=reactions.get(m.to)||new Map();bucket.set(actor,m.text);reactions.set(m.to,bucket);}}
 for(const m of list){if(m.type==='reaction'||m.type==='other'&&/protocol|album|senderKey/i.test(m.kind||''))continue;
  const day=dayKey(m.ts);if(day!==lastDay){let d=s.days.get(day);if(!d){d=document.createElement('div');d.className='day';s.days.set(day,d);}d.textContent=dayLabel(m.ts);nodes.push(d);lastDay=day;previous=null;}
  let node=s.nodes.get(m.id);const signature=JSON.stringify([m.type,m.text,m.contacts,m.quote,m.fileName,m.transcript,m.transcription,m.localStatus]);
  if(!node||node.dataset.signature!==signature){node=bubble(m,s);node.dataset.signature=signature;s.nodes.set(m.id,node);}
  node.classList.toggle('grouped',Boolean(previous&&previous.fromMe===m.fromMe&&previous.who===m.who&&m.ts-previous.ts<180));
  const receipt=node.querySelector('.receipt');if(receipt){const status=m.fromMe?msgStatus(m):'';receipt.textContent=status;receipt.title=status;receipt.setAttribute('aria-label',status);receipt.dataset.symbol=/Lida|Reproduzida|Entregue/.test(status)?'✓✓':status==='Enviada'?'✓':status==='Enviando…'?'◷':status?'!':'';receipt.classList.toggle('read',/Lida|Reproduzida/.test(status));receipt.classList.toggle('pending',!/Enviada|Entregue|Lida|Reproduzida/.test(status));}
  const rx=node.querySelector('.reaction-line');rx.textContent=Array.from(reactions.get(m.id)?.values()||[]).filter(Boolean).join(' ');rx.hidden=!rx.textContent;
  nodes.push(node);previous=m;
 }
 if(!nodes.length){const empty=document.createElement('p');empty.className='timeline-empty';empty.textContent=s.initialized?'Nenhuma mensagem disponível nesta conversa.':'Carregando mensagens…';nodes.push(empty);}
 reconcile($('#messages'),nodes);$('#more-wrap').hidden=!s.hasMore;
 readObserver.disconnect();for(const node of s.nodes.values())if(node.isConnected)readObserver.observe(node);
 searchMessages(false);
}
function bubble(m,s){const d=document.createElement('article');d.className='m'+(m.fromMe?' me':'')+(m.type==='audio'?' audio':'')+(['image','sticker','video'].includes(m.type)?' photo':'')+(m.localStatus?.includes('confirmado')?' failed':'');d.dataset.id=m.id;
 const mediaJid=m.jid||s.chat.jid,src=m.localUrl||'/api/media?'+new URLSearchParams({jid:mediaJid,id:m.id,v:'4'});
 let html=(!m.fromMe&&s.chat.group?`<div class="who">${esc(m.who||m.participant||'Participante')}</div>`:'');
 if(m.quote)html+=`<div class="quote" aria-label="Mensagem citada">${esc(m.quote.text||({image:'Foto',audio:'Áudio',video:'Vídeo',document:'Documento'}[m.quote.type]||'Mensagem citada'))}</div>`;
 if(m.type==='text')html+=`<div class="body-text">${linkify(m.text)}</div>`;
 else if(m.type==='contact')html+=(m.contacts||[]).map((contact,i)=>`<section class="shared-contact"><strong>${esc(contact.name)}</strong>${contact.phones.length?contact.phones.map((number,j)=>`<div class="shared-phone"><button type="button" class="contact-open" data-contact="${i}" data-phone="${j}" aria-label="Conversar com ${esc(contact.name)} pelo número ${esc(number)}">${icon('chat')}<span>${esc(phone({number}))}<small>Conversar</small></span></button><button type="button" class="contact-copy ghost" data-contact="${i}" data-phone="${j}" aria-label="Copiar número ${esc(number)}">Copiar</button></div>`).join(''):'<p class="muted">Este contato foi compartilhado sem número.</p>'}</section>`).join('')||'<p>Contato sem dados disponíveis.</p>';
 else if(m.type==='image'||m.type==='sticker')html+=`<button type="button" class="media-open" aria-label="Abrir imagem"><img src="${esc(src)}" alt="${esc(m.text||'Imagem recebida')}" loading="lazy" width="320" height="220"></button><div class="body-text">${linkify(m.text)}</div>`;
 else if(m.type==='video')html+=`<video controls playsinline preload="metadata" src="${esc(src)}" aria-label="Vídeo da conversa"></video><div class="body-text">${linkify(m.text)}</div>`;
 else if(m.type==='audio')html+=`<div class="audio-caption"><span>Áudio${m.seconds?' · '+duration(m.seconds):''}</span><button type="button" class="speed" aria-label="Alterar velocidade do áudio">1×</button></div><audio controls preload="none" src="${esc(src)}" aria-label="Áudio da conversa"></audio>${canTranscribe&&!m.transcript&&!m.transcription?'<button type="button" class="transcribe ghost">Transcrever áudio</button>':''}`;
 else if(m.type==='document')html+=`<a class="document" href="${esc(src)}" download="${esc(m.fileName||'documento')}">${icon('file')}<span>${esc(m.fileName||'Documento')}<small>${esc(m.mime||'Arquivo')}${Number(m.size)?' · '+Math.ceil(Number(m.size)/1024)+' KB':''}</small></span></a><div class="body-text">${linkify(m.text)}</div>`;
 else html+='<div class="body-text muted">Mensagem não disponível neste visualizador.</div>';
 if(m.transcript||m.transcription)html+=`<details class="transcript" open><summary>Transcrição</summary><p>${esc(m.transcript||"Nenhuma fala identificada neste áudio.")}</p>${m.transcript?'<button type="button" class="copy-transcript ghost">Copiar transcrição</button>':''}${transcriptSegments(m)}</details>`;
 html+='<div class="reaction-line" hidden></div>';
 html+=`<div class="stamp"><time datetime="${new Date(m.ts*1000).toISOString()}" title="${esc(new Date(m.ts*1000).toLocaleString('pt-BR'))}">${fmtTime(m.ts)}</time><span class="receipt">${esc(m.fromMe?msgStatus(m):'')}</span></div>`;
 if(m.localStatus==='Envio não confirmado')html+='<div class="message-actions"><button type="button" class="verify-send ghost">Verificar conversa</button><button type="button" class="copy-message ghost">Copiar texto</button></div>';
 d.innerHTML=html;
 d.querySelectorAll('.contact-open,.contact-copy').forEach(button=>button.addEventListener('click',()=>{const contact=m.contacts[Number(button.dataset.contact)],number=contact.phones[Number(button.dataset.phone)];if(button.classList.contains('contact-copy'))copy(number);else openSharedContact(contact,number);}));
 d.querySelector('.media-open')?.addEventListener('click',()=>{const image=$('#full-image');image.src=src;image.classList.remove('zoomed');$('#zoom-image').textContent='Ampliar';$('#download-image').href=src;$('#media-dialog').showModal();});
 d.querySelector('.speed')?.addEventListener('click',e=>{const audio=d.querySelector('audio'),rates=[1,1.5,2],rate=rates[(rates.indexOf(audio.playbackRate)+1)%rates.length];audio.playbackRate=rate;e.currentTarget.textContent=String(rate).replace('.',',')+'×';});
 d.querySelector('audio')?.addEventListener('play',e=>{document.querySelectorAll('audio').forEach(a=>{if(a!==e.target)a.pause();});});
 d.querySelector('.transcribe')?.addEventListener('click',e=>transcribe(m,s,e.currentTarget));
 d.querySelectorAll('.transcript-seek').forEach(button=>button.addEventListener('click',()=>{
  const audio=d.querySelector('audio');if(!audio)return;
  const seek=()=>{audio.currentTime=Number(button.dataset.start)||0;audio.play().catch(()=>toast('Toque em reproduzir no áudio para continuar.'));};
  if(audio.readyState>=1)seek();else{audio.addEventListener('loadedmetadata',seek,{once:true});audio.load();}
 }));
 d.querySelector('.copy-transcript')?.addEventListener('click',()=>copy(m.transcript));d.querySelector('.copy-message')?.addEventListener('click',()=>copy(m.text));d.querySelector('.verify-send')?.addEventListener('click',()=>loadChat(s));
 for(const media of d.querySelectorAll('img,video,audio')){media.addEventListener('error',()=>{if(d.querySelector('.media-error'))return;const error=document.createElement('div');error.className='media-error';error.textContent='Mídia indisponível. ';const retry=document.createElement('button');retry.className='ghost';retry.textContent='Tentar novamente';retry.onclick=()=>{error.remove();media.src=src+'&retry='+Date.now();};error.append(retry);media.after(error);});}
 return d;
}
function transcriptSegments(m){
 const segments=m.transcription?.segments||[];
 if(!segments.length)return '';
 return '<details class="transcript-segments"><summary>Ouvir por trecho</summary>'+segments.map(segment=>`<button type="button" class="transcript-seek" data-start="${Math.max(0,Number(segment.start)||0)}"><time>${duration(Math.floor(Number(segment.start)||0))}</time><span>${esc(segment.text)}</span></button>`).join('')+'</details>';
}
async function transcribe(m,s,button){
 if(button.disabled)return;
 button.disabled=true;button.setAttribute('aria-busy','true');
 const started=Date.now();button.textContent='Transcrevendo…';
 const timer=setInterval(()=>{button.textContent='Transcrevendo… '+duration(Math.floor((Date.now()-started)/1000));},1000);
 const previousError=button.parentElement.querySelector('.transcription-error');previousError?.remove();
 try{
  const result=await post('/api/transcribe',{jid:m.jid||s.chat.jid,id:m.id},{timeout:330000});
  m.transcript=result.texto||'';m.transcription={segments:result.segments||[],language:result.language,provider:result.provider,model:result.model};
  s.messages.set(m.id,{...s.messages.get(m.id),transcript:m.transcript,transcription:m.transcription});
  if(current===s){const anchor=captureAnchor();renderMessages(s);restoreAnchor(anchor);}
 }catch(e){
  button.disabled=false;button.textContent='Tentar transcrição novamente';
  const error=document.createElement('p');error.className='transcription-error';error.setAttribute('role','alert');error.textContent=e.message;button.after(error);
 }finally{clearInterval(timer);button.removeAttribute('aria-busy');}
}

async function copy(text){try{await navigator.clipboard.writeText(text);toast('Copiado.');}catch{toast('Não foi possível copiar. Selecione o texto para copiar manualmente.');}}
function resizeComposer(){const t=$('#txt');t.style.height='auto';t.style.height=Math.min(160,Math.max(46,t.scrollHeight))+'px';$('#send').disabled=!current||current.sending||!t.value.trim();$('#send').setAttribute('aria-label',current?.sending?'Enviando mensagem':'Enviar mensagem');$('#send .send-label').textContent=current?.sending?'Enviando…':'Enviar';window.voiceUX?.sync();}
async function sendMessage(){const s=current,text=$('#txt').value.trim();if(!s||s.sending||!text||!session)return;
 s.sending=true;const requestId=crypto.randomUUID(),localId='local-'+requestId;
 const m={id:localId,fromMe:true,ts:Math.floor(Date.now()/1000),type:'text',text,localStatus:'Enviando…'};s.messages.set(localId,m);drafts[s.key]='';persistDrafts();$('#txt').value='';resizeComposer();renderMessages(s);$('#msgs').scrollTop=$('#msgs').scrollHeight;renderList();
 try{const result=await post('/api/send',{number:s.chat.number||s.chat.jid,text,requestId},{timeout:120000});if(!result.id){m.localStatus='Envio não confirmado';}else{s.messages.delete(localId);s.nodes.get(localId)?.remove();s.nodes.delete(localId);m.id=result.id;m.localStatus='Enviada';m.status=result.status;s.messages.set(result.id,m);} }
 catch(e){m.localStatus='Envio não confirmado';if(current===s)chatError(e.uncertain?'O envio não foi confirmado. Verifique as mensagens recentes antes de enviar de novo.':e.message);}
 finally{s.sending=false;if(current===s){renderMessages(s);resizeComposer();$('#txt').focus({preventScroll:true});}renderList();if(session)loadChat(s);}
}
function updateJump(){if(!current)return;const bottom=atBottom();current.atBottom=bottom;if(bottom)current.newCount=0;$('#jump').hidden=bottom;$('#jump').textContent=current.newCount?`${current.newCount} nova${current.newCount===1?' mensagem':'s mensagens'} ↓`:'Ir para mensagens recentes ↓';}
const readObserver=new IntersectionObserver(entries=>{if(!current||document.hidden)return;for(const e of entries){if(e.isIntersecting)current.visible.add(e.target.dataset.id);else current.visible.delete(e.target.dataset.id);}clearTimeout(readTimer);readTimer=setTimeout(flushRead,650);},{root:$('#msgs'),threshold:.2});
async function flushRead(){const s=current;if(!s||!session||document.hidden||s.readBusy||s.readFailed)return;const ids=Array.from(s.visible).filter(id=>{const m=s.messages.get(id);return m&&!m.fromMe&&!s.read.has(id)&&!['READ','PLAYED',4,5].includes(m.status);}).slice(0,100);if(!ids.length)return;s.readBusy=true;try{const result=await post('/api/read',{jid:s.chat.jid,keys:ids.map(id=>{const m=s.messages.get(id);return {id,jid:m.jid||s.chat.jid,participant:m.participantJid||''};})});if(result.ok===false)throw new Error('Leitura ainda não sincronizada. Tente atualizar a conversa.');ids.forEach(id=>s.read.add(id));if(current===s)$('#read-state').textContent='Leitura sincronizada';loadList();}catch(e){s.readFailed=true;if(current===s){$('#read-state').textContent='Leitura ainda não sincronizada';chatError(e.message);}}finally{s.readBusy=false;}}
function searchMessages(jump=true){if(!current)return;const q=fold($('#mq').value.trim()),s=current;for(const n of s.nodes.values())n.classList.remove('search-hit');searchMatches=q?Array.from(s.messages.values()).filter(m=>m.type!=='reaction'&&fold((m.text||'')+' '+(m.transcript||'')).includes(q)).sort((a,b)=>a.ts-b.ts).map(m=>s.nodes.get(m.id)).filter(n=>n?.isConnected):[];if(jump)matchIndex=searchMatches.length?0:-1;else matchIndex=Math.min(Math.max(0,matchIndex),searchMatches.length-1);$('#match-count').textContent=q?(searchMatches.length?`${matchIndex+1} de ${searchMatches.length}`:'Nenhum resultado'):'';$('#prev-match').disabled=$('#next-match').disabled=!searchMatches.length;if(matchIndex>=0){searchMatches[matchIndex].classList.add('search-hit');if(jump)searchMatches[matchIndex].scrollIntoView({block:'center'});}}
function nextMatch(delta){if(!searchMatches.length)return;searchMatches[matchIndex]?.classList.remove('search-hit');matchIndex=(matchIndex+delta+searchMatches.length)%searchMatches.length;searchMatches[matchIndex].classList.add('search-hit');searchMatches[matchIndex].scrollIntoView({block:'center'});$('#match-count').textContent=`${matchIndex+1} de ${searchMatches.length}`;}
function showDetails(){if(!current)return;const c=current.chat,p=preferences[current.key]||{};$('#detail-name').textContent=c.name||c.number;$('#detail-number').textContent=phone(c);$('#copy-number').hidden=c.group;$('#favorite').textContent=p.favorite?'Remover das favoritas':'Adicionar às favoritas';$('#pending').textContent=p.pending?'Concluir pendência':'Marcar como pendente';$('#details').showModal();}
async function start(info){if(session)return;session=true;authEpoch++;canTranscribe=Boolean(info.transcriber);$('#login').hidden=true;$('#app').hidden=false;$('#pw').value='';await loadList();checkState();listTimer=setInterval(()=>{if(!document.hidden)loadList();},15000);chatTimer=setInterval(()=>{if(!document.hidden)loadChat();},8000);stateTimer=setInterval(()=>{if(!document.hidden)checkState();},60000);const saved=history.state?.waKey;if(saved){const c=chats.find(c=>keyFor(c)===saved);if(c)openChat(c,false);}}
$('#login-form').addEventListener('submit',async e=>{e.preventDefault();const b=$('#login-submit');if(b.disabled)return;b.disabled=true;b.textContent='Entrando…';$('#login-error').hidden=true;try{await post('/api/login',{senha:$('#pw').value});await start(await api('/api/session'));}catch(err){$('#login-error').textContent=err.status===401?'Senha incorreta. Confira e tente novamente.':err.message;$('#login-error').hidden=false;}finally{b.disabled=false;b.textContent='Entrar';}});
$('#show-password').onclick=()=>{const pw=$('#pw');pw.type=pw.type==='password'?'text':'password';$('#show-password').setAttribute('aria-label',pw.type==='password'?'Mostrar senha':'Ocultar senha');};
$('#q').addEventListener('input',renderList);$('#clear-search').onclick=()=>{$('#q').value='';renderList();$('#q').focus();};document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>setFilter(b.dataset.filter));
$('#refresh-list').onclick=()=>{loadList();checkState();};$('#refresh-chat').onclick=$('#retry-chat').onclick=()=>{if(current){current.readFailed=false;loadChat();flushRead();}};
$('#back').onclick=()=>{if(history.state?.waKey)history.back();else closeChat();};window.addEventListener('popstate',e=>{const c=e.state?.waKey&&chats.find(c=>keyFor(c)===e.state.waKey);if(c)openChat(c,false);else closeChat();});
$('#more').onclick=()=>loadChat(current,true);$('#jump').onclick=()=>{$('#msgs').scrollTop=$('#msgs').scrollHeight;updateJump();};$('#msgs').addEventListener('scroll',()=>{updateJump();if(current){current.scroll=$('#msgs').scrollTop;current.anchor=captureAnchor();}},{passive:true});
let draftFrame;$('#txt').addEventListener('input',()=>{if(current){drafts[current.key]=$('#txt').value;persistDrafts();resizeComposer();cancelAnimationFrame(draftFrame);draftFrame=requestAnimationFrame(renderList);}});
$('#txt').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&matchMedia('(min-width:960px)').matches){e.preventDefault();sendMessage();}});$('#compose').addEventListener('submit',e=>{e.preventDefault();sendMessage();});
$('#toggle-message-search').onclick=()=>{$('#message-search').hidden=!$('#message-search').hidden;if(!$('#message-search').hidden)$('#mq').focus();};$('#close-message-search').onclick=()=>{$('#message-search').hidden=true;$('#mq').value='';searchMessages(false);$('#toggle-message-search').focus();};$('#mq').addEventListener('input',()=>searchMessages());$('#next-match').onclick=()=>nextMatch(1);$('#prev-match').onclick=()=>nextMatch(-1);
$('#contact-details').onclick=showDetails;$('#copy-number').onclick=()=>current&&copy(current.chat.number||'');for(const [id,key]of[['favorite','favorite'],['pending','pending']])$('#'+id).onclick=()=>{if(!current)return;const p=preferences[current.key]||{};p[key]=!p[key];preferences[current.key]=p;persistPreferences();$('#details').close();renderList();toast(key==='pending'?(p.pending?'Conversa marcada como pendente.':'Pendência concluída.'):(p.favorite?'Adicionada às favoritas.':'Removida das favoritas.'));};
$('#account').onclick=()=>$('#account-dialog').showModal();document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$('#'+b.dataset.close).close());$('#zoom-image').onclick=()=>{const zoomed=$('#full-image').classList.toggle('zoomed');$('#zoom-image').textContent=zoomed?'Ajustar à tela':'Ampliar';};
$('#logout').onclick=async()=>{try{await post('/api/logout',{});window.voiceUX?.clear();drafts={};persistDrafts();states.clear();listNodes.clear();chats=[];current=null;$('#list').replaceChildren();$('#messages').replaceChildren();$('#txt').value='';$('#app').classList.remove('chat-open');$('#main').hidden=true;$('#empty').hidden=false;history.replaceState({},'');showLogin();}catch(e){toast(e.message);}};
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&session){loadList();loadChat();checkState();flushRead();}});window.addEventListener('online',()=>{if(session){loadList();loadChat();checkState();}});window.addEventListener('offline',()=>{syncError='Sem conexão com a internet';renderSync();});
window.addEventListener('pagehide',saveCurrent);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.querySelector('dialog[open]')&&current){if(!$('#message-search').hidden)$('#close-message-search').click();else $('#back').click();}});
if(window.visualViewport){const fit=()=>{$('#app').style.height=visualViewport.height+'px';};visualViewport.addEventListener('resize',fit);fit();}
// Preserve reading position when media, transcription or the keyboard resize content.
const timelineResize=new ResizeObserver(()=>{if(!current)return;if(current.atBottom)$('#msgs').scrollTop=$('#msgs').scrollHeight;else restoreAnchor(current.anchor);});
timelineResize.observe($('#messages'));timelineResize.observe($('#msgs'));
api('/api/session').then(start).catch(e=>showLogin(e.status===401?'':e.message));
