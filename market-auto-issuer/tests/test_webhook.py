"""Tests for the Yandex Market webhook endpoints."""
import json
import pytest
from sqlalchemy import select

from app.models.models import IncomingEvent


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body


class TestWebhookPing:
    def test_ping_returns_required_fields(self, client, ping_payload):
        resp = client.post("/api/market/webhook/notification", json=ping_payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] is not None and body["name"] != ""
        assert body["version"] is not None and body["version"] != ""
        assert body["time"] is not None and body["time"] != ""

    def test_ping_saved_to_db(self, client, db_session, ping_payload):
        client.post("/api/market/webhook/notification", json=ping_payload)
        event = db_session.execute(
            select(IncomingEvent).where(IncomingEvent.notification_type == "PING")
        ).scalar_one_or_none()
        assert event is not None
        assert event.notification_type == "PING"

    def test_webhook_root_also_works(self, client, ping_payload):
        resp = client.post("/api/market/webhook", json=ping_payload)
        assert resp.status_code == 200
        body = resp.json()
        assert "name" in body and "version" in body and "time" in body


class TestWebhookOrderCreated:
    def test_order_created_saved_with_order_id(self, client, db_session, order_created_payload):
        resp = client.post("/api/market/webhook/notification", json=order_created_payload)
        assert resp.status_code == 200
        # Correct response shape
        body = resp.json()
        assert body["name"] is not None

        # Event saved in DB
        event = db_session.execute(
            select(IncomingEvent).where(IncomingEvent.order_id == "555")
        ).scalar_one_or_none()
        assert event is not None
        assert event.notification_type == "ORDER_CREATED"

    def test_order_status_updated_saved(self, client, db_session):
        payload = {
            "type": "ORDER_STATUS_UPDATED",
            "orderId": "999",
            "order": {"id": 999, "status": "PROCESSING"},
        }
        resp = client.post("/api/market/webhook/notification", json=payload)
        assert resp.status_code == 200
        event = db_session.execute(
            select(IncomingEvent).where(IncomingEvent.order_id == "999")
        ).scalar_one_or_none()
        assert event is not None

    def test_meta_fields_added_to_payload(self, client, db_session, order_created_payload):
        client.post("/api/market/webhook/notification", json=order_created_payload)
        event = db_session.execute(
            select(IncomingEvent).where(IncomingEvent.order_id == "555")
        ).scalar_one()
        assert "_meta" in event.payload
        assert "received_at" in event.payload["_meta"]

    def test_invalid_json_handled_gracefully(self, client):
        resp = client.post(
            "/api/market/webhook/notification",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        # Should not crash — returns 200 with proper shape
        assert resp.status_code == 200

    def test_multiple_events_stored_independently(self, client, db_session):
        for i in range(3):
            payload = {"type": "ORDER_CREATED", "orderId": str(100 + i)}
            client.post("/api/market/webhook/notification", json=payload)

        count = db_session.execute(
            select(IncomingEvent).where(
                IncomingEvent.notification_type == "ORDER_CREATED"
            )
        ).scalars().all()
        assert len(count) == 3
