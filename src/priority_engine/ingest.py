"""Load the CSV into Postgres. Run once at startup; the pipeline reads Postgres."""
import logging

import pandas as pd
from sqlalchemy import distinct, func

from .config import CFG
from .db import engine, session
from .models import Lead

log = logging.getLogger(__name__)

COLUMNS = {
    "Lead ID": "lead_id", "Created At": "created_at", "Product Type": "product_type",
    "Channel": "channel", "Device": "device", "Partner": "partner", "City": "city",
    "Insurance Company": "insurance_company", "Payment Type": "payment_type",
    "Minutes Since Abandonment": "minutes_since_abandonment",
    "Days To Policy Expiry": "days_to_policy_expiry", "Price": "price",
    "Discount Percent": "discount_percent",
    "Has Previous Purchase": "has_previous_purchase",
    "Visited Offer Page": "visited_offer_page",
    "Incoming Call Last 24h": "incoming_call_last_24h",
    "Sessions Last 7d": "sessions_last_7d", "Offer Views Last 7d": "offer_views_last_7d",
    "Price Comparisons Last 7d": "price_comparisons_last_7d",
    "Days Since Last Visit": "days_since_last_visit",
    "Expected Margin": "expected_margin", "Completed Purchase": "completed_purchase",
}


def load_csv(force=False):
    with session() as s:
        existing = s.query(func.count(Lead.id)).scalar() or 0
        if existing and not force:
            log.info("leads already loaded (%s rows), skipping", existing)
            return existing
        if force:
            s.query(Lead).delete()

    path = CFG["csv_path"]
    if not path.exists():
        raise SystemExit(
            f"\nDataset not found: {path}\n"
            f"The repository ships the code, not the data. Copy the CSV in first:\n"
            f"    cp /path/to/leads.csv data/leads.csv\n"
            f"then run `docker compose up` again.\n"
        )

    df = pd.read_csv(path).rename(columns=COLUMNS)
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
    df = df[list(COLUMNS.values())]

    df.to_sql("leads", engine, schema="pe", if_exists="append", index=False,
              chunksize=1000, method="multi")

    with session() as s:
        total = s.query(func.count(Lead.id)).scalar()
        dupes = total - s.query(func.count(distinct(Lead.lead_id))).scalar()
    log.info("loaded %s rows (%s duplicate lead_ids, deduped by v_leads_curated)", total, dupes)
    return total
