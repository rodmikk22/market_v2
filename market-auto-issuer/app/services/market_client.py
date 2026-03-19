"""
Yandex Market Partner API client.

Key points (from production experience):
- Auth header is  Api-Key: <token>  (NOT Authorization: Bearer)
- deliverDigitalGoods: codes[] length MUST equal item.count
- Long payloads go into `slip`, short keys/codes go into `codes`
"""
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Codes longer than this threshold are treated as "instructions" → slip field
_CODE_MAX_LEN = 64


class MarketClientError(Exception):
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Market API error {status_code}: {body}")


def _headers() -> dict:
    return {
        "Api-Key": settings.MARKET_API_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_order(order_id: str) -> dict:
    """Fetch a single order from Partner API."""
    url = (
        f"{settings.MARKET_API_BASE}/v2/campaigns"
        f"/{settings.MARKET_CAMPAIGN_ID}/orders/{order_id}"
    )
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, headers=_headers())
    if resp.status_code != 200:
        raise MarketClientError(resp.status_code, resp.text)
    data = resp.json()
    return data.get("order", data)


def send_digital_goods(order_id: str, items: list[dict]) -> dict:
    """
    Call POST /v2/campaigns/{campaignId}/orders/{orderId}/deliverDigitalGoods.

    `items` is a list of dicts:
        {
            "id": <order_item_id: int>,
            "count": <how many codes needed: int>,
            "payloads": ["payload1", "payload2", ...]  # len == count
        }

    Each payload is split into code + slip intelligently:
    - If payload is short enough → put in `codes[]`
    - If payload is long → put a placeholder in `codes[]`, full text in `slip`
    """
    request_items = []
    for item in items:
        item_id: int = item["id"]
        payloads: list[str] = item["payloads"]
        count: int = item["count"]

        if len(payloads) != count:
            raise ValueError(
                f"Item {item_id}: expected {count} payloads, got {len(payloads)}"
            )

        # Build codes list — codes must not be blank
        codes = []
        slip_parts = []
        for idx, payload in enumerate(payloads, start=1):
            if len(payload) <= _CODE_MAX_LEN and "\n" not in payload:
                codes.append(payload)
            else:
                # Short code token + full content goes to slip
                token = f"ITEM{item_id}-{idx}"
                codes.append(token)
                slip_parts.append(f"[{token}]\n{payload}")

        item_payload: dict = {
            "id": item_id,
            "codes": codes,
            "activate_till": "2099-12-31",
        }
        if slip_parts:
            item_payload["slip"] = "\n\n---\n\n".join(slip_parts)

        request_items.append(item_payload)

    url = (
        f"{settings.MARKET_API_BASE}/v2/campaigns"
        f"/{settings.MARKET_CAMPAIGN_ID}/orders/{order_id}/deliverDigitalGoods"
    )
    body = {"items": request_items}

    logger.info("Delivering digital goods to order %s: %s", order_id, body)

    with httpx.Client(timeout=30) as client:
        resp = client.post(url, headers=_headers(), json=body)

    if resp.status_code not in (200, 201, 204):
        raise MarketClientError(resp.status_code, resp.text)

    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}
