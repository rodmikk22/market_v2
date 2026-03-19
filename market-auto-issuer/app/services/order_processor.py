"""
Order processor — core fulfillment logic.

Flow:
1. Fetch order from Partner API
2. Save/update snapshot in market_orders
3. Check if status is allowed for fulfillment
4. Check if order was already fulfilled (idempotency)
5. For each order item, reserve item.count stock items
6. Deliver all items in one API call
7. On success: mark stock as issued + issuances as sent
8. On failure: release stock + mark issuances as failed
"""
import logging
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.models import MarketOrder, Issuance
from app.services import market_client, inventory_service, delivery_service
from app.services.inventory_service import InsufficientStockError

logger = logging.getLogger(__name__)

ALLOWED_STATUSES = {"PROCESSING", "DELIVERY", "PICKUP"}


def process_order_job(order_id: str) -> None:
    """Entry point called by the RQ worker."""
    logger.info("Processing order %s", order_id)
    with SessionLocal() as db:
        try:
            _process(db, order_id)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("Unhandled error processing order %s: %s", order_id, exc)
            raise


def _process(db: Session, order_id: str) -> None:
    # ── 1. Fetch from Market API ──────────────────────────────────────────
    try:
        raw_order = market_client.get_order(order_id)
    except market_client.MarketClientError as exc:
        logger.error("Could not fetch order %s from API: %s", order_id, exc)
        _upsert_order_snapshot(db, order_id, None, None, {"error": str(exc)})
        return

    status: str = raw_order.get("status", "")
    substatus: str = raw_order.get("substatus", "")

    # ── 2. Save snapshot ──────────────────────────────────────────────────
    _upsert_order_snapshot(db, order_id, status, substatus, raw_order)

    # ── 3. Check allowed status ───────────────────────────────────────────
    allowed = set(settings.ALLOWED_ISSUE_STATUSES) | ALLOWED_STATUSES
    if status not in allowed:
        logger.info(
            "Order %s has status '%s' — not in allowed list, skipping",
            order_id, status,
        )
        return

    # ── 4. Idempotency check — already fulfilled? ─────────────────────────
    existing = (
        db.query(Issuance)
        .filter(
            Issuance.order_id == order_id,
            Issuance.delivery_status == "sent",
        )
        .first()
    )
    if existing:
        logger.info("Order %s already has sent issuances — skipping", order_id)
        return

    # ── 5. Collect order items ────────────────────────────────────────────
    order_items: list[dict] = raw_order.get("items", [])
    if not order_items:
        logger.warning("Order %s has no items", order_id)
        return

    # ── 6. Reserve stock for every item ───────────────────────────────────
    delivery_items = []
    all_reserved = []

    try:
        for idx, item in enumerate(order_items):
            product_code: str = item.get("offerId", "")
            count: int = item.get("count", 1)
            order_item_id: int = item.get("id")

            if not product_code:
                raise ValueError(f"Item at index {idx} has no offerId")

            reserved = inventory_service.reserve_stock_items(
                db, product_code, count, order_id
            )
            all_reserved.extend(reserved)
            delivery_items.append({
                "order_item_id": order_item_id,
                "order_item_idx": idx,
                "stock_items": reserved,
            })

        # ── 7. Deliver ────────────────────────────────────────────────────
        success = delivery_service.deliver_order_items(db, order_id, delivery_items)

        if success:
            # Mark stock as issued
            for di in delivery_items:
                inventory_service.finalize_stock_items(db, di["stock_items"], order_id)
            logger.info("Order %s fulfilled successfully", order_id)
        else:
            # Release stock back to free
            inventory_service.release_stock_items(db, all_reserved)
            logger.error("Order %s delivery failed — stock released", order_id)

    except InsufficientStockError as exc:
        inventory_service.release_stock_items(db, all_reserved)
        logger.error("Insufficient stock for order %s: %s", order_id, exc)
        # Save error issuance record
        from app.models.models import Issuance as Iss
        iss = Iss(
            order_id=order_id,
            order_item_key=f"{order_id}:0",
            delivery_status="failed",
            error_text=str(exc),
        )
        db.add(iss)

    except Exception as exc:
        inventory_service.release_stock_items(db, all_reserved)
        logger.exception("Unexpected error for order %s: %s", order_id, exc)
        raise


def _upsert_order_snapshot(
    db: Session, order_id: str, status, substatus, raw_order
) -> None:
    snap = db.query(MarketOrder).filter(MarketOrder.order_id == order_id).first()
    if snap:
        snap.status = status
        snap.substatus = substatus
        snap.raw_order = raw_order
    else:
        snap = MarketOrder(
            order_id=order_id,
            status=status,
            substatus=substatus,
            raw_order=raw_order,
        )
        db.add(snap)
    db.flush()
