"""Database access.

Row-level writes go through the ORM (see models.py); the analytical reads --
views, window functions, percentiles -- stay as SQL, where an ORM adds nothing.
"""
import logging
import time
from contextlib import contextmanager

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from .config import CFG, ROOT

log = logging.getLogger(__name__)
engine = create_engine(CFG["db_url"], pool_pre_ping=True, future=True)
Session = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session():
    """ORM session in a committed transaction."""
    with Session.begin() as s:
        yield s


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


# One arbitrary constant, shared by every process that migrates.
MIGRATION_LOCK = 0x9E10_0001


def migrate(attempts=5):
    """Run db/migrations/*.sql, then build the live priority view from config.

    api, worker and bootstrap all call this on start-up, and they start
    together. Two things follow:

    - They must not migrate at once, so the whole thing runs under one advisory
      lock. The second process blocks, then finds every statement idempotent.
    - `CREATE OR REPLACE VIEW` needs an exclusive lock on the view, while the
      worker's first scoring run is reading it. Waiting blindly deadlocked the
      two on start-up (worker holds the read, migration holds the queue). So the
      transaction gives up after 5s and the whole attempt is retried, which
      turns a hard failure into a pause.
    """
    for attempt in range(1, attempts + 1):
        try:
            with engine.begin() as c:
                c.execute(text("SET LOCAL lock_timeout = '5s'"))
                c.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                          {"k": MIGRATION_LOCK})
                for f in sorted((ROOT / "db" / "migrations").glob("*.sql")):
                    c.execute(text(f.read_text()))
                    log.info("applied %s", f.name)
                c.execute(text(_priority_view_sql()))
            _log_view_settings()
            return
        except OperationalError as exc:
            if attempt == attempts:
                raise
            log.warning("migration attempt %s/%s did not get the locks (%s); retrying",
                        attempt, attempts, type(exc.orig).__name__)
            time.sleep(1.5 * attempt)


def _clock_setting():
    """`priority.current_time`, normalised. Blank counts as unset, so the env
    override `PE_PRIORITY__CURRENT_TIME=` means the same as the empty YAML value:
    use the real clock."""
    setting = CFG["priority"].get("current_time")
    if setting is None or not str(setting).strip():
        return None
    setting = str(setting).strip()
    return "dataset" if setting.lower() == "dataset" else setting


def clock_sql():
    """SQL expression for "now", from `priority.current_time`.

    Three settings, because three situations need different answers:

      dataset    the newest created_at in the data. This file is a fixed
                 historical export, so a real clock puts every lead months past
                 its support and the queue comes back empty.
      null       `now()` -- the real wall clock, which is what production runs.
      timestamp  any explicit instant, for replaying a particular moment.

    An explicit value is parsed here and re-emitted in ISO form rather than
    interpolated as typed: this string goes into a CREATE VIEW, so it must not
    be able to carry anything but a timestamp.
    """
    setting = _clock_setting()
    if setting is None:
        return "now()"
    if setting == "dataset":
        return "(SELECT max(created_at) FROM pe.leads)"
    return f"TIMESTAMPTZ '{clock_now().isoformat()}'"


def clock_now():
    """The resolved reference time as a Python timestamp.

    Reads through the same setting as clock_sql(), so the API reports exactly
    the instant the view is built on -- one clock, not two that can disagree.
    """
    setting = _clock_setting()
    if setting is None:
        return pd.Timestamp.now(tz="UTC")
    if setting == "dataset":
        at = scalar("SELECT max(created_at) FROM pe.leads")
        return pd.Timestamp(at) if at is not None else pd.Timestamp.now(tz="UTC")
    at = pd.Timestamp(setting)
    if at.tzinfo is None:                       # bare timestamps are read as UTC
        at = at.tz_localize("UTC")
    return at


def clock_mode():
    """How "now" is being decided, for the dashboard to say so out loud."""
    setting = _clock_setting()
    return "wall" if setting is None else ("dataset" if setting == "dataset" else "fixed")


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


def _priority_view_sql():
    """The view's DDL, with every constant taken from config.

    Generated rather than hand-written so config.yaml stays the only place these
    numbers live -- no risk of the SQL and the config disagreeing.
    """
    pr = CFG["priority"]
    return PRIORITY_VIEW_SQL.format(
        clock=clock_sql(),
        support=pr["decay_support_minutes"],
        horizon=pr["queue_horizon_hours"] * 60,
        max_excess=pr["decay_max_excess_hours"] * 60,
        rate=pr["decay_per_hour"],
        p1=pr["tiers"]["P1"] / 100,
        p2=pr["tiers"]["P2"] / 100,
        p3=pr["tiers"]["P3"] / 100,
    )


def _log_view_settings():
    pr = CFG["priority"]
    log.info("priority view built (clock=%s, support=%smin, decay=%s/h capped at %sh, "
             "queue horizon=%sh)", clock_mode(), pr["decay_support_minutes"],
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


# --- the read the training job needs -------------------------------------- #

def training_data():
    """Deduped leads with a known outcome, old enough for the label to be final.

    Maturity is measured against `ingested_at` -- when the export was taken --
    not against `now()` or the queue's reference clock. A label is settled or not
    depending on how long after the lead the data was pulled, which is a property
    of the file, and the same rule then holds whether the queue is being read at
    a fixed instant or live.
    """
    return query(
        """
        SELECT * FROM pe.v_leads_curated
        WHERE completed_purchase IS NOT NULL
          AND created_at < (SELECT max(ingested_at) FROM pe.leads)
                           - make_interval(days => :maturity)
        ORDER BY created_at
        """,
        maturity=CFG["train"]["label_maturity_days"],
    )
