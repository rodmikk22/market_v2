"""
Inventory service: reserve, finalize, release stock items.
All operations are inside DB transactions to prevent double-issuance.
"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.models.models import StockItem

logger = logging.getLogger(__name__)


class InsufficientStockError(Exception):
    def __init__(self, product_code: str, needed: int, available: int):
        self.product_code = product_code
        self.needed = needed
        self.available = available
        super().__init__(
            f"Not enough stock for {product_code}: need {needed}, have {available}"
        )


def reserve_stock_items(
    db: Session, product_code: str, count: int, order_id: str
) -> list[StockItem]:
    """
    Atomically reserve `count` free items of `product_code` for `order_id`.
    Returns the reserved StockItem objects.
    Raises InsufficientStockError if there aren't enough free items.
    """
    # Lock rows for update so concurrent workers don't double-reserve
    items = (
        db.execute(
            select(StockItem)
            .where(
                StockItem.product_code == product_code,
                StockItem.status == "free",
            )
            .limit(count)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )

    if len(items) < count:
        available = count_free(db, product_code)
        raise InsufficientStockError(product_code, count, available)

    for item in items:
        item.status = "reserved"
        item.reserved_for_order_id = order_id

    db.flush()
    logger.info(
        "Reserved %d items of %s for order %s",
        len(items), product_code, order_id,
    )
    return list(items)


def finalize_stock_items(
    db: Session, items: list[StockItem], order_id: str
) -> None:
    """Mark items as issued after successful delivery."""
    for item in items:
        item.status = "issued"
        item.issued_to_order_id = order_id
        item.reserved_for_order_id = None
    db.flush()


def release_stock_items(db: Session, items: list[StockItem]) -> None:
    """Release reserved items back to free (on delivery failure)."""
    for item in items:
        item.status = "free"
        item.reserved_for_order_id = None
    db.flush()
    logger.warning("Released %d reserved items back to free", len(items))


def count_by_status(db: Session) -> dict:
    """Return {product_code: {status: count}} for dashboard."""
    rows = (
        db.execute(
            select(
                StockItem.product_code,
                StockItem.status,
                func.count(StockItem.id).label("cnt"),
            ).group_by(StockItem.product_code, StockItem.status)
        )
        .all()
    )
    result: dict = {}
    for row in rows:
        result.setdefault(row.product_code, {"free": 0, "reserved": 0, "issued": 0})
        result[row.product_code][row.status] = row.cnt
    return result


def count_free(db: Session, product_code: str) -> int:
    return db.scalar(
        select(func.count(StockItem.id)).where(
            StockItem.product_code == product_code,
            StockItem.status == "free",
        )
    ) or 0
