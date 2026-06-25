"""
WebHarvest License Server — PayOS Payment Integration.

Python implementation of PayOS REST API (no official Python SDK available).
Follows the same flow as xuongmedia's Node.js payosService.js.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

import httpx

logger = logging.getLogger("license.payos")

PAYOS_API_BASE = "https://api-merchant.payos.vn"


class PayOSService:
    """PayOS REST API client for Python (equivalent to @payos/node)."""

    def __init__(self, client_id: str, api_key: str, checksum_key: str):
        self.client_id = client_id
        self.api_key = api_key
        self.checksum_key = checksum_key

    def _compute_checksum(self, data: dict) -> str:
        """Compute HMAC-SHA256 checksum for PayOS requests.

        PayOS signature: sort keys alphabetically → build query string → HMAC-SHA256.
        """
        sorted_data = dict(sorted(data.items()))
        query_string = "&".join(f"{k}={v}" for k, v in sorted_data.items() if v is not None)
        return hmac.new(
            self.checksum_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def create_payment_link(
        self,
        order_code: int,
        amount: int,
        description: str,
        return_url: str,
        cancel_url: str,
        buyer_name: str = "",
        buyer_email: str = "",
        buyer_phone: str = "",
        items: list = None,
    ) -> dict:
        """Create a PayOS payment link.

        Returns: {"checkoutUrl": "https://pay.payos.vn/...", ...}
        Equivalent to xuongmedia's createPaymentLink.
        """
        payload = {
            "orderCode": order_code,
            "amount": amount,
            "description": description[:25],  # PayOS max 25 chars
            "returnUrl": return_url,
            "cancelUrl": cancel_url,
        }

        if buyer_name:
            payload["buyerName"] = buyer_name
        if buyer_email:
            payload["buyerEmail"] = buyer_email
        if buyer_phone:
            payload["buyerPhone"] = buyer_phone
        if items:
            payload["items"] = items

        # Compute signature on required fields
        sig_data = {
            "amount": amount,
            "cancelUrl": cancel_url,
            "description": description[:25],
            "orderCode": order_code,
            "returnUrl": return_url,
        }
        payload["signature"] = self._compute_checksum(sig_data)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{PAYOS_API_BASE}/v2/payment-requests",
                json=payload,
                headers={
                    "x-client-id": self.client_id,
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") == "00":
                return result.get("data", {})
            else:
                raise PayOSError(
                    f"PayOS create link failed: {result.get('desc', 'Unknown error')}"
                )

    async def get_payment_info(self, order_code: int) -> dict:
        """Query payment status from PayOS.

        Equivalent to xuongmedia's getPaymentInfo.
        """
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{PAYOS_API_BASE}/v2/payment-requests/{order_code}",
                headers={
                    "x-client-id": self.client_id,
                    "x-api-key": self.api_key,
                },
            )
            resp.raise_for_status()
            result = resp.json()
            if result.get("code") == "00":
                return result.get("data", {})
            raise PayOSError(f"PayOS query failed: {result.get('desc')}")

    def verify_webhook(self, payload: dict) -> dict | None:
        """Verify webhook signature from PayOS.

        Equivalent to xuongmedia's verifyPaymentWebhookData.
        Returns the verified data dict, or None if verification fails.
        """
        data = payload.get("data", {})
        received_sig = payload.get("signature", "")

        if not data or not received_sig:
            logger.warning("Webhook missing data or signature")
            return None

        # Compute expected signature from data fields
        sig_data = {}
        for key in sorted(data.keys()):
            val = data[key]
            if val is not None:
                sig_data[key] = val

        expected_sig = self._compute_checksum(sig_data)

        if not hmac.compare_digest(expected_sig, received_sig):
            logger.warning("Webhook signature mismatch")
            return None

        return data

    async def confirm_webhook_url(self, webhook_url: str) -> bool:
        """Register/confirm webhook URL with PayOS."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{PAYOS_API_BASE}/confirm-webhook",
                    json={"webhookUrl": webhook_url},
                    headers={
                        "x-client-id": self.client_id,
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                )
                logger.info("PayOS webhook URL confirmed: %s (status=%d)", webhook_url, resp.status_code)
                return resp.status_code == 200
        except Exception as e:
            logger.warning("PayOS webhook confirmation failed: %s", e)
            return False


class PayOSError(Exception):
    pass
