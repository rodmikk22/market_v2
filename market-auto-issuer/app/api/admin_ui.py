"""Admin HTML pages (server-rendered with Jinja2)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.models import Issuance

import pathlib

TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()

_ctx = lambda active: {"active": active, "version": settings.APP_VERSION}


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, **_ctx("dashboard")}
    )


@router.get("/admin/stock", response_class=HTMLResponse)
def admin_stock(request: Request):
    return templates.TemplateResponse(
        "stock.html", {"request": request, **_ctx("stock")}
    )


@router.get("/admin/orders", response_class=HTMLResponse)
def admin_orders(request: Request):
    return templates.TemplateResponse(
        "orders.html", {"request": request, **_ctx("orders")}
    )


@router.get("/admin/issuances", response_class=HTMLResponse)
def admin_issuances(request: Request):
    return templates.TemplateResponse(
        "issuances.html", {"request": request, **_ctx("issuances")}
    )


@router.get("/admin/events", response_class=HTMLResponse)
def admin_events(request: Request):
    return templates.TemplateResponse(
        "events.html", {"request": request, **_ctx("events")}
    )


@router.get("/admin/partials/recent_issuances", response_class=HTMLResponse)
def partial_recent_issuances(request: Request, db: Session = Depends(get_db)):
    items = (
        db.query(Issuance)
        .order_by(Issuance.id.desc())
        .limit(10)
        .all()
    )
    BADGE = {"sent": "badge-sent", "failed": "badge-failed", "pending": "badge-pending"}

    def fmt(d):
        if not d:
            return "—"
        return d.strftime("%d.%m.%y %H:%M")

    rows = "".join(
        f"""<tr>
          <td><code class="small">{i.order_id}</code></td>
          <td><span class="status-badge {BADGE.get(i.delivery_status,'')}">
            {i.delivery_status}</span></td>
          <td class="payload-cell small">
            {(i.stock_item.secret_payload[:60] if i.stock_item else '') or '—'}
          </td>
          <td class="small text-muted">{fmt(i.created_at)}</td>
        </tr>"""
        for i in items
    )
    if not rows:
        rows = '<tr><td colspan="4" class="text-center text-muted py-3">Выдач пока нет</td></tr>'

    return HTMLResponse(f"""
    <table class="table table-sm align-middle mb-0">
      <thead class="table-light">
        <tr><th>Заказ</th><th>Статус</th><th>Payload</th><th>Дата</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>""")
