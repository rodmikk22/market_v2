"""Tests for delivery_service — bridges processor and Market API."""
import pytest
from unittest.mock import patch, MagicMock

from app.models.models import StockItem, Issuance
from app.services import delivery_service


def make_stock_item(db_session, payload="SECRET-XYZ"):
    item = StockItem(
        product_code="MRKT-TEST",
        secret_payload=payload,
        status="reserved",
    )
    db_session.add(item)
    db_session.commit()
    return item


class TestDeliverOrderItems:

    def test_dry_run_mode_returns_true(self, db_session):
        """DELIVERY_MODE != yandex_digital → skip real call, mark sent."""
        item = make_stock_item(db_session)

        result = delivery_service.deliver_order_items(
            db_session,
            order_id="ORDER-DRY",
            delivery_items=[{
                "order_item_id": 1001,
                "order_item_idx": 0,
                "stock_items": [item],
            }],
        )
        db_session.commit()

        assert result is True
        iss = db_session.query(Issuance).filter_by(order_id="ORDER-DRY").first()
        assert iss is not None
        assert iss.delivery_status == "sent"

    def test_yandex_digital_success_creates_sent_issuance(self, db_session):
        from app.config import settings
        item = make_stock_item(db_session, "KEY-ABCD")

        with patch.object(settings.__class__, "DELIVERY_MODE",
                          new_callable=lambda: property(lambda self: "yandex_digital")), \
             patch("app.services.delivery_service.market_client.send_digital_goods",
                   return_value={"status": "OK"}) as mock_send:

            result = delivery_service.deliver_order_items(
                db_session,
                order_id="ORDER-YD",
                delivery_items=[{
                    "order_item_id": 2001,
                    "order_item_idx": 0,
                    "stock_items": [item],
                }],
            )
            db_session.commit()

        assert result is True
        iss = db_session.query(Issuance).filter_by(order_id="ORDER-YD").first()
        assert iss.delivery_status == "sent"

    def test_yandex_digital_failure_creates_failed_issuance(self, db_session):
        from app.config import settings
        from app.services.market_client import MarketClientError
        item = make_stock_item(db_session)

        with patch.object(settings.__class__, "DELIVERY_MODE",
                          new_callable=lambda: property(lambda self: "yandex_digital")), \
             patch("app.services.delivery_service.market_client.send_digital_goods",
                   side_effect=MarketClientError(400, "Required=2, found=1")):

            result = delivery_service.deliver_order_items(
                db_session,
                order_id="ORDER-FAIL",
                delivery_items=[{
                    "order_item_id": 3001,
                    "order_item_idx": 0,
                    "stock_items": [item],
                }],
            )
            db_session.commit()

        assert result is False
        iss = db_session.query(Issuance).filter_by(order_id="ORDER-FAIL").first()
        assert iss.delivery_status == "failed"
        assert iss.error_text is not None

    def test_multiple_items_create_multiple_issuances(self, db_session):
        items = [make_stock_item(db_session, f"KEY-{i}") for i in range(3)]

        result = delivery_service.deliver_order_items(
            db_session,
            order_id="ORDER-MULTI",
            delivery_items=[{
                "order_item_id": 4001,
                "order_item_idx": 0,
                "stock_items": items,
            }],
        )
        db_session.commit()

        assert result is True
        issuances = db_session.query(Issuance).filter_by(order_id="ORDER-MULTI").all()
        assert len(issuances) == 3

    def test_issuance_has_stock_item_id(self, db_session):
        item = make_stock_item(db_session, "LINKED-KEY")

        delivery_service.deliver_order_items(
            db_session,
            order_id="ORDER-LINK",
            delivery_items=[{
                "order_item_id": 5001,
                "order_item_idx": 0,
                "stock_items": [item],
            }],
        )
        db_session.commit()

        iss = db_session.query(Issuance).filter_by(order_id="ORDER-LINK").first()
        assert iss.stock_item_id == item.id
