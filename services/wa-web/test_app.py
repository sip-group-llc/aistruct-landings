"""Regression tests with synthetic records; never contact Evolution or send messages."""
import asyncio
import base64
import importlib.util
import os
import io
import shutil
import wave
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx

for key, value in {"EVOLUTION_URL": "https://evolution.invalid", "EVOLUTION_APIKEY": "test",
                   "WA_PASSWORD": "test-password", "WA_SECRET": "test-secret", "TRANSCRIBER_URL": "", "GROQ_API_KEY": ""}.items():
    os.environ[key] = value
spec = importlib.util.spec_from_file_location("wa_under_test", Path(__file__).with_name("app.py"))
wa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wa)


def record(jid, n, ts, from_me=False):
    return {"key": {"id": f"{jid}-{n}", "remoteJid": jid, "fromMe": from_me},
            "messageTimestamp": ts, "message": {"conversation": f"synthetic {n}"}}


class AppTests(unittest.IsolatedAsyncioTestCase):
    def test_mentions_preserve_original_and_replace_only_declared_complete_ids(self):
        rec=record('12345@g.us',1,1)
        rec['message']={'extendedTextMessage':{'text':'@123 falar com @456 e @1234', 'contextInfo':{'mentionedJid':['123@lid','456@lid']}}}
        msg=wa._norm(rec)
        wa.resolve_mentions([msg],{'123@lid':'Ana','456@lid':'Bruno'})
        self.assertEqual(msg['displayText'],'@Ana falar com @Bruno e @1234')
        self.assertEqual(msg['text'],'@123 falar com @456 e @1234')
        rec['message']={'conversation':'@123 falar com @456'}
        rec['contextInfo']={'mentionedJid':['123@lid','456@lid']}
        msg=wa._norm(rec);wa.resolve_mentions([msg],{'123@lid':'Ana','456@lid':'Bruno'})
        self.assertEqual(msg['displayText'],'@Ana falar com @Bruno')

    async def test_mention_names_join_lid_and_phone_without_inventing_names(self):
        from unittest.mock import AsyncMock
        response=httpx.Response(200,json={'participants':[{'id':'123@lid','phoneNumber':'5511999991111@s.whatsapp.net'},{'id':'456@lid','phoneNumber':'5511999992222@s.whatsapp.net'}]},request=httpx.Request('GET','https://evolution.invalid'))
        with patch.object(wa,'_contact_names_cache',(-10000,{})),patch.object(wa,'_group_names_cache',{}),patch.object(wa,'_post',AsyncMock(return_value=[{'remoteJid':'5511999991111@s.whatsapp.net','pushName':'Ana'}])),patch.object(wa.evo,'get',AsyncMock(return_value=response)):
            names=await wa.mention_names('12345@g.us')
            self.assertEqual(names['123@lid'],'Ana');self.assertEqual(names['456@lid'],'5511999992222')

    async def test_group_members_are_authenticated_and_filtered(self):
        from unittest.mock import AsyncMock
        response=httpx.Response(200,json={'subject':'Grupo','desc':'Descrição','participants':[{'id':'123@lid','phoneNumber':'5511999998888@s.whatsapp.net','name':'Ana','admin':'admin','secret':'hidden'},{'id':'456@lid','admin':None}]},request=httpx.Request('GET','https://evolution.invalid'))
        with patch.object(wa.evo,'get',AsyncMock(return_value=response)) as get:
            r=await self.client.get('/api/group',params={'jid':'12345@g.us'});self.assertEqual(r.status_code,200)
            self.assertEqual(r.json()['size'],2);self.assertEqual(r.json()['participants'][0],{'id':'123@lid','number':'5511999998888','name':'Ana','admin':True})
            self.assertEqual(r.json()['participants'][1]['number'],'')
            self.assertEqual(get.call_args.kwargs['params'],{'groupJid':'12345@g.us'})
            self.assertEqual((await self.client.get('/api/group?jid=private')).status_code,400)
            self.client.cookies.clear();self.assertEqual((await self.client.get('/api/group?jid=12345@g.us')).status_code,401)

    async def test_read_lid_uses_verified_phone_alias_and_requires_confirmation(self):
        from unittest.mock import AsyncMock
        with tempfile.TemporaryDirectory() as root:
            workspace=wa.Workspace(root);workspace.learn_chat_aliases([('123@lid','5511999998888')])
            store=wa.PushStore(root,'badge')
            with patch.object(wa,'_workspace',workspace),patch.object(wa,'_push',store),patch.object(wa,'_post',AsyncMock(return_value={'read':'success'})) as post:
                r=await self.client.post('/api/read',json={'keys':[{'jid':'123@lid','id':'latest'}]})
                self.assertEqual(r.status_code,200)
                self.assertEqual(post.call_args.args[1]['readMessages'][0]['remoteJid'],'5511999998888@s.whatsapp.net')
                post.return_value={'read':'failed'}
                r=await self.client.post('/api/read',json={'keys':[{'jid':'123@lid','id':'failed'}]})
                self.assertEqual(r.status_code,502)
                self.assertNotIn('123@lid|failed',store.receipts())

    async def test_own_profile_read_uses_own_number_and_filters_metadata(self):
        from unittest.mock import AsyncMock
        own={'wuid':'5511999998888:1@s.whatsapp.net'}
        detail={'name':'Nome','status':{'status':'Recado'},'picture':'https://example.com/photo.jpg'}
        response=httpx.Response(200,json=[{'name':wa.INST,'profileName':'Meu nome','token':'must-not-leak'}],request=httpx.Request('GET','https://evolution.invalid'))
        with patch.object(wa,'_post',AsyncMock(side_effect=[own,detail])) as post,patch.object(wa.evo,'get',AsyncMock(return_value=response)):
            result=await self.client.get('/api/me');self.assertEqual(result.status_code,200)
            self.assertEqual(result.json(),{'name':'Meu nome','number':'5511999998888','about':'Recado','picture':'https://example.com/photo.jpg'})
            self.assertEqual(post.call_args.args[1],{'number':'5511999998888'})

    async def test_own_profile_updates_only_selected_field_and_rejects_invalid_inputs(self):
        from unittest.mock import AsyncMock
        with patch.object(wa,'_post',AsyncMock(return_value={'update':'success'})) as post:
            for field,key,path in [('name','name','updateProfileName'),('about','status','updateProfileStatus')]:
                result=await self.client.post('/api/me',json={'field':field,'value':' Novo valor '});self.assertEqual(result.status_code,200)
                self.assertEqual(post.call_args.args,(f'/chat/{path}/{wa.INST}',{key:'Novo valor'}))
            count=post.call_count
            for body in [{'field':'number','value':'5511'},{'field':'name','value':'x'*26},{'field':'about','value':''},{'field':'name','value':'Nome','number':'other'}]:
                self.assertEqual((await self.client.post('/api/me',json=body)).status_code,400)
            self.assertEqual(post.call_count,count)
            self.assertEqual((await self.client.post('/api/me/picture',content=b'not an image')).status_code,415)
            self.assertEqual((await self.client.post('/api/me/picture',content=b'\x89PNG\r\n\x1a\nsynthetic')).status_code,200)
            self.assertEqual(post.call_args.args[0],f'/chat/updateProfilePicture/{wa.INST}')
            self.client.cookies.clear();self.assertEqual((await self.client.get('/api/me')).status_code,401)
            self.assertEqual((await self.client.post('/api/me',json={'field':'name','value':'Nome'})).status_code,401)

    async def test_push_routes_auth_storage_and_read_receipts(self):
        from test_push import subscription
        with tempfile.TemporaryDirectory() as root, patch.object(wa, '_push', wa.PushStore(root, 'test')), patch.object(wa._disk, 'root', Path(root)):
            self.client.cookies.clear()
            self.assertEqual((await self.client.get('/api/push')).status_code,401)
            self.assertEqual((await self.client.post('/api/push/subscribe',json=subscription())).status_code,401)
            self.client.cookies.set(wa.COOKIE,wa._token)
            config=await self.client.get('/api/push');self.assertTrue(config.json()['available']);self.assertEqual(len(config.json()['publicKey']),87)
            sub=subscription();self.assertEqual((await self.client.post('/api/push/subscribe',json=sub)).status_code,200)
            bad={**sub,'endpoint':'https://127.0.0.1/private'};self.assertEqual((await self.client.post('/api/push/subscribe',json=bad)).status_code,400)
            with patch.object(wa,'_post',return_value={'read':'success'}):
                self.assertEqual((await self.client.post('/api/read',json={'keys':[{'jid':'a','id':'1'}]})).status_code,200)
            self.assertTrue((await self.client.get('/api/read-state')).json()['a|1'])
            self.assertEqual((await self.client.post('/api/push/unsubscribe',json={'endpoint':sub['endpoint']})).status_code,200)
            self.assertEqual(wa._push.subscriptions(),[])

    async def test_push_cycle_reads_recent_pages_without_sending_whatsapp(self):
        from test_push import subscription
        from unittest.mock import AsyncMock, MagicMock
        with tempfile.TemporaryDirectory() as root:
            store=wa.PushStore(root,'test');store.subscribe(subscription())
            rec=record('a',1,int(__import__('time').time()))
            read=AsyncMock(return_value={'messages':{'records':[rec],'pages':1}})
            with patch.object(wa,'_push',store),patch.object(wa,'_workspace',wa.Workspace(root)),patch.object(wa,'_post',read),patch.object(store,'deliver',return_value=0) as deliver:
                await wa.push_cycle()
                self.assertEqual(read.call_count,1);self.assertIn('/chat/findMessages/',read.call_args.args[0]);deliver.assert_called_once()

    def test_commercial_template_content_and_missing_payload(self):
        rec = record('synthetic@lid', 1, 1)
        rec['message'] = {'templateMessage': {'hydratedTemplate': {
            'hydratedTitleText': 'Aviso', 'hydratedContentText': 'Seu pedido chegou.',
            'hydratedFooterText': 'Equipe', 'hydratedButtons': [
                {'quickReplyButton': {'displayText': 'Confirmar', 'id': 'private-token'}}]}}}
        result = wa._norm(rec)
        self.assertEqual(result['type'], 'text')
        self.assertEqual(result['text'], 'Aviso\n\nSeu pedido chegou.\n\nEquipe\n\nOpções da mensagem: Confirmar')
        self.assertEqual(result['template']['actions'], [{'label': 'Confirmar', 'url': ''}])
        rec['message']['templateMessage']['hydratedTemplate']['hydratedButtons'] = [
            {'urlButton': {'displayText': 'Abrir', 'url': 'https://example.com/details'}},
            {'urlButton': {'displayText': 'Inválido', 'url': 'javascript:alert(1)'}}]
        actions = wa._norm(rec)['template']['actions']
        self.assertEqual(actions[0]['url'], 'https://example.com/details')
        self.assertEqual(actions[1]['url'], '')
        rec['message'] = {'placeholderMessage': {'type': 0}}
        result = wa._norm(rec)
        self.assertFalse(result['cacheable'])
        self.assertIn('não foi sincronizado', result['text'])

    async def test_flags_import_preserves_remote_state_and_updates_conflict(self):
        with tempfile.TemporaryDirectory() as root, patch.object(wa,'_workspace',wa.Workspace(root)):
            imported=await self.client.post('/api/work-import-flags',json={'5511':{'favorite':True,'pending':True}})
            self.assertEqual(imported.status_code,200)
            result=await self.client.post('/api/work-flags',json={'key':'5511','field':'pending','value':False,'revision':1})
            self.assertEqual(result.status_code,200);self.assertTrue(result.json()['favorite']);self.assertFalse(result.json()['pending'])
            stale=await self.client.post('/api/work-flags',json={'key':'5511','field':'pending','value':True,'revision':1})
            self.assertEqual(stale.status_code,409)
            await self.client.post('/api/work-import-flags',json={'5511':{'favorite':False,'pending':True}})
            wa._workspace=wa.Workspace(root)
            current=(await self.client.get('/api/work-summary')).json()['5511']['flags']
            self.assertEqual(current,{'favorite':True,'pending':False,'revision':2})
            self.client.cookies.clear()
            self.assertEqual((await self.client.post('/api/work-import-flags',json={})).status_code,401)

    async def test_private_notes_persist_and_conflicting_edits_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as root, patch.object(wa,'_workspace',wa.Workspace(root)):
            payload={'key':'5511','notes':'Nota privada','labels':['Cliente','cliente','Retornar'],'revision':0}
            first=await self.client.post('/api/work',json=payload)
            self.assertEqual(first.status_code,200,first.text)
            self.assertEqual(first.json()['labels'],['Cliente','Retornar'])
            second=await self.client.post('/api/work',json={**payload,'notes':'stale overwrite'})
            self.assertEqual(second.status_code,409)
            with patch.object(wa,'_workspace',wa.Workspace(root)):
                saved=(await self.client.get('/api/work?key=5511')).json()
                self.assertEqual(saved['notes'],'Nota privada');self.assertEqual(saved['revision'],1)
            summary=(await self.client.get('/api/work-summary')).json()
            self.assertTrue(summary['5511']['hasNotes']);self.assertNotIn('notes',summary['5511'])
            invalid=await self.client.post('/api/work',json={**payload,'labels':['x'*33]})
            self.assertEqual(invalid.status_code,400)
            self.client.cookies.clear()
            self.assertEqual((await self.client.get('/api/work?key=5511')).status_code,401)
            self.assertEqual((await self.client.post('/api/work',json=payload)).status_code,401)

    async def test_audio_and_image_replies_share_original_and_deduplicate_concurrently(self):
        jid='media-reply@lid';original=record(jid,1,10);calls=[]
        async def fake(path,body):
            if '/findMessages/' in path:
                await asyncio.sleep(.01)
                return {'messages':{'records':[original]}}
            calls.append((path,body));return {'key':{'id':'media-replied'},'status':'PENDING'}
        async def encode(raw):return b'OggSsynthetic'
        with patch.object(wa,'_post',fake),patch.object(wa,'_voice_ogg',encode):
            for kind,raw,mime in [('audio',b'synthetic','audio/wav'),('image',b'\x89PNG\r\n\x1a\nsynthetic','image/png')]:
                url=f'/api/send-{kind}?number={jid}&requestId={kind}-quoted&replyId={original["key"]["id"]}'
                a,b=await asyncio.gather(self.client.post(url,content=raw,headers={'Content-Type':mime}),self.client.post(url,content=raw,headers={'Content-Type':mime}))
                self.assertEqual(a.status_code,200,a.text);self.assertEqual(b.status_code,200,b.text)
                self.assertEqual(calls[-1][1]['quoted'],{'key':original['key'],'message':original['message']})
            self.assertEqual(len(calls),2)

    async def test_quoted_reply_uses_original_and_rejects_other_conversation(self):
        jid='reply@s.whatsapp.net'
        original=record(jid, 1, 10)
        calls=[]
        async def fake(path, body):
            calls.append((path,body))
            if '/findMessages/' in path:return {'messages':{'records':[original]}}
            return {'key':{'id':'reply-sent'},'status':'PENDING'}
        payload={'number':jid,'text':'Resposta','requestId':'reply-test','replyTo':{'jid':jid,'id':original['key']['id'],'text':'forged'}}
        with patch.object(wa,'_post',fake):
            response=await self.client.post('/api/send',json=payload)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(calls[-1][1]['quoted'],{'key':original['key'],'message':original['message']})
            await self.client.post('/api/send',json=payload)
            self.assertEqual(sum('/sendText/' in p for p,b in calls),1)
            response=await self.client.post('/api/send',json={**payload,'number':'different@s.whatsapp.net'})
            self.assertEqual(response.status_code,400)
            response=await self.client.post('/api/send',json={**payload,'requestId':'missing','replyTo':{'id':'missing','jid':jid}})
            self.assertEqual(response.status_code,409)
            self.assertEqual(sum('/sendText/' in p for p,b in calls),1)

    async def test_disk_media_recovers_without_network_and_respects_policy(self):
        with tempfile.TemporaryDirectory() as root:
            store = wa.PersistentCache(root, 'test')
            jid, mid = 'disk@s.whatsapp.net', 'disk-message'
            wa._media_policy[(jid, mid)] = True
            wa._media.clear()
            calls = []
            async def fetch(*args):
                calls.append(args)
                return {'mimetype': 'audio/ogg', 'base64': 'YWJj'}
            with patch.object(wa, '_disk', store), patch.object(wa, '_post', fetch):
                self.assertEqual(await wa._fetch_media(jid, mid), ('audio/ogg', b'abc'))
                wa._media.clear()
                self.assertEqual(await wa._fetch_media(jid, mid), ('audio/ogg', b'abc'))
                self.assertEqual(len(calls), 1)
                wa._media_policy[(jid, mid)] = False
                await wa._fetch_media(jid, mid)
                self.assertEqual(len(calls), 2)
                self.assertEqual(len(wa._media), 0)

    async def test_disk_transcript_recovers_without_provider_call(self):
        with tempfile.TemporaryDirectory() as root:
            jid, mid = 'disk@s.whatsapp.net', 'saved-transcript'
            wa._media_policy[(jid, mid)] = True
            with patch.object(wa, 'GROQ_KEY', 'synthetic'), patch.object(wa, '_disk', wa.PersistentCache(root, 'test')):
                wa._disk.put('transcript', wa._transcript_identity(jid, mid), {'texto': 'persistido', 'segments': []})
                response = await self.client.post('/api/transcribe', json={'jid': jid, 'id': mid})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()['cached'])
                self.assertEqual(response.json()['texto'], 'persistido')

    async def test_cache_scope_is_private_and_content_restrictions_survive_normalization(self):
        info=(await self.client.get('/api/session')).json()
        self.assertEqual(len(info['cacheScope']),64)
        self.assertNotEqual(info['cacheScope'],wa._token)
        normal=record('a@s.whatsapp.net',1,10)
        self.assertTrue(wa._norm(normal)['cacheable'])
        for wrapper in ('ephemeralMessage','viewOnceMessage','viewOnceMessageV2'):
            restricted={**normal,'message':{wrapper:{'message':normal['message']}}}
            self.assertFalse(wa._norm(restricted)['cacheable'])
        restricted={**normal,'message':{'extendedTextMessage':{'text':'temporary','contextInfo':{'expiration':86400}}}}
        self.assertFalse(wa._norm(restricted)['cacheable'])

    async def test_unread_frontiers_preserve_each_alias(self):
        a=record('123@lid',1,10)
        a['key']['remoteJidAlt']='5511999998888@s.whatsapp.net'
        b=record('5511999998888@s.whatsapp.net',2,20,True)
        async def upstream(path,body=None):
            return [{'remoteJid':'123@lid','unreadCount':3,'lastMessage':a},
                    {'remoteJid':'5511999998888@s.whatsapp.net','unreadCount':2,'lastMessage':b}]
        with patch.object(wa,'_post',upstream):
            data=(await self.client.get('/api/chats')).json()
        self.assertEqual(len(data),1)
        self.assertEqual(data[0]['unread'],5)
        self.assertEqual({s['jid']:s['count'] for s in data[0]['unreadSources']},{'123@lid':3,'5511999998888@s.whatsapp.net':2})
        self.assertEqual({s['lastId'] for s in data[0]['unreadSources']},{a['key']['id'],b['key']['id']})

    async def test_shared_frontier_links_aliases_without_alt_and_does_not_double_unread(self):
        lid = record('123@lid', 1, 20, True)
        phone = record('5511999998888@s.whatsapp.net', 1, 20, True)
        lid['key']['id'] = phone['key']['id'] = 'same-message'
        current = [
            {'remoteJid': '123@lid', 'unreadCount': 2, 'lastMessage': lid},
            {'remoteJid': '5511999998888@s.whatsapp.net', 'unreadCount': 2, 'lastMessage': phone},
        ]
        async def upstream(path, body=None):
            return current
        with tempfile.TemporaryDirectory() as root, patch.object(wa, '_workspace', wa.Workspace(root)), patch.object(wa, '_post', upstream):
            first = (await self.client.get('/api/chats')).json()
            self.assertEqual(len(first), 1)
            self.assertEqual(first[0]['number'], '5511999998888')
            self.assertEqual(first[0]['unread'], 2)
            lid2, phone2 = record('123@lid', 2, 30), record('5511999998888@s.whatsapp.net', 3, 40, True)
            current[:] = [
                {'remoteJid': '123@lid', 'unreadCount': 1, 'lastMessage': lid2},
                {'remoteJid': '5511999998888@s.whatsapp.net', 'unreadCount': 0, 'lastMessage': phone2},
            ]
            wa._workspace = wa.Workspace(root)
            second = (await self.client.get('/api/chats')).json()
            self.assertEqual(len(second), 1)
            self.assertEqual(second[0]['unread'], 1)

    async def test_profile_fields_and_business_partial(self):
        async def upstream(path, body):
            self.assertEqual(body['number'],'5511999998888')
            if 'fetchBusinessProfile' in path:
                raise wa.HTTPException(502,'private upstream error')
            return {'name':'Hugo','picture':'https://example.com/photo.jpg','status':{'status':'Olá','setAt':'2026-09-13'},'isBusiness':True,'secret':'must not leak'}
        with patch.object(wa,'_post',upstream):
            r=await self.client.get('/api/profile?number=5511999998888')
            self.assertEqual(r.status_code,200)
            self.assertEqual(r.json()['about'],'Olá')
            self.assertTrue(r.json()['partial'])
            self.assertNotIn('secret',r.text)

    async def test_profile_privacy_auth_and_validation(self):
        async def upstream(path,body):
            return {'name':'','picture':'javascript:bad','status':None,'isBusiness':False}
        with patch.object(wa,'_post',upstream):
            r=await self.client.get('/api/profile?number=5511999998888')
            self.assertEqual(r.json()['picture'],'')
            self.assertEqual(r.json()['about'],'')
            self.assertEqual(r.headers['cache-control'],'no-store')
        self.assertEqual((await self.client.get('/api/profile?number=invalid')).status_code,400)
        self.client.cookies.clear()
        self.assertEqual((await self.client.get('/api/profile?number=5511999998888')).status_code,401)

    async def test_image_send_payload_and_deduplication(self):
        import base64
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aT1sAAAAASUVORK5CYII=')
        calls=[]
        async def upstream(path, body):
            calls.append((path, body))
            await asyncio.sleep(.01)
            return {'key': {'id': 'image-test'}, 'status': 'PENDING'}
        with patch.object(wa, '_post', upstream):
            path='/api/send-image?number=5511999998888&requestId=image-one'
            a,b=await asyncio.gather(self.client.post(path,content=png),self.client.post(path,content=png))
            self.assertEqual(a.json()['id'], 'image-test')
            self.assertEqual(b.status_code,200)
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][0],f'/message/sendMedia/{wa.INST}')
            self.assertEqual(calls[0][1]['mediatype'],'image')
            self.assertEqual(calls[0][1]['mimetype'],'image/png')
            self.assertEqual(base64.b64decode(calls[0][1]['media']),png)
            changed=await self.client.post(path.replace('5511999998888','5511888887777'),content=png)
            self.assertEqual(changed.status_code,409)

    async def test_image_send_validation_and_auth(self):
        path='/api/send-image?number=5511999998888&requestId=image-bad'
        self.assertEqual((await self.client.post(path,content=b'<svg/>')).status_code,415)
        self.assertEqual((await self.client.post(path,content=b'x'*(10*1024*1024+1))).status_code,413)
        self.client.cookies.clear()
        self.assertEqual((await self.client.post(path,content=b'abc')).status_code,401)

    def test_shared_contact_vcard(self):
        card = {'vcard': 'BEGIN:VCARD\r\nFN:Hugo\\, Silva\r\nTEL;waid=5511999998888:+55 11 1111-2222\r\nTEL;TYPE=CELL:tel:+55 (11) 99999-8888\r\nTEL:+351 912\r\n 345678\r\nTEL:javascript:123456789\r\nEND:VCARD'}
        typ, text, extra = wa._body({'message': {'ephemeralMessage': {'message': {'contactMessage': card}}}})
        self.assertEqual(typ, 'contact')
        self.assertEqual(text, 'Hugo, Silva')
        self.assertEqual(extra['contacts'][0]['phones'], ['5511999998888', '351912345678'])

    def test_shared_contacts_array_and_missing_phone(self):
        typ, text, extra = wa._body({'message': {'contactsArrayMessage': {'contacts': [
            {'displayName': '<Hugo>', 'vcard': 'TEL;waid=5511999998888:ignored'},
            {'displayName': 'Sem telefone', 'vcard': 'TEL:invalid123456789'}]}}})
        self.assertEqual(typ, 'contact')
        self.assertEqual(len(extra['contacts']), 2)
        self.assertEqual(extra['contacts'][1]['phones'], [])
        self.assertEqual(extra['contacts'][0]['name'], '<Hugo>')

    async def asyncSetUp(self):
        wa._cursors.clear(); wa._sends.clear(); wa._fails.clear()
        wa._trans.clear(); wa._trans_meta.clear(); wa._trans_tasks.clear()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=wa.app), base_url="https://test")
        self.client.cookies.set(wa.COOKIE, wa._token)

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_session_auth_assets_and_login_error(self):
        self.client.cookies.clear()
        self.assertEqual((await self.client.get('/api/session')).status_code, 401)
        wrong = await self.client.post('/api/login', json={"senha": "wrong"})
        self.assertEqual(wrong.status_code, 401)
        login = await self.client.post('/api/login', json={"senha": "test-password"})
        self.assertEqual(login.status_code, 200)
        self.assertIn('Secure', login.headers['set-cookie'])
        self.assertEqual((await self.client.get('/api/session')).json()['version'], (await self.client.get('/healthz')).json()['version'])
        for asset in ('/', '/app.js', '/style.css'):
            self.assertEqual((await self.client.get(asset)).status_code, 200)

    async def test_pwa_assets_and_private_api(self):
        self.client.cookies.clear()
        for asset in ('voice.js','pwa.js','sw.js','manifest.webmanifest','icon-192.png','icon-512.png','apple-touch-icon.png','offline.html'):
            self.assertEqual((await self.client.get('/'+asset)).status_code, 200, asset)
        manifest=(await self.client.get('/manifest.webmanifest')).json()
        self.assertEqual(manifest['display'], 'standalone')
        self.assertEqual((await self.client.post('/api/send-audio?number=test&requestId=one',content=b'abc')).status_code,401)
        self.assertEqual((await self.client.get('/app.py')).status_code,404)

    async def test_groq_model_multipart_and_segments(self):
        original=httpx.AsyncClient
        def handler(request):
            self.assertEqual(str(request.url),'https://api.groq.com/openai/v1/audio/transcriptions')
            self.assertEqual(request.headers['Authorization'],'Bearer test-key')
            self.assertIn(b'whisper-large-v3',request.content)
            self.assertIn(b'filename="audio.ogg"',request.content)
            self.assertNotIn(b'name="language"',request.content)
            return httpx.Response(200,json={'text':'Bom dia.','language':'portuguese','segments':[{'start':0,'end':2,'text':'Bom dia.'}]})
        with patch.object(wa,'GROQ_KEY','test-key'),patch.object(wa,'GROQ_LANGUAGE',''),patch.object(wa.httpx,'AsyncClient',lambda **kwargs: original(transport=httpx.MockTransport(handler),**kwargs)):
            result=await wa._groq_transcribe('audio/ogg;codecs=opus',b'synthetic')
        self.assertEqual(result['texto'],'Bom dia.');self.assertEqual(result['segments'][0]['start'],0)
        self.assertEqual(result['provider'],'Groq')

    async def test_media_ranges_for_transcript_seek(self):
        async def media(jid,mid):return 'audio/ogg',b'0123456789'
        with patch.object(wa,'_fetch_media',media):
            for requested,expected,content_range in [('bytes=3-5',b'345','bytes 3-5/10'),('bytes=7-',b'789','bytes 7-9/10'),('bytes=-2',b'89','bytes 8-9/10')]:
                result=await self.client.get('/api/media?jid=test&id=voice',headers={'Range':requested})
                self.assertEqual(result.status_code,206);self.assertEqual(result.content,expected)
                self.assertEqual(result.headers['content-range'],content_range)
            invalid=await self.client.get('/api/media?jid=test&id=voice',headers={'Range':'bytes=100-'})
            self.assertEqual(invalid.status_code,416)
            self.client.cookies.clear()
            self.assertEqual((await self.client.get('/api/media?jid=test&id=voice',headers={'Range':'bytes=0-'})).status_code,401)

    async def test_groq_errors_are_sanitized(self):
        original=httpx.AsyncClient
        for upstream,expected in [(401,503),(429,429),(500,502)]:
            def handler(request):return httpx.Response(upstream,json={'error':'sensitive provider details'})
            with patch.object(wa.httpx,'AsyncClient',lambda **kwargs: original(transport=httpx.MockTransport(handler),**kwargs)):
                with self.assertRaises(wa.HTTPException) as error:await wa._groq_transcribe('audio/ogg',b'synthetic')
            self.assertEqual(error.exception.status_code,expected)
            self.assertNotIn('sensitive',error.exception.detail)

    async def test_transcription_single_flight_cache_and_empty_speech(self):
        calls=[]
        async def media(jid,mid):return 'audio/ogg',b'synthetic'
        async def transcribe(mime,raw):
            calls.append(1);await asyncio.sleep(.03)
            return {'texto':'','segments':[],'model':'whisper-large-v3','provider':'Groq'}
        with patch.object(wa,'GROQ_KEY','test-key'),patch.object(wa,'_fetch_media',media),patch.object(wa,'_groq_transcribe',transcribe):
            payload={'jid':'test@lid','id':'voice-test'}
            a,b=await asyncio.gather(self.client.post('/api/transcribe',json=payload),self.client.post('/api/transcribe',json=payload))
            self.assertEqual(a.status_code,200);self.assertEqual(a.json(),b.json());self.assertEqual(len(calls),1)
            cached=(await self.client.post('/api/transcribe',json=payload)).json()
            self.assertTrue(cached['cached']);self.assertEqual(len(calls),1)
            self.assertEqual(wa._norm({'key':{'id':'voice-test','remoteJid':'test@lid'},'message':{'audioMessage':{}}})['transcription']['model'],'whisper-large-v3')
            self.client.cookies.clear()
            self.assertEqual((await self.client.post('/api/transcribe',json=payload)).status_code,401)

    async def test_audio_duplicate_conflict_and_validation(self):
        calls=[]
        async def fake(raw,number):
            calls.append((raw,number));await asyncio.sleep(.02)
            return {'id':'audio-one','status':'PENDING'}
        url='/api/send-audio?number=synthetic&requestId=audio-request'
        with patch.object(wa,'_send_voice',fake):
            opts={'content':b'synthetic-audio','headers':{'Content-Type':'audio/webm;codecs=opus'}}
            a,b=await asyncio.gather(self.client.post(url,**opts),self.client.post(url,**opts))
            self.assertEqual(a.json(),b.json());self.assertEqual(len(calls),1)
            self.assertEqual((await self.client.post(url,content=b'other',headers=opts['headers'])).status_code,409)
            self.assertEqual((await self.client.post(url,content=b'',headers=opts['headers'])).status_code,400)
            self.assertEqual((await self.client.post(url,content=b'x',headers={'Content-Type':'text/html'})).status_code,415)
            with patch.object(wa,'MAX_AUDIO',8):
                self.assertEqual((await self.client.post(url,**opts)).status_code,413)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg required for the actual codec test')
    async def test_real_audio_conversion_and_voice_payload(self):
        wav=io.BytesIO()
        with wave.open(wav,'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0\0'*16000)
        calls=[]
        async def fake(path,body):
            calls.append((path,body));return {'key':{'id':'encoded-audio'},'status':'PENDING'}
        with patch.object(wa,'_post',fake):
            result=await self.client.post('/api/send-audio?number=synthetic&requestId=encoded',content=wav.getvalue(),headers={'Content-Type':'audio/wav'})
            self.assertEqual(result.status_code,200,result.text)
        self.assertIn('/message/sendWhatsAppAudio/',calls[0][0])
        self.assertFalse(calls[0][1]['encoding'])
        encoded = base64.b64decode(calls[0][1]['audio'])
        self.assertTrue(encoded.startswith(b'OggS'))
        self.assertIn(b'OpusHead', encoded)
        with self.assertRaises(wa.HTTPException):await wa._voice_ogg(b'invalid audio')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg required for the duration boundary test')
    async def test_voice_duration_boundary(self):
        for seconds in (600.25, 602):
            wav=io.BytesIO()
            with wave.open(wav,'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(8000);f.writeframes(b'\0\0'*int(8000*seconds))
            if seconds<601:
                self.assertIn(b'OpusHead',await wa._voice_ogg(wav.getvalue()))
            else:
                with self.assertRaises(wa.HTTPException) as error:await wa._voice_ogg(wav.getvalue())
                self.assertEqual(error.exception.status_code,400)

    async def test_complete_chronological_merge_and_retry(self):
        # 130 received messages interleaved with 110 sent messages in another JID.
        data = {'a@lid': [record('a@lid', i, 1000-i*2) for i in range(130)],
                'b@s.whatsapp.net': [record('b@s.whatsapp.net', i, 999-i*2, True) for i in range(110)]}
        calls=[]
        async def fake(path, body):
            jid=body['where']['key']['remoteJid']; page=body['page']; calls.append((jid,page))
            return {'messages': {'records': data[jid][(page-1)*50:page*50], 'pages': (len(data[jid])+49)//50}}
        with patch.object(wa, '_post', fake):
            params={'jid':'a@lid','extra':'b@s.whatsapp.net'}
            first=(await self.client.get('/api/messages',params=params)).json()
            self.assertEqual(len(first['messages']),50)
            params['cursor']=first['cursor']
            second=(await self.client.get('/api/messages',params=params)).json()
            repeated=(await self.client.get('/api/messages',params=params)).json()
            self.assertEqual(second['messages'], repeated['messages'])
            pages=[first,second]
            while pages[-1]['hasMore']:
                params['cursor']=pages[-1]['cursor']
                pages.append((await self.client.get('/api/messages',params=params)).json())
            ids=[m['id'] for p in pages for m in p['messages']]
            self.assertEqual(len(ids),240); self.assertEqual(len(set(ids)),240)
            for newer,older in zip(pages,pages[1:]):
                self.assertGreaterEqual(min(m['ts'] for m in newer['messages']), max(m['ts'] for m in older['messages']))
            self.assertIn(('b@s.whatsapp.net',3),calls)
            bad=await self.client.get('/api/messages',params={'jid':'other','cursor':first['cursor']})
            self.assertEqual(bad.status_code,410)

    async def test_skewed_histories_do_not_skip_old_sent_messages(self):
        data={'recent@lid':[record('recent@lid',i,10000-i) for i in range(75)],
              'old@s.whatsapp.net':[record('old@s.whatsapp.net',i,1000-i,True) for i in range(80)]}
        async def fake(path,body):
            records=data[body['where']['key']['remoteJid']]; p=body['page']
            return {'messages':{'records':records[(p-1)*50:p*50],'pages':2}}
        with patch.object(wa,'_post',fake):
            params={'jid':'recent@lid','extra':'old@s.whatsapp.net'}; all_messages=[]
            while True:
                result=(await self.client.get('/api/messages',params=params)).json()
                all_messages += list(reversed(result['messages']))
                if not result['hasMore']: break
                params['cursor']=result['cursor']
            self.assertEqual(len(all_messages),155)
            self.assertEqual([m['ts'] for m in all_messages],sorted([m['ts'] for m in all_messages],reverse=True))

    async def test_concurrent_send_idempotency_and_payload_conflict(self):
        calls=[]
        async def fake(path,body):
            calls.append(body); await asyncio.sleep(.02)
            return {'key':{'id':'confirmed-id'},'status':'PENDING'}
        with patch.object(wa,'_post',fake):
            payload={'number':'synthetic','text':'hello','requestId':'test-send'}
            a,b=await asyncio.gather(self.client.post('/api/send',json=payload),self.client.post('/api/send',json=payload))
            self.assertEqual(a.json(),b.json()); self.assertEqual(len(calls),1)
            conflict=await self.client.post('/api/send',json={**payload,'text':'other'})
            self.assertEqual(conflict.status_code,409)

    async def test_read_failure_and_original_keys(self):
        async def failure(path,body): raise wa.HTTPException(502,'unavailable')
        body={'jid':'merged@lid','keys':[{'id':'1','jid':'real@g.us','participant':'person@lid'}]}
        with patch.object(wa,'_post',failure):
            self.assertEqual((await self.client.post('/api/read',json=body)).status_code,502)
        captured=[]
        async def success(path,data): captured.append(data); return {'read':'success'}
        with patch.object(wa,'_post',success):
            self.assertTrue((await self.client.post('/api/read',json=body)).json()['ok'])
        self.assertEqual(captured[0]['readMessages'][0]['remoteJid'],'real@g.us')
        self.assertEqual(captured[0]['readMessages'][0]['participant'],'person@lid')

    async def test_quote_status_wrapped_content_and_transcription(self):
        rec=record('a@lid',1,1000)
        rec['status']='READ';rec['message']={'ephemeralMessage':{'message':{'extendedTextMessage':{
            'text':'Reply','contextInfo':{'stanzaId':'q','quotedMessage':{'conversation':'Original'}}}}}}
        wa._trans[wa._transcript_identity(rec['key']['remoteJid'], rec['key']['id'])]='Transcript'
        msg=wa._norm(rec)
        self.assertEqual(msg['text'],'Reply');self.assertEqual(msg['quote']['text'],'Original')
        self.assertEqual(msg['status'],'READ');self.assertEqual(msg['transcript'],'Transcript')


if __name__=='__main__': unittest.main()
