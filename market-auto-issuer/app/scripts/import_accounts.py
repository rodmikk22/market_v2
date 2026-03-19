"""
Import digital stock from CSV into the database.

Usage (inside worker container):
  IMPORT_PRODUCT_CODE=MRKT-XXXXXXXX IMPORT_CSV_PATH=/app/stock.csv \
      python -m app.scripts.import_accounts

CSV format (auto-detected):
  - With header: columns secret_payload (required), label (optional)
  - Without header: one item per line
"""
import csv
import io
import logging
import os
import sys

logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="%(asctime)s %(levelname)s — %(message)s")
logger = logging.getLogger(__name__)


def main():
    product_code = os.environ.get("IMPORT_PRODUCT_CODE", "").strip()
    csv_path = os.environ.get("IMPORT_CSV_PATH", "").strip()

    if not product_code:
        logger.error("IMPORT_PRODUCT_CODE env var is required")
        sys.exit(1)
    if not csv_path:
        logger.error("IMPORT_CSV_PATH env var is required")
        sys.exit(1)
    if not os.path.exists(csv_path):
        logger.error("File not found: %s", csv_path)
        sys.exit(1)

    # Import here so DB connection is only opened when script runs
    from app.database import SessionLocal
    from app.models.models import StockItem

    with open(csv_path, encoding="utf-8-sig", errors="replace") as f:
        content = f.read()

    reader = csv.DictReader(io.StringIO(content))
    fieldnames = reader.fieldnames or []

    added = skipped = 0

    with SessionLocal() as db:
        if fieldnames:
            rows = list(reader)
        else:
            rows = [{"secret_payload": line.strip()}
                    for line in content.splitlines() if line.strip()]

        for row in rows:
            payload = (
                row.get("secret_payload") or row.get("payload") or
                row.get("code") or row.get("key") or
                (list(row.values())[0] if row else None)
            )
            if not payload or not str(payload).strip():
                skipped += 1
                continue

            label = str(row.get("label", "")).strip() or None
            db.add(StockItem(
                product_code=product_code,
                secret_payload=str(payload).strip(),
                label=label,
            ))
            added += 1

        db.commit()

    logger.info(
        "Import complete: product_code=%s added=%d skipped=%d",
        product_code, added, skipped,
    )


if __name__ == "__main__":
    main()
