from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, JSON, ForeignKey, func
)
from sqlalchemy.orm import relationship

from app.database import Base


class IncomingEvent(Base):
    """Raw webhook payloads received from Yandex Market."""
    __tablename__ = "incoming_events"

    id = Column(Integer, primary_key=True, index=True)
    notification_type = Column(String(64), nullable=False, index=True)
    order_id = Column(String(64), nullable=True, index=True)
    payload = Column(JSON, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MarketOrder(Base):
    """Snapshot of a Yandex Market order fetched from Partner API."""
    __tablename__ = "market_orders"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(64), nullable=True)
    substatus = Column(String(64), nullable=True)
    raw_order = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    issuances = relationship("Issuance", back_populates="order")


class StockItem(Base):
    """A single digital item (key / account / code) in the warehouse."""
    __tablename__ = "stock_items"

    id = Column(Integer, primary_key=True, index=True)
    # Must match offerId on Yandex Market (e.g. MRKT-H5D87B1O)
    product_code = Column(String(128), nullable=False, index=True)
    # The secret to deliver: could be a key, login+pass, instructions, etc.
    secret_payload = Column(Text, nullable=False)
    # free | reserved | issued
    status = Column(String(16), nullable=False, default="free", index=True)
    # Tracking who this item is reserved/issued for
    reserved_for_order_id = Column(String(64), nullable=True, index=True)
    issued_to_order_id = Column(String(64), nullable=True, index=True)
    # Optional label shown in admin UI
    label = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=func.now())

    issuances = relationship("Issuance", back_populates="stock_item")


class Issuance(Base):
    """Delivery log — one row per delivered item per order."""
    __tablename__ = "issuances"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(64), nullable=False, index=True)
    # "{order_id}:{item_idx}" — matches Market order item key
    order_item_key = Column(String(128), nullable=False)
    stock_item_id = Column(Integer, ForeignKey("stock_items.id"), nullable=True)
    # pending | sent | failed
    delivery_status = Column(String(16), nullable=False, default="pending")
    # Response / message ID from Market delivery API
    delivery_message_id = Column(String(256), nullable=True)
    error_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    order = relationship("MarketOrder", foreign_keys=[order_id],
                         primaryjoin="Issuance.order_id == MarketOrder.order_id",
                         back_populates="issuances")
    stock_item = relationship("StockItem", back_populates="issuances")
