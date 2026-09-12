"""Read-only Core `Table` objects for the Postgres views the app queries.

`v_leads_curated`, `v_latest_prediction` and `v_current_priority` are database
VIEWs (see db/migrations/001_init.sql and the DDL `db.py` generates for
`v_current_priority`), not tables the app writes to -- so unlike models.py they
are not mapped as ORM classes. A lightweight, non-mapped `Table` is the right
idiom for reading a view through Core `select()`.

Columns are declared explicitly (rather than `autoload_with=engine`) so the
module can be imported -- and used to build queries -- without a live database
connection.
"""
from sqlalchemy import (BigInteger, Boolean, Column, DateTime, Float, Integer,
                        MetaData, Numeric, SmallInteger, String, Table)

metadata = MetaData(schema="pe")

# Mirrors pe.leads exactly -- v_leads_curated is `SELECT DISTINCT ON (lead_id) *`.
v_leads_curated = Table(
    "v_leads_curated", metadata,
    Column("id", BigInteger),
    Column("lead_id", String),
    Column("created_at", DateTime(timezone=True)),
    Column("product_type", String),
    Column("channel", String),
    Column("device", String),
    Column("partner", String),
    Column("city", String),
    Column("insurance_company", String),
    Column("payment_type", String),
    Column("price", Numeric(14, 2)),
    Column("discount_percent", Numeric(6, 2)),
    Column("expected_margin", Numeric(14, 2)),
    Column("days_to_policy_expiry", Integer),
    Column("minutes_since_abandonment", Integer),
    Column("sessions_last_7d", Integer),
    Column("offer_views_last_7d", Integer),
    Column("price_comparisons_last_7d", Integer),
    Column("days_since_last_visit", Numeric(8, 2)),
    Column("has_previous_purchase", SmallInteger),
    Column("visited_offer_page", SmallInteger),
    Column("incoming_call_last_24h", SmallInteger),
    Column("completed_purchase", SmallInteger),
    Column("ingested_at", DateTime(timezone=True)),
)

# DISTINCT ON (lead_id) newest raw prediction, joined to lead context.
v_latest_prediction = Table(
    "v_latest_prediction", metadata,
    Column("lead_id", String),
    Column("model_version", String),
    Column("probability", Float),
    Column("score", Integer),
    Column("scored_at_age_minutes", Float),
    Column("predicted_at", DateTime(timezone=True)),
    Column("batch_id", String),
    Column("lead_created_at", DateTime(timezone=True)),
    Column("product_type", String),
    Column("channel", String),
    Column("device", String),
    Column("partner", String),
    Column("city", String),
    Column("insurance_company", String),
    Column("payment_type", String),
    Column("price", Numeric(14, 2)),
    Column("discount_percent", Numeric(6, 2)),
    Column("expected_margin", Numeric(14, 2)),
    Column("days_to_policy_expiry", Integer),
    Column("minutes_since_abandonment", Integer),
    Column("sessions_last_7d", Integer),
    Column("offer_views_last_7d", Integer),
    Column("days_since_last_visit", Numeric(8, 2)),
    Column("has_previous_purchase", SmallInteger),
    Column("visited_offer_page", SmallInteger),
    Column("incoming_call_last_24h", SmallInteger),
    Column("completed_purchase", SmallInteger),
)

# v_latest_prediction's columns, plus the read-time decay/ranking columns the
# generated DDL in db.py (PRIORITY_VIEW_SQL) adds on top.
v_current_priority = Table(
    "v_current_priority", metadata,
    *(Column(c.name, c.type) for c in v_latest_prediction.columns),
    Column("current_age_minutes", Float),
    Column("excess_minutes", Float),
    Column("is_stale", Boolean),
    Column("decayed_odds", Float),
    Column("decayed_probability", Float),
    Column("expected_value", Float),
    Column("priority_rank", BigInteger),
    Column("priority_tier", String),
)
