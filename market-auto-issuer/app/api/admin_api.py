"""Admin REST API — used by the admin UI (Jinja2 + HTMX)."""
import csv
import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.models import IncomingEvent, Issuance, MarketOrder, StockItem
from app.services.inventory_service import count_by_status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin")


# ─────────────────────────── Dashboard ──────────────────────────────────────

@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    stock = count_by_status(db)
    total_free = sum(v.get("free", 0) for v in stock.values())
    total_reserved = sum(v.get("reserved", 0) for v in stock.values())
    total_issued = sum(v.get("issued", 0) for v in stock.values())
    total_orders = db.query(MarketOrder).count()
    total_events = db.query(IncomingEvent).count()
    sent_issuances = db.query(Issuance).filter(Issuance.delivery_status == "sent").count()
    failed_issuances = db.query(Issuance).filter(Issuance.delivery_status == "failed").count()
    return {
        "stock": stock,
        "totals": {
            "free": total_free,
            "reserved": total_reserved,
            "issued": total_issued,
        },
        "orders": total_orders,
        "events": total_events,
        "issuances_sent": sent_issuances,
        "issuances_failed": failed_issuances,
    }


# ─────────────────────────── Stock items ────────────────────────────────────

@router.get("/stock")
def list_stock(
    db: Session = Depends(get_db),
    product_code: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    q = db.query(StockItem)
    if product_code:
        q = q.filter(StockItem.product_code == product_code)
    if status:
        q = q.filter(StockItem.status == status)
    total = q.count()
    items = q.order_by(desc(StockItem.id)).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [_stock_dict(i) for i in items],
    }


@router.post("/stock")
def add_stock_item(
    product_code: str = Form(...),
    secret_payload: str = Form(...),
    label: str = Form(default=""),
    db: Session = Depends(get_db),
):
    item = StockItem(
        product_code=product_code.strip(),
        secret_payload=secret_payload.strip(),
        label=label.strip() or None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _stock_dict(item)


@router.put("/stock/{item_id}")
def update_stock_item(
    item_id: int,
    product_code: str = Form(None),
    secret_payload: str = Form(None),
    label: str = Form(None),
    status: str = Form(None),
    db: Session = Depends(get_db),
):
    item = db.query(StockItem).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    if product_code is not None:
        item.product_code = product_code.strip()
    if secret_payload is not None:
        item.secret_payload = secret_payload.strip()
    if label is not None:
        item.label = label.strip() or None
    if status is not None and status in ("free", "reserved", "issued"):
        item.status = status
    db.commit()
    db.refresh(item)
    return _stock_dict(item)


@router.delete("/stock/{item_id}")
def delete_stock_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(StockItem).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    if item.status != "free":
        raise HTTPException(status_code=400, detail="Can only delete free items")
    db.delete(item)
    db.commit()
    return {"deleted": item_id}


@router.post("/stock/import")
async def import_stock_csv(
    product_code: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Import stock items from a CSV file.
    Expected columns: secret_payload  (and optionally: label)
    First row can be a header — auto-detected.
    """
    content = await file.read()
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    # Fallback: if no header row detected, treat first column as secret_payload
    fieldnames = reader.fieldnames or []
    use_dict = bool(fieldnames)

    added = 0
    skipped = 0

    if use_dict:
        rows = list(reader)
    else:
        # plain list, no header
        rows = [{"secret_payload": line.strip()}
                for line in text.splitlines() if line.strip()]

    for row in rows:
        payload = (
            row.get("secret_payload") or
            row.get("payload") or
            row.get("code") or
            row.get("key") or
            (list(row.values())[0] if row else None)
        )
        if not payload or not payload.strip():
            skipped += 1
            continue

        label = row.get("label", "").strip() or None

        db.add(StockItem(
            product_code=product_code.strip(),
            secret_payload=payload.strip(),
            label=label,
        ))
        added += 1

    db.commit()
    return {"added": added, "skipped": skipped, "product_code": product_code}


# ─────────────────────────── Orders ─────────────────────────────────────────

@router.get("/orders")
def list_orders(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    total = db.query(MarketOrder).count()
    items = (
        db.query(MarketOrder)
        .order_by(desc(MarketOrder.id))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [_order_dict(o) for o in items],
    }


# ─────────────────────────── Events ─────────────────────────────────────────

@router.get("/events")
def list_events(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    total = db.query(IncomingEvent).count()
    items = (
        db.query(IncomingEvent)
        .order_by(desc(IncomingEvent.id))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [_event_dict(e) for e in items],
    }


# ─────────────────────────── Issuances ───────────────────────────────────────

@router.get("/issuances")
def list_issuances(
    db: Session = Depends(get_db),
    order_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    q = db.query(Issuance)
    if order_id:
        q = q.filter(Issuance.order_id == order_id)
    if status:
        q = q.filter(Issuance.delivery_status == status)
    total = q.count()
    items = q.order_by(desc(Issuance.id)).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [_issuance_dict(i) for i in items],
    }


# ─────────────────────────── Serializers ─────────────────────────────────────

def _stock_dict(i: StockItem) -> dict:
    return {
        "id": i.id,
        "product_code": i.product_code,
        "secret_payload": i.secret_payload,
        "label": i.label,
        "status": i.status,
        "reserved_for_order_id": i.reserved_for_order_id,
        "issued_to_order_id": i.issued_to_order_id,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


def _order_dict(o: MarketOrder) -> dict:
    return {
        "id": o.id,
        "order_id": o.order_id,
        "status": o.status,
        "substatus": o.substatus,
        "raw_order": o.raw_order,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


def _event_dict(e: IncomingEvent) -> dict:
    return {
        "id": e.id,
        "notification_type": e.notification_type,
        "order_id": e.order_id,
        "payload": e.payload,
        "received_at": e.received_at.isoformat() if e.received_at else None,
    }


def _issuance_dict(i: Issuance) -> dict:
    return {
        "id": i.id,
        "order_id": i.order_id,
        "order_item_key": i.order_item_key,
        "stock_item_id": i.stock_item_id,
        "delivery_status": i.delivery_status,
        "delivery_message_id": i.delivery_message_id,
        "error_text": i.error_text,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "secret_payload": (
            i.stock_item.secret_payload if i.stock_item else None
        ),
    }
