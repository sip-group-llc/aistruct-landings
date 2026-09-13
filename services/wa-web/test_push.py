import base64
import json
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from push_service import PushStore, validate_subscription, WebPushException

def subscription():
    key=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    enc=lambda data:base64.urlsafe_b64encode(data).decode().rstrip('=')
    return {'endpoint':'https://fcm.googleapis.com/fcm/send/synthetic','keys':{'p256dh':enc(key),'auth':enc(b'0123456789abcdef')}}

def message(mid,ts,jid='123@lid',**extra):
    return {'key':{'id':mid,'remoteJid':jid,**extra},'messageTimestamp':ts}

class PushTests(unittest.TestCase):
    def test_reject_private_endpoints_and_invalid_keys(self):
        for url in ['https://localhost/test','http://fcm.googleapis.com/x','https://fcm.googleapis.com.evil.test/x','https://user@fcm.googleapis.com/x','https://fcm.googleapis.com:444/x']:
            sub=subscription();sub['endpoint']=url
            with self.assertRaises(ValueError):validate_subscription(sub)
        sub=subscription();sub['keys']['auth']='x'
        with self.assertRaises(ValueError):validate_subscription(sub)

    def test_persistent_keys_reads_dedup_and_old_messages(self):
        with tempfile.TemporaryDirectory() as root:
            store=PushStore(root,'owner');sub=subscription();store.subscribe(sub);key=store.public_key()
            store=PushStore(root,'owner');self.assertEqual(store.public_key(),key)
            now=time.time()+2;records=[message('new',now),message('old',now-86400),message('mine',now,fromMe=True)]
            sent=[];send=lambda **kw:sent.append(kw)
            self.assertEqual(store.deliver(records,now,send=send),1)
            self.assertEqual(store.deliver(records,now+1,send=send),0)
            self.assertEqual(len(sent),1);self.assertNotIn('old',sent[0]['data'])
            store.mark_read([{'remoteJid':'5511@s.whatsapp.net','id':'read'}])
            self.assertEqual(store.deliver([message('read',now+1)],now+2,{'123@lid':'5511'},send),0)
            self.assertEqual(PushStore(root,'different-owner').subscriptions(),[])
            store.remove(sub['endpoint']);self.assertEqual(store.subscriptions(),[])

    def test_failed_delivery_retries_and_expired_subscription_removed(self):
        with tempfile.TemporaryDirectory() as root:
            store=PushStore(root,'owner');store.subscribe(subscription());now=time.time()+2;records=[message('new',now)]
            def failed(**kw):raise RuntimeError('offline')
            self.assertEqual(store.deliver(records,now,send=failed),0)
            self.assertEqual(store.deliver(records,now+1,send=lambda **kw:None),1)
            def expired(**kw):raise WebPushException('gone',response=SimpleNamespace(status_code=410))
            store.deliver([message('next',now+2)],now+3,send=expired);self.assertEqual(store.subscriptions(),[])

    def test_real_webpush_encrypts_and_signs_without_external_request(self):
        with tempfile.TemporaryDirectory() as root:
            store=PushStore(root,'owner');store.subscribe(subscription());now=time.time()+2
            with patch('requests.post',return_value=SimpleNamespace(status_code=201,text='',headers={})) as network:
                self.assertEqual(store.deliver([message('new',now)],now),1)
                self.assertEqual(network.call_count,1)

    def test_alias_duplicates_only_notify_once_and_new_messages_still_notify(self):
        with tempfile.TemporaryDirectory() as root:
            store=PushStore(root,'owner');store.subscribe(subscription());now=time.time()+2;sent=[]
            send=lambda **kw:sent.append(kw)
            records=[message('same',now),message('same',now,'5511@s.whatsapp.net')]
            self.assertEqual(store.deliver(records,now,{'123@lid':'5511'},send),1)
            self.assertEqual(store.deliver(records,now+1,{'123@lid':'5511'},send),0)
            self.assertEqual(store.deliver([message('new',now+2)],now+2,{'123@lid':'5511'},send),1)

if __name__=='__main__':unittest.main()
