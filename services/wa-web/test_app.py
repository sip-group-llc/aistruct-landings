"""Regression tests with synthetic records; never contact Evolution or send messages."""
import asyncio
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx

for key, value in {"EVOLUTION_URL": "https://evolution.invalid", "EVOLUTION_APIKEY": "test",
                   "WA_PASSWORD": "test-password", "WA_SECRET": "test-secret", "TRANSCRIBER_URL": ""}.items():
    os.environ[key] = value
spec = importlib.util.spec_from_file_location("wa_under_test", Path(__file__).with_name("app.py"))
wa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wa)


def record(jid, n, ts, from_me=False):
    return {"key": {"id": f"{jid}-{n}", "remoteJid": jid, "fromMe": from_me},
            "messageTimestamp": ts, "message": {"conversation": f"synthetic {n}"}}


class AppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        wa._cursors.clear(); wa._sends.clear(); wa._fails.clear()
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
        self.assertEqual((await self.client.get('/api/session')).json()['version'], '2026.09.12.2')
        for asset in ('/', '/app.js', '/style.css'):
            self.assertEqual((await self.client.get(asset)).status_code, 200)

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
        async def success(path,data): captured.append(data); return {}
        with patch.object(wa,'_post',success):
            self.assertTrue((await self.client.post('/api/read',json=body)).json()['ok'])
        self.assertEqual(captured[0]['readMessages'][0]['remoteJid'],'real@g.us')
        self.assertEqual(captured[0]['readMessages'][0]['participant'],'person@lid')

    async def test_quote_status_wrapped_content_and_transcription(self):
        rec=record('a@lid',1,1000)
        rec['status']='READ';rec['message']={'ephemeralMessage':{'message':{'extendedTextMessage':{
            'text':'Reply','contextInfo':{'stanzaId':'q','quotedMessage':{'conversation':'Original'}}}}}}
        wa._trans[rec['key']['id']]='Transcript'
        msg=wa._norm(rec)
        self.assertEqual(msg['text'],'Reply');self.assertEqual(msg['quote']['text'],'Original')
        self.assertEqual(msg['status'],'READ');self.assertEqual(msg['transcript'],'Transcript')


if __name__=='__main__': unittest.main()
