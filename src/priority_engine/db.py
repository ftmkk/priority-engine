"""Database access. Plain SQL through SQLAlchemy — no ORM layer."""
import logging
import time

import pandas as pd
from sqlalchemy import create_engine, text

from .config import CFG, ROOT

log = logging.getLogger(__name__)
engine = create_engine(CFG["db_url"], pool_pre_ping=True, future=True)


def wait_ready(timeout=90):
    """Postgres may still be booting when the api/worker container starts."""
    deadline = time.time() + timeout
    while True:
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            return
        except Exception:
            if time.time() > deadline:
                raise
            time.sleep(1.5)


def migrate():
    """Run db/migrations/*.sql, then build the live priority view from config."""
    with engine.begin() as c:
        for f in sorted((ROOT / "db" / "migrations").glob("*.sql")):
            c.execute(text(f.read_text()))
            log.info("applied %s", f.name)
    create_priority_view()


def clock_sql():
    """The reference for "now". This dataset is a fixed historical snapshot, so
    wall-clock time would put every lead far past its support; `dataset` reads
    the newest created_at instead. Production uses `wall`."""
    return ("(SELECT max(created_at) FROM pe.leads)"
            if CFG["priority"]["clock"] == "dataset" else "now()")


PRIORITY_VIEW_SQL = """
CREATE OR REPLACE VIEW pe.v_current_priority AS
WITH ref AS (SELECT {clock} AS at),
aged AS (
    SELECT
        p.*,
        -- the lead's abandonment age right now
        p.minutes_since_abandonment
            + GREATEST(EXTRACT(EPOCH FROM (r.at - p.lead_created_at)) / 60.0, 0)
          AS current_age_minutes
    FROM pe.v_latest_prediction p CROSS JOIN ref r
),
fresh AS (
    -- Only leads still worth calling are in the queue at all.
    SELECT * FROM aged WHERE current_age_minutes <= {horizon}
),
decayed AS (
    SELECT
        f.*,
        -- Inside the support the stored score is already current, because the
        -- scoring job re-inferred it at this age -- so there is nothing to decay.
        -- Past the boundary the model has no evidence, so we decay the anchor by
        -- how far beyond it we now are, capped so the arithmetic stays sane.
        LEAST(GREATEST(f.current_age_minutes - {support}, 0), {max_excess})
          AS excess_minutes,
        f.current_age_minutes > {support} AS is_stale
    FROM fresh f
),
scored AS (
    SELECT d.*,
           (d.probability / NULLIF(1 - d.probability, 0))
             * power({rate}, d.excess_minutes / 60.0) AS decayed_odds
    FROM decayed d
),
valued AS (
    SELECT s.*,
           s.decayed_odds / (1 + s.decayed_odds) AS decayed_probability,
           (s.decayed_odds / (1 + s.decayed_odds))
             * COALESCE(s.expected_margin, 0) AS expected_value
    FROM scored s
)
SELECT v.*,
       ROW_NUMBER() OVER (ORDER BY v.expected_value DESC) AS priority_rank,
       CASE
           WHEN PERCENT_RANK() OVER (ORDER BY v.expected_value) >= {p1} THEN 'P1'
           WHEN PERCENT_RANK() OVER (ORDER BY v.expected_value) >= {p2} THEN 'P2'
           WHEN PERCENT_RANK() OVER (ORDER BY v.expected_value) >= {p3} THEN 'P3'
           ELSE 'P4'
       END AS priority_tier
FROM valued v;
"""


def create_priority_view():
    """Build v_current_priority with the decay constants from config.

    The view is generated rather than hand-written so config.yaml stays the only
    place these numbers live -- no risk of the SQL and the config disagreeing.
    """
    pr = CFG["priority"]
    sql = PRIORITY_VIEW_SQL.format(
        clock=clock_sql(),
        support=pr["decay_support_minutes"],
        horizon=pr["queue_horizon_hours"] * 60,
        max_excess=pr["decay_max_excess_hours"] * 60,
        rate=pr["decay_per_hour"],
        p1=pr["tiers"]["P1"] / 100,
        p2=pr["tiers"]["P2"] / 100,
        p3=pr["tiers"]["P3"] / 100,
    )
    with engine.begin() as c:
        c.execute(text(sql))
    log.info("priority view built (clock=%s, support=%smin, decay=%s/h capped at %sh, "
             "queue horizon=%sh)", pr["clock"], pr["decay_support_minutes"],
             pr["decay_per_hour"], pr["decay_max_excess_hours"],
             pr["queue_horizon_hours"])


def query(sql, **params):
    with engine.connect() as c:
        return pd.read_sql_query(text(sql), c, params=params)


def execute(sql, **params):
    """Write in a committed transaction. Returns the first value for
    INSERT ... RETURNING, else the affected row count."""
    with engine.begin() as c:
        r = c.execute(text(sql), params)
        return r.scalar() if r.returns_rows else r.rowcount


def scalar(sql, **params):
    """Read a single value. Read-only — use execute() for writes."""
    with engine.connect() as c:
        return c.execute(text(sql), params).scalar()


# --- the two reads the pipeline needs ------------------------------------- #

def training_data():
    """Deduped leads with a known outcome, old enough for the label to be final."""
    return query(
        """
        SELECT * FROM pe.v_leads_curated
        WHERE completed_purchase IS NOT NULL
          AND created_at < now() - make_interval(days => :maturity)
        ORDER BY created_at
        """,
        maturity=CFG["train"]["label_maturity_days"],
    )


def leads_to_score(lookback_hours):
    """Leads created in the lookback window — what the 5-minute job rescores.

    Falls back to the newest slice of the dataset when nothing is that recent,
    so the job still does real work on this static snapshot.
    """
    df = query(
        """
        SELECT * FROM pe.v_leads_curated
        WHERE created_at >= now() - make_interval(hours => :h)
        """,
        h=lookback_hours,
    )
    if not df.empty:
        return df
    return query(
        """
        SELECT * FROM pe.v_leads_curated
        WHERE created_at >= (SELECT max(created_at) FROM pe.v_leads_curated)
                            - make_interval(hours => :h)
        """,
        h=lookback_hours,
    )
