"""
Tests for order_processor — full fulfillment pipeline.
Market API calls are intercepted with respx (httpx mock).
"""
import pytest
import respx
import httpx
from unittest.mock import patch, MagicMock

from app.models.models import StockItem, MarketOrder, Issuance
from app.services import order_processor
from app.services.inventory_service import InsufficientStockError


ORDER_ID = "77777"
OFFER_ID = "MRKT-TEST01"


def _make_raw_order(status="PROCESSING", items=None):
    if items is None:
        items = [{"id": 1001, "offerId": OFFER_ID, "count": 1}]
    return {
        "id": int(ORDER_ID),
        "status": status,
        "substatus": "STARTED",
        "items": items,
    }


def _seed_stock(db_session, count=3):
    for i in range(count):
        item = StockItem(
            product_code=OFFER_ID,
            secret_payload=f"CODE-{i:04d}",
            status="free",
        )
        db_session.add(item)
    db_session.commit()


class TestProcessOrderJob:

    def test_saves_order_snapshot(self, db_session):
        raw = _make_raw_order()
        _seed_stock(db_session)

        with patch("app.services.order_processor.market_client.get_order", return_value=raw), \
             patch("app.services.delivery_service.deliver_order_items", return_value=True), \
             patch("app.services.order_processor.SessionLocal") as mock_sl:
            mock_sl.return_value.__enter__ = lambda s: db_session
            mock_sl.return_value.__exit__ = MagicMock(return_value=False)
            order_processor._process(db_session, ORDER_ID)
            db_session.commit()

        snap = db_session.query(MarketOrder).filter_by(order_id=ORDER_ID).first()
        assert snap is not None
        assert snap.status == "PROCESSING"

    def test_skips_non_allowed_status(self, db_session):
        raw = _make_raw_order(status="CANCELLED")
        _seed_stock(db_session)

        with patch("app.services.order_processor.market_client.get_order", return_value=raw), \
             patch("app.services.delivery_service.deliver_order_items") as mock_del:
            order_processor._process(db_session, ORDER_ID)

        mock_del.assert_not_called()

    def test_idempotency_already_sent(self, db_session):
        """If order already has a 'sent' issuance, skip re-processing."""
        raw = _make_raw_order()
        _seed_stock(db_session)

        # Pre-create a sent issuance
        iss = Issuance(
            order_id=ORDER_ID,
            order_item_key=f"{ORDER_ID}:0",
            delivery_status="sent",
        )
        db_session.add(iss)
        db_session.commit()

        with patch("app.services.order_processor.market_client.get_order", return_value=raw), \
             patch("app.services.delivery_service.deliver_order_items") as mock_del:
            order_processor._process(db_session, ORDER_ID)

        mock_del.assert_not_called()

    def test_fulfills_single_item(self, db_session):
        raw = _make_raw_order()
        _seed_stock(db_session, count=2)

        with patch("app.services.order_processor.market_client.get_order", return_value=raw), \
             patch("app.services.delivery_service.deliver_order_items", return_value=True) as mock_del:
            order_processor._process(db_session, ORDER_ID)
            db_session.commit()

        mock_del.assert_called_once()
        call_args = mock_del.call_args
        assert call_args[0][1] == ORDER_ID
        delivery_items = call_args[0][2]
        assert len(delivery_items) == 1
        assert len(delivery_items[0]["stock_items"]) == 1

    def test_fulfills_multi_item_order_count_2(self, db_session):
        """Order with count=2 must reserve and deliver exactly 2 codes."""
        raw = _make_raw_order(items=[{"id": 2001, "offerId": OFFER_ID, "count": 2}])
        _seed_stock(db_session, count=5)

        with patch("app.services.order_processor.market_client.get_order", return_value=raw), \
             patch("app.services.delivery_service.deliver_order_items", return_value=True) as mock_del:
            order_processor._process(db_session, ORDER_ID)
            db_session.commit()

        delivery_items = mock_del.call_args[0][2]
        assert len(delivery_items[0]["stock_items"]) == 2

    def test_fulfills_multi_line_order(self, db_session):
        """Order with 3 different line items, each count=1."""
        OFFER_B = "MRKT-TEST02"
        OFFER_C = "MRKT-TEST03"
        for code in [OFFER_ID, OFFER_B, OFFER_C]:
            db_session.add(StockItem(product_code=code, secret_payload=f"S-{code}", status="free"))
        db_session.commit()

        raw = _make_raw_order(items=[
            {"id": 3001, "offerId": OFFER_ID, "count": 1},
            {"id": 3002, "offerId": OFFER_B, "count": 1},
            {"id": 3003, "offerId": OFFER_C, "count": 1},
        ])

        with patch("app.services.order_processor.market_client.get_order", return_value=raw), \
             patch("app.services.delivery_service.deliver_order_items", return_value=True) as mock_del:
            order_processor._process(db_session, ORDER_ID)
            db_session.commit()

        delivery_items = mock_del.call_args[0][2]
        assert len(delivery_items) == 3

    def test_releases_stock_on_delivery_failure(self, db_session):
        raw = _make_raw_order()
        _seed_stock(db_session, count=2)

        with patch("app.services.order_processor.market_client.get_order", return_value=raw), \
             patch("app.services.delivery_service.deliver_order_items", return_value=False):
            order_processor._process(db_session, ORDER_ID)
            db_session.commit()

        # All stock back to free
        free_count = db_session.query(StockItem).filter_by(
            product_code=OFFER_ID, status="free"
        ).count()
        assert free_count == 2

    def test_creates_failed_issuance_on_insufficient_stock(self, db_session):
        raw = _make_raw_order(items=[{"id": 4001, "offerId": OFFER_ID, "count": 5}])
        _seed_stock(db_session, count=2)  # Only 2 available, need 5

        with patch("app.services.order_processor.market_client.get_order", return_value=raw), \
             patch("app.services.delivery_service.deliver_order_items") as mock_del:
            order_processor._process(db_session, ORDER_ID)
            db_session.commit()

        mock_del.assert_not_called()
        iss = db_session.query(Issuance).filter_by(order_id=ORDER_ID).first()
        assert iss is not None
        assert iss.delivery_status == "failed"
        assert "stock" in iss.error_text.lower() or "PROD" in iss.error_text or OFFER_ID in iss.error_text

    def test_api_error_saved_to_snapshot(self, db_session):
        from app.services.market_client import MarketClientError
        with patch(
            "app.services.order_processor.market_client.get_order",
            side_effect=MarketClientError(403, "OAuth token is invalid"),
        ):
            order_processor._process(db_session, ORDER_ID)
            db_session.commit()

        snap = db_session.query(MarketOrder).filter_by(order_id=ORDER_ID).first()
        assert snap is not None
        assert "error" in snap.raw_order

    def test_marks_stock_issued_after_success(self, db_session):
        raw = _make_raw_order()
        _seed_stock(db_session, count=2)

        with patch("app.services.order_processor.market_client.get_order", return_value=raw), \
             patch("app.services.delivery_service.deliver_order_items", return_value=True):
            order_processor._process(db_session, ORDER_ID)
            db_session.commit()

        issued = db_session.query(StockItem).filter_by(
            issued_to_order_id=ORDER_ID, status="issued"
        ).count()
        assert issued == 1
