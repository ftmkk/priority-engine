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
from pathlib import Path

import joblib
import numpy as np
from sqlalchemy import Float, cast, func, insert, literal, select, true

from . import features, views
from .config import CFG
from .db import clock_expr, engine, query
from .models import ModelVersion, MonitoringSnapshot, Prediction

log = logging.getLogger(__name__)
_cache = {}


def _artifact_path(stored):
    """Resolve a registry entry against *this* process's artifacts directory.

    New rows store a bare filename. Older ones stored an absolute path, which
    resolved on the machine that trained and nowhere else — a host-side `train`
    then 500'd every `/interpret/*` call in the container while every DB-backed
    page kept working. Either form is accepted; the local directory wins, and
    the stored value is the fallback so a genuinely missing artifact still
    reports the path it was registered under.
    """
    local = CFG["artifacts_dir"] / Path(stored).name
    if local.exists():
        return local
    if Path(stored).exists():
        return Path(stored)
    raise FileNotFoundError(
        f"model artifact {Path(stored).name!r} is registered but not in "
        f"{CFG['artifacts_dir']} — it was trained somewhere else (host vs "
        f"container have separate artifact stores); retrain here or copy it over")


def active_model():
    """Load the active model, reusing it until a newer version is registered."""
    row = query(select(ModelVersion.version, ModelVersion.artifact_path)
                .where(ModelVersion.is_active))
    if row.empty:
        raise RuntimeError("no active model — run `train` first")
    version, path = row.iloc[0]["version"], _artifact_path(row.iloc[0]["artifact_path"])
    if _cache.get("version") != version:
        _cache.clear()
        _cache.update(version=version, bundle=joblib.load(path))
        log.info("loaded model %s", version)
    return _cache["version"], _cache["bundle"]["pipeline"]


def active_bundle():
    """Version, pipeline, and the artifact it came out of.

    The bundle carries the population statistics `features.build` needs and the
    reference row explanations are measured against — both fitted at training
    time, so serving cannot drift away from them.
    """
    version, pipe = active_model()
    return version, pipe, _cache["bundle"]


def leads_needing_score(version):
    """Leads whose newest score is stale for their current age.

    `target_age` is the age we want a score for: the lead's age now, capped at
    the support boundary. A lead needs work when it has never been scored under
    this model, or when it has aged past what its last score was computed at.
    Once target_age pins to the boundary, the stored value matches and the lead
    drops out for good.

    The horizon filter is what keeps this cheap. A lead written more than
    `queue_horizon_hours` ago is already past the horizon -- its age only grows
    -- so it can never appear in the queue again and there is nothing to score.
    Without that line every run walked all 50k curated leads and did one indexed
    lookup per lead, every five minutes, to re-learn that 49.7k of them were
    finished; the index on pe.predictions had taken 36 million scans by the time
    it was noticed.
    """
    pr = CFG["priority"]
    vc = views.v_leads_curated

    ref = select(clock_expr().label("at")).cte("ref")
    target_age = func.least(
        vc.c.minutes_since_abandonment
        + func.greatest(func.extract("epoch", ref.c.at - vc.c.created_at) / 60.0, 0),
        pr["decay_support_minutes"],
    )

    # The newest prediction per lead under this model version -- the Core
    # equivalent of the original's `LEFT JOIN LATERAL ... ORDER BY predicted_at
    # DESC LIMIT 1`, expressed as a ranked subquery instead.
    ranked = (
        select(
            Prediction.lead_id,
            Prediction.scored_at_age_minutes,
            func.row_number().over(
                partition_by=Prediction.lead_id,
                order_by=Prediction.predicted_at.desc(),
            ).label("rn"),
        )
        .where(Prediction.model_version == version)
        .subquery()
    )
    last = (
        select(ranked.c.lead_id, ranked.c.scored_at_age_minutes)
        .where(ranked.c.rn == 1)
        .subquery("last")
    )

    stmt = (
        select(vc, target_age.label("target_age"))
        .select_from(
            vc.join(ref, true()).outerjoin(last, last.c.lead_id == vc.c.lead_id)
        )
        .where(vc.c.created_at >= ref.c.at
               - func.make_interval(0, 0, 0, 0, pr["queue_horizon_hours"]))
        .where(
            last.c.scored_at_age_minutes.is_(None)
            | (last.c.scored_at_age_minutes < target_age - 0.5)
        )
    )
    return query(stmt)


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

    prob = pipe.predict_proba(
        features.build(advance_clock(df), _cache["bundle"].get("feature_ref")))[:, 1]
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
    qp = views.v_current_priority
    stmt = insert(MonitoringSnapshot).from_select(
        ["captured_at", "model_version", "scored_leads", "mean_probability",
         "p10_probability", "p90_probability", "observed_base_rate",
         "expected_base_rate", "detail"],
        select(
            func.now(),
            literal(version),
            func.count(),
            func.avg(qp.c.decayed_probability),
            func.percentile_cont(0.1).within_group(qp.c.decayed_probability),
            func.percentile_cont(0.9).within_group(qp.c.decayed_probability),
            func.avg(cast(qp.c.completed_purchase, Float)),
            func.avg(qp.c.probability),
            func.jsonb_build_object(
                "newly_scored", newly_scored,
                "stale", func.count().filter(qp.c.is_stale),
            ),
        ).select_from(qp),
    )
    with engine.begin() as c:
        c.execute(stmt)
