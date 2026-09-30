"""Exercise real checkout construction with only the external transport stubbed."""
import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))
spec = importlib.util.spec_from_file_location("hyu_coupon_test_app", SERVICE / "app.py")
app = importlib.util.module_from_spec(spec)
# A leftover deployment variable must not re-enable implicit coupons.
with patch.dict(os.environ, {"DEFAULT_COUPON": "COSENZA10", "INFLUENCER_COUPONS_JSON": ""}):
    spec.loader.exec_module(app)


class CheckoutCoupons(unittest.TestCase):
    def checkout(self, coupon, tier="kit6"):
        sent = []

        class Client:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, *, headers, json):
                sent.append(json)
                return app.httpx.Response(201, json={"id": "fixture", "checkoutUrl": "https://example.invalid"})

        payload = {"items": [{"flavor": "maca-verde", "tier": tier, "qty": 1}]}
        if coupon is not None:
            payload["coupon"] = coupon
        with patch.object(app.httpx, "AsyncClient", Client), patch.object(app, "FLAT_SHIPPING_CENTS", 3377):
            result = asyncio.run(app._do_checkout(payload))
        return sent[0], result

    def test_no_implicit_coupon(self):
        for coupon in (None, "", "INVALID"):
            with self.subTest(coupon=coupon):
                body, result = self.checkout(coupon)
                self.assertNotIn("coupon", body)
                self.assertNotIn("coupon", body.get("metadata", {}))
                self.assertEqual(result["coupon"], "")
                self.assertEqual(result["discountPct"], 0)
                self.assertEqual(result["totalAmount"], 6990 + 3377)

    def test_explicit_coupon_and_shipping(self):
        for code, pct in (("ARTHURPC", 5), ("COSENZA10", 10), ("JUVZS", 10), ("DOPAMINA10", 10)):
            for tier, price, shipping in (("kit6", 6990, 3377), ("kit12", 11990, 0)):
                with self.subTest(code=code, tier=tier):
                    body, result = self.checkout(code.lower(), tier)
                    discount = price - (price * (100 - pct) + 50) // 100
                    self.assertEqual(body["items"][0]["unitAmount"], price)
                    self.assertEqual(body["coupon"], {"code": code, "type": "fixed", "value": discount})
                    self.assertEqual(body["metadata"]["coupon"], code)
                    self.assertEqual(body["metadata"]["discount_pct"], str(pct))
                    self.assertEqual(result["totalAmount"], price + shipping - discount)
                    self.assertEqual(result["freteCents"], shipping)


if __name__ == "__main__":
    unittest.main()
