"""Delivery service — bridges order processor and Market API."""
import logging
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import StockItem, Issuance
from app.services import market_client

logger = logging.getLogger(__name__)


def deliver_order_items(
    db: Session,
    order_id: str,
    delivery_items: list[dict],
) -> bool:
    """
    Send digital goods for one order.

    `delivery_items` is a list of:
        {
            "order_item_id": int,          # from Market order
            "order_item_idx": int,         # position in order (for logging)
            "stock_items": [StockItem, ...]  # reserved items, len == item.count
        }

    Returns True on success, False on failure.
    Creates Issuance records for every item.
    """
    if settings.DELIVERY_MODE != "yandex_digital":
        logger.warning("DELIVERY_MODE is '%s' — skipping real delivery", settings.DELIVERY_MODE)
        _create_issuances(db, order_id, delivery_items, status="sent",
                          message="dry-run mode")
        return True

    # Build payload for Market API
    api_items = []
    for di in delivery_items:
        api_items.append({
            "id": di["order_item_id"],
            "count": len(di["stock_items"]),
            "payloads": [s.secret_payload for s in di["stock_items"]],
        })

    try:
        result = market_client.send_digital_goods(order_id, api_items)
        logger.info("Delivery OK for order %s: %s", order_id, result)
        _create_issuances(db, order_id, delivery_items, status="sent",
                          message=str(result))
        return True
    except Exception as exc:
        logger.error("Delivery FAILED for order %s: %s", order_id, exc)
        _create_issuances(db, order_id, delivery_items, status="failed",
                          error=str(exc))
        return False


def _create_issuances(
    db: Session,
    order_id: str,
    delivery_items: list[dict],
    status: str,
    message: str = None,
    error: str = None,
) -> None:
    for di in delivery_items:
        idx = di["order_item_idx"]
        for stock_item in di["stock_items"]:
            iss = Issuance(
                order_id=order_id,
                order_item_key=f"{order_id}:{idx}",
                stock_item_id=stock_item.id,
                delivery_status=status,
                delivery_message_id=message,
                error_text=error,
            )
            db.add(iss)
    db.flush()
