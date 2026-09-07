"""Scoring job.

Not a blanket rescore. A lead's stored features never change, so rescoring the
same row with the same clock returns the same number. What does change is the
lead's *age*, and that splits the work in two:

  inside the fitted support (age <= decay_support_minutes)
      The model is valid at these ages, so we ask it: advance the lead's clock
      features to its current age and re-infer. This window is finite per lead
      (6 hours by default), so the job winds itself down.

  past the boundary
      The model has no evidence out here. The last score inside the window is
      kept as an anchor and the read-time decay in v_current_priority takes over.

So the 5-minute cadence exists to walk leads through their support window, and
each lead stops needing it once it leaves.
"""
import logging
from datetime import datetime, timezone

import joblib
import numpy as np

from . import features
from .config import CFG
from .db import clock_sql, engine, query

log = logging.getLogger(__name__)
_cache = {}


def active_model():
    """Load the active model, reusing it until a newer version is registered."""
    row = query("SELECT version, artifact_path FROM pe.model_versions WHERE is_active")
    if row.empty:
        raise RuntimeError("no active model — run `train` first")
    version, path = row.iloc[0]["version"], row.iloc[0]["artifact_path"]
    if _cache.get("version") != version:
        _cache.clear()
        bundle = joblib.load(path)
        _cache.update(version=version, pipe=bundle["pipeline"],
                      reference=bundle["reference"])
        log.info("loaded model %s", version)
    return _cache["version"], _cache["pipe"]


def active_bundle():
    """Model plus the reference row explanations are measured against."""
    version, pipe = active_model()
    return version, pipe, _cache["reference"]


def leads_needing_score(version):
    """Leads whose newest score is stale for their current age.

    `target_age` is the age we want a score for: the lead's age now, capped at
    the support boundary. A lead needs work when it has never been scored under
    this model, or when it has aged past what its last score was computed at.
    Once target_age pins to the boundary, the stored value matches and the lead
    drops out for good.
    """
    support = CFG["priority"]["decay_support_minutes"]
    return query(f"""
        WITH ref AS (SELECT {clock_sql()} AS at)
        SELECT l.*,
               LEAST(
                   l.minutes_since_abandonment
                     + GREATEST(EXTRACT(EPOCH FROM (r.at - l.created_at)) / 60.0, 0),
                   :support
               ) AS target_age
        FROM pe.v_leads_curated l
        CROSS JOIN ref r
        LEFT JOIN LATERAL (
            SELECT p.scored_at_age_minutes
            FROM pe.predictions p
            WHERE p.lead_id = l.lead_id AND p.model_version = :version
            ORDER BY p.predicted_at DESC
            LIMIT 1
        ) last ON TRUE
        WHERE last.scored_at_age_minutes IS NULL
           OR last.scored_at_age_minutes < LEAST(
                  l.minutes_since_abandonment
                    + GREATEST(EXTRACT(EPOCH FROM (r.at - l.created_at)) / 60.0, 0),
                  :support
              ) - 0.5
    """, version=version, support=support)


def advance_clock(df):
    """Move the lead's time-dependent features to `target_age`.

    Both clocks move together: abandonment age goes up, days-to-expiry comes
    down. The expiry effect is tiny over a 6-hour window (its coefficient is
    ~260x smaller per minute) but advancing only one of them would be wrong.
    """
    out = df.copy()
    elapsed_minutes = df["target_age"] - df["minutes_since_abandonment"]
    out["minutes_since_abandonment"] = df["target_age"]
    out["days_to_policy_expiry"] = (
        df["days_to_policy_expiry"].astype(float) - elapsed_minutes / 1440.0
    )
    return out


def run(limit=None):
    version, pipe = active_model()
    df = leads_needing_score(version)
    if limit:
        df = df.nlargest(limit, "target_age")
    if df.empty:
        # Nothing new to score, but the queue's score distribution is still worth
        # recording -- that is what drift monitoring watches, and it moves as
        # leads age out even when no inference runs.
        log.info("every lead is current under %s", version)
        _snapshot(version)
        return {"scored": 0, "model_version": version}

    prob = pipe.predict_proba(features.build(advance_clock(df)))[:, 1]
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    out = df[["lead_id"]].copy()
    out["model_version"] = version
    out["probability"] = prob
    out["score"] = np.round(prob * 1000).astype(int)
    out["scored_at_age_minutes"] = df["target_age"].to_numpy()
    out["lead_created_at"] = df["created_at"].to_numpy()
    out["predicted_at"] = datetime.now(timezone.utc)
    out["batch_id"] = batch_id
    out.to_sql("predictions", engine, schema="pe", if_exists="append", index=False,
               chunksize=1000, method="multi")

    support = CFG["priority"]["decay_support_minutes"]
    in_window = int((df["target_age"] < support - 0.5).sum())
    _snapshot(version, len(out))
    log.info("scored %s leads with %s (%s still inside the %smin support window)",
             len(out), version, in_window, support)
    return {"scored": len(out), "model_version": version, "batch_id": batch_id,
            "in_support_window": in_window}


def _snapshot(version, newly_scored=0):
    """Record the live queue's score distribution.

    Taken from the queue rather than from whatever was just scored, so it tracks
    what the sales floor is actually being handed. The base rate is not
    stationary in this data (9.5% -> 7.4%), so this is measured every run rather
    than assumed away.
    """
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO pe.monitoring_snapshots
              (captured_at, model_version, scored_leads, mean_probability,
               p10_probability, p90_probability, observed_base_rate,
               expected_base_rate, detail)
            SELECT now(), :v, count(*),
                   avg(decayed_probability),
                   percentile_cont(0.1) WITHIN GROUP (ORDER BY decayed_probability),
                   percentile_cont(0.9) WITHIN GROUP (ORDER BY decayed_probability),
                   avg(completed_purchase::float),
                   avg(probability),
                   jsonb_build_object('newly_scored', :n,
                                      'stale', count(*) FILTER (WHERE is_stale))
            FROM pe.v_current_priority
        """), {"v": version, "n": newly_scored})
