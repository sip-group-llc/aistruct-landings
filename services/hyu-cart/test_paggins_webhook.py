"""Isolated regression checks; fake secret, temporary DB and mocked network only.

Run: uv run --no-project --with-requirements requirements.txt python -m unittest test_paggins_webhook -v
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

os.environ["PAGGINS_WEBHOOK_SECRET"] = "whsec_test_only"
os.environ["PAGGINS_API_KEY"] = "test_only"
os.environ["LEADS_DB"] = os.path.join(tempfile.gettempdir(), "hyu_import_unused.db")
os.environ["BLING_CLIENT_ID"] = ""
os.environ["BLING_CLIENT_SECRET"] = ""
os.environ["BLING_REFRESH_TOKEN"] = ""

import httpx
from fastapi.testclient import TestClient
import app as bridge


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        bridge.LEADS_DB = os.path.join(self.tmp.name, "orders.db")
        bridge.PAGGINS_WEBHOOK_SECRET = "whsec_test_only"
        self.client = TestClient(bridge.app)
        self.worker = patch.object(bridge, "_enrich_then_bling", new_callable=AsyncMock)
        self.dispatch = self.worker.start()
        conn = bridge._db()
        conn.execute("INSERT INTO pedidos (order_id, session_id, status, total_cents, "
                     "subtotal_cents, frete_cents, coupon, meta, items) "
                     "VALUES ('hyu-first','cs_first','created',8991,8991,0,'WOLFZ','{}','[]')")
        conn.execute("INSERT INTO pedidos (order_id, session_id, status, total_cents, "
                     "frete_cents, coupon, meta, items) "
                     "VALUES ('hyu-second','cs_second','created',6990,0,'','{}','[]')")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.worker.stop()
        self.client.close()
        self.tmp.cleanup()

    def send(self, event=None, raw=None, timestamp=None, delivery=None):
        if raw is None:
            raw = json.dumps(event or self.event(), separators=(",", ":")).encode()
        stamp = str(int(time.time()) if timestamp is None else timestamp)
        sig = hmac.new(b"whsec_test_only", stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        headers = {"X-Paggins-Signature": f"t={stamp},v1={sig}"}
        if delivery:
            headers["X-Paggins-Delivery-Id"] = delivery
        return self.client.post("/webhook/paggins", content=raw, headers=headers)

    def event(self):
        return {"id": "delivery-first", "event": "order.paid", "data": {
            "orderId": "paggins-first", "externalOrderId": "hyu-first",
            "checkoutSessionId": "cs_first", "effectiveAmount": 89.91,
            "currency": "BRL", "customer": {"document": "12345678901", "phoneNumber": "11999999999"}}}

    def scalar(self, sql):
        conn = bridge._db()
        try:
            return conn.execute(sql).fetchone()[0]
        finally:
            conn.close()

    def test_signed_paid_maps_customer_and_deduplicates(self):
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.send().json(), {"received": True, "duplicate": True})
        self.assertEqual(self.scalar("SELECT status FROM pedidos WHERE id=1"), "paid")
        self.assertEqual(self.scalar("SELECT document FROM pedidos WHERE id=1"), "12345678901")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders"), 1)
        self.dispatch.assert_called_once_with(1, "cs_first")

    def test_header_delivery_and_external_order_dedup_with_truncated_payload(self):
        ev = self.event()
        del ev["id"]
        del ev["data"]["checkoutSessionId"]
        del ev["data"]["orderId"]
        ev["data"]["padding"] = "x" * 5000
        self.assertEqual(self.send(ev, delivery="header-first").status_code, 200)
        self.assertTrue(self.send(ev, delivery="header-first").json()["duplicate"])
        self.assertTrue(self.send(ev, delivery="header-second").json()["duplicate"])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders"), 1)

    def test_parallel_deliveries_schedule_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.send(), range(8)))
        self.assertTrue(all(r.status_code == 200 for r in responses))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders"), 1)
        self.dispatch.assert_called_once()

    def test_bad_signature_stale_timestamp_and_missing_secret(self):
        self.assertEqual(self.client.post("/webhook/paggins", json=self.event()).status_code, 401)
        self.assertEqual(self.send(timestamp=int(time.time()) - 301).status_code, 401)
        bridge.PAGGINS_WEBHOOK_SECRET = ""
        self.assertEqual(self.send().status_code, 503)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders"), 0)

    def test_shape_and_matching_are_validated_before_writes(self):
        self.assertEqual(self.send(raw=b"[]").status_code, 400)
        ev = self.event()
        ev["data"]["externalOrderId"] = "hyu-second"
        self.assertEqual(self.send(ev).status_code, 400)
        ev = self.event()
        ev["data"]["effectiveAmount"] = 0.01
        self.assertEqual(self.send(ev).status_code, 400)
        ev = self.event()
        ev["data"]["currency"] = "USD"
        self.assertEqual(self.send(ev).status_code, 400)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders"), 0)

    def test_failed_or_fulfilled_never_marks_paid(self):
        ev = self.event()
        ev["data"]["payment"] = {"status": "failed"}
        self.assertTrue(self.send(ev).json()["ignored"])
        ev["event"] = "order.fulfilled"
        self.assertEqual(self.send(ev).status_code, 200)
        self.assertEqual(self.scalar("SELECT status FROM pedidos WHERE id=1"), "created")
        self.dispatch.assert_not_called()

    def test_legacy_raw_signature_and_nested_session(self):
        ev = {"event": "payment.succeeded", "data": {
            "sessionId": "cs_first", "payment": {"amount": 8991, "status": "paid"}}}
        raw = json.dumps(ev).encode()
        sig = hmac.new(b"whsec_test_only", raw, hashlib.sha256).hexdigest()
        response = self.client.post("/webhook/paggins", content=raw,
                                    headers={"X-Paggins-Signature": sig})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.scalar("SELECT status FROM pedidos WHERE id=1"), "paid")

    def test_refund_holds_order_commission_and_replayed_paid(self):
        self.send()
        conn = bridge._db()
        conn.execute("INSERT INTO comissoes (order_id,pedido_id,status) VALUES ('hyu-first',1,'pending')")
        conn.commit()
        conn.close()
        ev = self.event()
        ev["id"] = "refund-first"
        ev["event"] = "order.partially_refunded"
        del ev["data"]["checkoutSessionId"]
        del ev["data"]["externalOrderId"]
        self.assertTrue(self.send(ev).json()["review"])
        self.assertEqual(self.scalar("SELECT status FROM pedidos WHERE id=1"), "review")
        self.assertEqual(self.scalar("SELECT status FROM comissoes WHERE pedido_id=1"), "review")
        self.assertTrue(self.send().json()["duplicate"])
        self.assertEqual(self.scalar("SELECT status FROM pedidos WHERE id=1"), "review")
        self.dispatch.assert_called_once()
        bridge._credit_commission("hyu-first", 1, "WOLF", 8991, "WOLFZ")
        self.assertEqual(self.scalar("SELECT status FROM comissoes WHERE pedido_id=1"), "review")

    def test_paggins_credits_existing_affiliate_coupon(self):
        conn = bridge._db()
        conn.execute("INSERT INTO afiliados (tag,cupom,pct,active) VALUES ('WOLF','WOLFZ',5,1)")
        conn.commit()
        conn.close()
        self.send()
        self.send()
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM comissoes"), 1)
        self.assertEqual(self.scalar("SELECT base_cents FROM comissoes"), 8991)

    def test_checkout_discount_shipping_and_simple_checkout_are_persisted(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = httpx.Response(201, json={"id": "cs_created", "checkoutUrl": "https://www.paggins.com/checkout/external/cs_created"})
        with patch.object(bridge.httpx, "AsyncClient") as client_class:
            client_class.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(bridge._do_checkout({
                "items": [{"flavor": "tropical", "tier": "kit6"}], "coupon": "WOLFZ"}))
        self.assertEqual(result["totalAmount"], 6291 + bridge.FLAT_SHIPPING_CENTS)
        self.assertEqual(self.scalar("SELECT subtotal_cents FROM pedidos WHERE session_id='cs_created'"), 6291)
        stored = json.loads(self.scalar("SELECT items FROM pedidos WHERE session_id='cs_created'"))
        self.assertEqual(stored[0]["cents"], 6291)
        self.assertEqual(mock_client.post.call_args.kwargs["json"]["requireShippingInfo"], True)
        self.assertEqual(mock_client.post.call_args.kwargs["json"]["items"][-1]["sku"], "HYU-FRETE")

    def test_free_shipping_mixed_kits_oos_and_unpaid_bling(self):
        lines = bridge._cart_lines([{"flavor": "tropical", "tier": "kit6", "qty": 2}])
        self.assertEqual(sum(ln["cans"] for ln in lines), 12)
        mix = bridge._cart_lines([{"mix": {"tropical": 3, "maca-verde": 3}, "tier": "kit6"}])
        self.assertEqual(mix[0]["cents"], 6990 + bridge.MIX_FEE_CENTS)
        with self.assertRaises(bridge.HTTPException):
            bridge._cart_lines([{"flavor": "hot-lemon", "tier": "kit6"}])
        with patch.object(bridge.BLING, "ensure_contato", new_callable=AsyncMock) as contact:
            asyncio.run(bridge._bling_dispatch(1))
            contact.assert_not_called()


if __name__ == "__main__":
    unittest.main()
