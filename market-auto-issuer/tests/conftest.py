"""
Shared pytest fixtures for the full test suite.

Uses:
- SQLite in-memory for DB (no Postgres needed in CI)
- fakeredis for queue
- httpx.AsyncClient for FastAPI endpoint tests
- respx for mocking Yandex Market API calls
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("MARKET_API_TOKEN", "ACMA:test_token")
os.environ.setdefault("MARKET_CAMPAIGN_ID", "12345")
os.environ.setdefault("MARKET_BUSINESS_ID", "67890")
os.environ.setdefault("DELIVERY_MODE", "dry_run")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app


# ── In-memory SQLite engine ──────────────────────────────────────────────────
@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # SQLite doesn't enforce FK by default
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ── FastAPI test client with DB override ─────────────────────────────────────
@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ── Sample data helpers ───────────────────────────────────────────────────────
@pytest.fixture
def sample_stock(db_session):
    """Insert 5 free stock items for two product codes."""
    from app.models.models import StockItem
    items = [
        StockItem(product_code="MRKT-AAA", secret_payload=f"KEY-AAA-{i}", status="free")
        for i in range(3)
    ] + [
        StockItem(product_code="MRKT-BBB", secret_payload=f"KEY-BBB-{i}", status="free")
        for i in range(2)
    ]
    for item in items:
        db_session.add(item)
    db_session.commit()
    return items


@pytest.fixture
def ping_payload():
    return {"type": "PING", "notificationType": "PING"}


@pytest.fixture
def order_created_payload():
    return {
        "type": "ORDER_CREATED",
        "notificationType": "ORDER_CREATED",
        "orderId": "555",
        "order": {"id": 555},
    }
