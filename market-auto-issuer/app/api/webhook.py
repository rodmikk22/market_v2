"""
Webhook handler for Yandex Market push notifications.

Critical: Market validates our response for /notification calls.
Required response format:
    {"name": "<str>", "version": "<str>", "time": "<ISO-8601 UTC>"}

Any other format causes: INVALID_RESPONSE / validate error: name must not be null
"""
import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any

import redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from rq import Queue
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.models import IncomingEvent
from app.services.order_processor import process_order_job

logger = logging.getLogger(__name__)
router = APIRouter()

# Redis connection and queue (lazy init)
_redis_conn = None
_queue = None


def _get_queue() -> Queue:
    global _redis_conn, _queue
    if _queue is None:
        import redis as redis_lib
        _redis_conn = redis_lib.from_url(settings.REDIS_URL)
        _queue = Queue("orders", connection=_redis_conn)
    return _queue


def _webhook_response() -> dict:
    """The exact response shape Yandex Market requires."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _verify_signature(request: Request, body: bytes) -> None:
    """Optional HMAC-SHA256 signature check."""
    secret = settings.WEBHOOK_SHARED_SECRET
    if not secret:
        return
    sig = request.headers.get("X-Market-Signature", "")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Invalid webhook signature")


@router.post("/market/webhook")
async def webhook_root(request: Request, db: Session = Depends(get_db)):
    """Legacy / catch-all webhook endpoint."""
    return await _handle_webhook(request, db)


@router.post("/market/webhook/notification")
async def webhook_notification(request: Request, db: Session = Depends(get_db)):
    """Primary notification endpoint registered in Market settings."""
    return await _handle_webhook(request, db)


async def _handle_webhook(request: Request, db: Session) -> dict:
    body = await request.body()
    _verify_signature(request, body)

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        payload = {"_raw": body.decode(errors="replace")}

    notification_type: str = payload.get("type", payload.get("notificationType", "UNKNOWN"))
    order_id: str | None = (
        payload.get("orderId")
        or payload.get("order", {}).get("id")
        if isinstance(payload, dict) else None
    )
    if order_id is not None:
        order_id = str(order_id)

    # Attach request metadata
    payload["_meta"] = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "client_host": request.client.host if request.client else None,
        "url": str(request.url),
    }

    # Persist raw event
    event = IncomingEvent(
        notification_type=notification_type,
        order_id=order_id,
        payload=payload,
    )
    db.add(event)
    db.commit()
    logger.info("Webhook received: type=%s order_id=%s", notification_type, order_id)

    # Enqueue background processing for order events
    if notification_type not in ("PING",) and order_id:
        try:
            q = _get_queue()
            q.enqueue(
                process_order_job,
                order_id,
                job_timeout=300,
                result_ttl=86400,
            )
            logger.info("Enqueued processing for order %s", order_id)
        except Exception as exc:
            logger.error("Failed to enqueue order %s: %s", order_id, exc)

    return _webhook_response()
