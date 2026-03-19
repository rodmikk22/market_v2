"""Tests for inventory_service: reserve, finalize, release, counts."""
import pytest
from sqlalchemy.orm import Session

from app.models.models import StockItem
from app.services.inventory_service import (
    InsufficientStockError,
    count_by_status,
    count_free,
    finalize_stock_items,
    release_stock_items,
    reserve_stock_items,
)


def make_items(db: Session, product_code: str, count: int, status: str = "free") -> list[StockItem]:
    items = []
    for i in range(count):
        item = StockItem(
            product_code=product_code,
            secret_payload=f"SECRET-{product_code}-{i}",
            status=status,
        )
        db.add(item)
        items.append(item)
    db.commit()
    return items


class TestReserveStockItems:
    def test_reserve_exact_count(self, db_session):
        make_items(db_session, "PROD-A", 3)
        reserved = reserve_stock_items(db_session, "PROD-A", 3, "order-1")
        db_session.commit()

        assert len(reserved) == 3
        for item in reserved:
            assert item.status == "reserved"
            assert item.reserved_for_order_id == "order-1"

    def test_reserve_partial_count(self, db_session):
        make_items(db_session, "PROD-B", 5)
        reserved = reserve_stock_items(db_session, "PROD-B", 2, "order-2")
        db_session.commit()

        assert len(reserved) == 2
        assert count_free(db_session, "PROD-B") == 3

    def test_reserve_raises_when_insufficient(self, db_session):
        make_items(db_session, "PROD-C", 1)
        with pytest.raises(InsufficientStockError) as exc_info:
            reserve_stock_items(db_session, "PROD-C", 3, "order-3")

        err = exc_info.value
        assert err.product_code == "PROD-C"
        assert err.needed == 3
        assert err.available == 1

    def test_reserve_raises_when_empty(self, db_session):
        with pytest.raises(InsufficientStockError):
            reserve_stock_items(db_session, "NONEXISTENT", 1, "order-x")

    def test_reserve_does_not_take_already_reserved(self, db_session):
        """Reserved items should not be re-reserved."""
        make_items(db_session, "PROD-D", 2)
        # Reserve both
        reserve_stock_items(db_session, "PROD-D", 2, "order-10")
        db_session.commit()

        with pytest.raises(InsufficientStockError):
            reserve_stock_items(db_session, "PROD-D", 1, "order-11")

    def test_reserve_does_not_take_issued(self, db_session):
        make_items(db_session, "PROD-E", 1, status="issued")
        with pytest.raises(InsufficientStockError):
            reserve_stock_items(db_session, "PROD-E", 1, "order-12")


class TestFinalizeStockItems:
    def test_finalize_marks_as_issued(self, db_session):
        make_items(db_session, "PROD-F", 2)
        reserved = reserve_stock_items(db_session, "PROD-F", 2, "order-20")
        db_session.commit()

        finalize_stock_items(db_session, reserved, "order-20")
        db_session.commit()

        for item in reserved:
            db_session.refresh(item)
            assert item.status == "issued"
            assert item.issued_to_order_id == "order-20"
            assert item.reserved_for_order_id is None


class TestReleaseStockItems:
    def test_release_returns_to_free(self, db_session):
        make_items(db_session, "PROD-G", 3)
        reserved = reserve_stock_items(db_session, "PROD-G", 3, "order-30")
        db_session.commit()

        release_stock_items(db_session, reserved)
        db_session.commit()

        for item in reserved:
            db_session.refresh(item)
            assert item.status == "free"
            assert item.reserved_for_order_id is None

        assert count_free(db_session, "PROD-G") == 3


class TestCountByStatus:
    def test_count_mixed_statuses(self, db_session):
        make_items(db_session, "PROD-H", 3, "free")
        make_items(db_session, "PROD-H", 2, "issued")
        make_items(db_session, "PROD-H", 1, "reserved")

        stats = count_by_status(db_session)
        assert stats["PROD-H"]["free"] == 3
        assert stats["PROD-H"]["issued"] == 2
        assert stats["PROD-H"]["reserved"] == 1

    def test_count_multiple_products(self, db_session):
        make_items(db_session, "PROD-I", 4, "free")
        make_items(db_session, "PROD-J", 2, "free")

        stats = count_by_status(db_session)
        assert stats["PROD-I"]["free"] == 4
        assert stats["PROD-J"]["free"] == 2

    def test_count_free_helper(self, db_session):
        make_items(db_session, "PROD-K", 5, "free")
        make_items(db_session, "PROD-K", 2, "issued")
        assert count_free(db_session, "PROD-K") == 5
