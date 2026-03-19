"""Tests for the Admin REST API endpoints."""
import io
import pytest
from sqlalchemy.orm import Session

from app.models.models import StockItem, IncomingEvent, MarketOrder, Issuance


def seed_stock(db: Session, product_code="MRKT-X1", count=3, status="free"):
    items = []
    for i in range(count):
        item = StockItem(
            product_code=product_code,
            secret_payload=f"SECRET-{i}",
            status=status,
        )
        db.add(item)
        items.append(item)
    db.commit()
    return items


class TestStatsEndpoint:
    def test_stats_empty_db(self, client):
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "totals" in body
        assert body["totals"]["free"] == 0

    def test_stats_counts_correctly(self, client, db_session):
        seed_stock(db_session, count=4, status="free")
        seed_stock(db_session, count=2, status="issued")

        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["totals"]["free"] == 4
        assert body["totals"]["issued"] == 2


class TestStockEndpoints:
    def test_list_stock_empty(self, client):
        resp = client.get("/api/admin/stock")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["items"] == []

    def test_add_stock_item(self, client):
        resp = client.post("/api/admin/stock", data={
            "product_code": "MRKT-NEW",
            "secret_payload": "MY-KEY-123",
            "label": "test batch",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["product_code"] == "MRKT-NEW"
        assert body["secret_payload"] == "MY-KEY-123"
        assert body["status"] == "free"
        assert body["id"] > 0

    def test_add_stock_persists(self, client, db_session):
        client.post("/api/admin/stock", data={
            "product_code": "MRKT-PERSIST",
            "secret_payload": "PAYLOAD-999",
        })
        item = db_session.query(StockItem).filter_by(product_code="MRKT-PERSIST").first()
        assert item is not None
        assert item.secret_payload == "PAYLOAD-999"

    def test_list_stock_pagination(self, client, db_session):
        seed_stock(db_session, count=10)
        resp = client.get("/api/admin/stock?page=1&per_page=4")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 10
        assert len(body["items"]) == 4

    def test_list_stock_filter_by_product_code(self, client, db_session):
        seed_stock(db_session, "MRKT-A", count=3)
        seed_stock(db_session, "MRKT-B", count=2)

        resp = client.get("/api/admin/stock?product_code=MRKT-A")
        assert resp.status_code == 200
        assert resp.json()["total"] == 3

    def test_list_stock_filter_by_status(self, client, db_session):
        seed_stock(db_session, count=3, status="free")
        seed_stock(db_session, count=2, status="issued")

        resp = client.get("/api/admin/stock?status=issued")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_update_stock_item(self, client, db_session):
        items = seed_stock(db_session, count=1)
        item_id = items[0].id

        resp = client.put(f"/api/admin/stock/{item_id}", data={
            "label": "updated label",
            "status": "issued",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["label"] == "updated label"
        assert body["status"] == "issued"

    def test_update_nonexistent_returns_404(self, client):
        resp = client.put("/api/admin/stock/99999", data={"label": "x"})
        assert resp.status_code == 404

    def test_delete_free_item(self, client, db_session):
        items = seed_stock(db_session, count=1)
        item_id = items[0].id

        resp = client.delete(f"/api/admin/stock/{item_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == item_id

        # Should be gone
        assert db_session.query(StockItem).get(item_id) is None

    def test_delete_reserved_item_rejected(self, client, db_session):
        items = seed_stock(db_session, count=1, status="reserved")
        item_id = items[0].id

        resp = client.delete(f"/api/admin/stock/{item_id}")
        assert resp.status_code == 400


class TestCSVImport:
    def test_import_simple_csv_no_header(self, client, db_session):
        csv_content = b"CODE-001\nCODE-002\nCODE-003\n"
        resp = client.post(
            "/api/admin/stock/import",
            data={"product_code": "MRKT-IMP"},
            files={"file": ("test.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["added"] == 3
        assert body["skipped"] == 0
        assert db_session.query(StockItem).filter_by(product_code="MRKT-IMP").count() == 3

    def test_import_csv_with_header(self, client, db_session):
        csv_content = b"secret_payload,label\nKEY-A,batch1\nKEY-B,batch1\n"
        resp = client.post(
            "/api/admin/stock/import",
            data={"product_code": "MRKT-HEAD"},
            files={"file": ("test.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert resp.status_code == 200
        assert resp.json()["added"] == 2

    def test_import_skips_empty_lines(self, client, db_session):
        csv_content = b"KEY-1\n\n\nKEY-2\n\n"
        resp = client.post(
            "/api/admin/stock/import",
            data={"product_code": "MRKT-SKIP"},
            files={"file": ("test.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["added"] == 2
        assert body["skipped"] == 3  # 3 empty lines


class TestOrdersEndpoint:
    def test_list_orders_empty(self, client):
        resp = client.get("/api/admin/orders")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_orders_pagination(self, client, db_session):
        for i in range(5):
            db_session.add(MarketOrder(order_id=str(i), status="PROCESSING"))
        db_session.commit()

        resp = client.get("/api/admin/orders?page=1&per_page=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2


class TestIssuancesEndpoint:
    def test_list_issuances_empty(self, client):
        resp = client.get("/api/admin/issuances")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_issuances_with_filter(self, client, db_session):
        for status in ["sent", "sent", "failed"]:
            db_session.add(Issuance(
                order_id="111",
                order_item_key="111:0",
                delivery_status=status,
            ))
        db_session.commit()

        resp = client.get("/api/admin/issuances?status=sent")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_filter_by_order_id(self, client, db_session):
        for oid in ["AAA", "BBB", "AAA"]:
            db_session.add(Issuance(
                order_id=oid,
                order_item_key=f"{oid}:0",
                delivery_status="sent",
            ))
        db_session.commit()

        resp = client.get("/api/admin/issuances?order_id=AAA")
        assert resp.json()["total"] == 2


class TestEventsEndpoint:
    def test_list_events_pagination(self, client, db_session):
        for i in range(6):
            db_session.add(IncomingEvent(
                notification_type="PING",
                payload={"type": "PING"},
            ))
        db_session.commit()

        resp = client.get("/api/admin/events?page=1&per_page=3")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 6
        assert len(body["items"]) == 3
