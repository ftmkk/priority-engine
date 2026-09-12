"""FastAPI backend for the admin panel. All endpoints under /api."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Date, Float, Integer, case, cast, func, literal, literal_column, select
from sqlalchemy.dialects.postgresql import BIT

from . import db, interpret, predict, segments, train, views
from .config import CFG
from .models import JobRun, Lead, ModelVersion, MonitoringSnapshot, Prediction, Segment, LeadSegment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(_):
    db.wait_ready()
    db.migrate()
    log.info("api ready")
    yield


app = FastAPI(title="Lead Priority Engine", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=CFG["api"]["cors_origins"],
    allow_methods=["*"], allow_headers=["*"],
)


def rows(stmt, **params):
    """Query -> JSON-safe dicts. SQL NULL arrives as NaN via pandas, and NaN is
    not valid JSON, so it becomes None here rather than 500-ing the response."""
    df = db.query(stmt, **params)
    return df.astype(object).where(df.notna(), None).to_dict("records")


# --------------------------------------------------------------------------- #
def clock_state():
    """What "now" currently means, so the UI can say it rather than imply it.

    `mode` is dataset / fixed / wall and `pinned` is true for the first two: on
    a historical export the queue is read at a frozen instant, and a dashboard
    that hides that just looks out of date.
    """
    mode = db.clock_mode()
    return {
        "mode": mode,
        "pinned": mode != "wall",
        "at": db.clock_now().isoformat(),
        "horizon_hours": CFG["priority"]["queue_horizon_hours"],
        "support_minutes": CFG["priority"]["decay_support_minutes"],
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "leads": db.scalar(select(func.count()).select_from(Lead)),
        "predictions": db.scalar(select(func.count()).select_from(Prediction)),
        "active_model": db.scalar(
            select(ModelVersion.version).where(ModelVersion.is_active)),
        "clock": clock_state(),
    }


@app.get("/api/clock")
def clock():
    return clock_state()


@app.get("/api/summary")
def summary():
    """Dashboard KPIs."""
    vc = views.v_leads_curated
    qp = views.v_current_priority
    kpi = rows(
        select(
            func.count().label("leads"),
            cast(func.avg(vc.c.completed_purchase), Float).label("conversion"),
            func.sum(vc.c.completed_purchase).label("converters"),
            func.sum(case((vc.c.completed_purchase == 1, vc.c.expected_margin))).label("margin_won"),
        ).where(vc.c.completed_purchase.isnot(None))
    )[0]
    queue = rows(
        select(
            qp.c.priority_tier,
            func.count().label("leads"),
            cast(func.avg(qp.c.probability), Float).label("avg_probability"),
            func.sum(qp.c.expected_value).label("expected_value"),
        ).group_by(qp.c.priority_tier).order_by(qp.c.priority_tier)
    )
    model = rows(
        select(ModelVersion.version, ModelVersion.algorithm, ModelVersion.trained_at,
               ModelVersion.train_rows, ModelVersion.valid_rows, ModelVersion.test_rows,
               ModelVersion.base_rate_train, ModelVersion.base_rate_valid,
               ModelVersion.base_rate_test, ModelVersion.metrics,
               ModelVersion.selection_metrics, ModelVersion.candidate_results)
        .where(ModelVersion.is_active)
    )
    return {"kpi": kpi, "queue_by_tier": queue, "model": model[0] if model else None}


@app.get("/api/queue")
def queue(
    tier: str | None = None,
    channel: str | None = None,
    product_type: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    """The call list: highest expected value first.

    Filters are only ever applied against a fixed, known set of columns (never a
    caller-supplied name), and every value is a bound parameter -- built with
    Core's `==`, nothing is string-interpolated.
    """
    qp = views.v_current_priority
    given = {k: v for k, v in (("priority_tier", tier), ("channel", channel),
                               ("product_type", product_type)) if v}

    def _filtered(stmt):
        for col, val in given.items():
            stmt = stmt.where(qp.c[col] == val)
        return stmt

    return {
        "total": db.scalar(_filtered(select(func.count()).select_from(qp))),
        "items": rows(_filtered(
            select(qp.c.lead_id, qp.c.probability, qp.c.decayed_probability, qp.c.score,
                   qp.c.expected_value, qp.c.priority_tier, qp.c.priority_rank,
                   qp.c.is_stale, qp.c.current_age_minutes, qp.c.excess_minutes,
                   qp.c.predicted_at, qp.c.model_version, qp.c.product_type, qp.c.channel,
                   qp.c.payment_type, qp.c.insurance_company, qp.c.price,
                   qp.c.expected_margin, qp.c.days_to_policy_expiry,
                   qp.c.minutes_since_abandonment, qp.c.offer_views_last_7d,
                   qp.c.visited_offer_page, qp.c.has_previous_purchase,
                   qp.c.completed_purchase)
        ).order_by(qp.c.expected_value.desc()).limit(limit).offset(offset)),
    }


@app.get("/api/model")
def model_detail():
    m = rows(select(ModelVersion).where(ModelVersion.is_active))
    if not m:
        raise HTTPException(404, "no active model — the training job hasn't run yet")
    return m[0]


@app.get("/api/model/versions")
def model_versions():
    mv = ModelVersion
    return rows(
        select(
            mv.version, mv.algorithm, mv.is_active, mv.trained_at, mv.train_rows,
            mv.valid_rows, mv.test_rows, mv.base_rate_train, mv.base_rate_valid,
            mv.base_rate_test,
            # `metrics` is the holdout; selection_metrics is the validation
            # window the algorithm was actually picked on.
            cast(mv.metrics["pr_auc"].astext, Float).label("pr_auc"),
            cast(mv.metrics["roc_auc"].astext, Float).label("roc_auc"),
            cast(mv.selection_metrics["pr_auc"].astext, Float).label("selection_pr_auc"),
        ).order_by(mv.trained_at.desc())
    )


# --- analytics behind the dashboards --------------------------------------- #
@app.get("/api/analytics/conversion-by/{dimension}")
def conversion_by(dimension: str):
    allowed = {"channel", "payment_type", "insurance_company", "product_type",
               "device", "partner", "city"}
    if dimension not in allowed:
        raise HTTPException(400, f"dimension must be one of {sorted(allowed)}")
    vc = views.v_leads_curated
    col = vc.c[dimension]
    conversion = cast(func.avg(vc.c.completed_purchase), Float)
    return rows(
        select(col.label("label"), func.count().label("leads"),
               conversion.label("conversion"))
        .where(vc.c.completed_purchase.isnot(None))
        .group_by(col).having(func.count() >= 40)
        .order_by(conversion.desc())
    )


@app.get("/api/analytics/urgency")
def urgency():
    """The two clocks that pull in opposite directions."""
    vc = views.v_leads_curated
    conversion = cast(func.avg(vc.c.completed_purchase), Float)
    curated = vc.c.completed_purchase.isnot(None)

    bucket = func.width_bucket(vc.c.minutes_since_abandonment, 0, 360, 9) * 40 - 40
    expiry_bucket = case(
        (vc.c.days_to_policy_expiry < 0, "expired"),
        (vc.c.days_to_policy_expiry < 4, "0-3"),
        (vc.c.days_to_policy_expiry < 8, "4-7"),
        (vc.c.days_to_policy_expiry < 14, "8-13"),
        (vc.c.days_to_policy_expiry < 20, "14-19"),
        (vc.c.days_to_policy_expiry < 28, "20-27"),
        else_="28+",
    )
    return {
        "abandonment": rows(
            select(bucket.label("bucket"), func.count().label("leads"),
                   conversion.label("conversion"))
            .where(curated).group_by(bucket).order_by(bucket)
        ),
        "expiry": rows(
            select(expiry_bucket.label("bucket"),
                   func.min(vc.c.days_to_policy_expiry).label("sort_key"),
                   func.count().label("leads"), conversion.label("conversion"))
            .where(curated).group_by(expiry_bucket)
            .order_by(func.min(vc.c.days_to_policy_expiry))
        ),
    }


@app.get("/api/analytics/engagement")
def engagement():
    vc = views.v_leads_curated
    conversion = cast(func.avg(vc.c.completed_purchase), Float)
    return {
        col: rows(
            select(func.least(vc.c[col], 6).label("bucket"), func.count().label("leads"),
                   conversion.label("conversion"))
            .where(vc.c.completed_purchase.isnot(None))
            .group_by(func.least(vc.c[col], 6)).having(func.count() >= 100)
            .order_by(func.least(vc.c[col], 6))
        )
        for col in ("offer_views_last_7d", "sessions_last_7d")
    }


@app.get("/api/analytics/weekly")
def weekly():
    vc = views.v_leads_curated
    week = cast(func.date_trunc("week", vc.c.created_at), Date)
    return rows(
        select(week.label("week"), func.count().label("leads"),
               cast(func.avg(vc.c.completed_purchase), Float).label("conversion"))
        .where(vc.c.completed_purchase.isnot(None))
        .group_by(week).having(func.count() > 300).order_by(week)
    )


@app.get("/api/analytics/target-balance")
def target_balance():
    vc = views.v_leads_curated
    return rows(
        select(vc.c.completed_purchase.label("outcome"), func.count().label("leads"))
        .where(vc.c.completed_purchase.isnot(None))
        .group_by(vc.c.completed_purchase).order_by(vc.c.completed_purchase)
    )


@app.get("/api/analytics/calibration")
def calibration():
    """Predicted vs observed on the held-out period.

    Read from the model registry, not from the served scores: the scoring job
    advances a lead's clock before asking the model, so a served score answers
    "what now?" while the recorded outcome answers "what happened at the original
    age". Comparing those two would look like a 3x miscalibration that isn't one.
    """
    m = rows(select(ModelVersion.metrics).where(ModelVersion.is_active))
    if not m:
        raise HTTPException(404, "no active model yet")
    return m[0]["metrics"].get("calibration", [])


@app.get("/api/analytics/score-distribution")
def score_distribution():
    vp = views.v_latest_prediction
    score_pct = (func.width_bucket(vp.c.probability, 0, 0.6, 30) - 1) * 2
    return rows(
        select(score_pct.label("score_pct"), func.count().label("leads"),
               func.sum(vp.c.completed_purchase).label("converters"))
        .group_by(score_pct).order_by(score_pct)
    )


@app.get("/api/analytics/decay-impact")
def decay_impact():
    """How much the read-time decay actually moves the queue, by lead age."""
    qp = views.v_current_priority
    regime = case(
        (qp.c.current_age_minutes <= CFG["priority"]["decay_support_minutes"],
         "inside support"),
        else_="past boundary",
    )
    age_hours = cast(func.floor(qp.c.current_age_minutes / 240) * 4, Integer)
    return rows(
        select(regime.label("regime"), age_hours.label("age_hours"),
               func.count().label("leads"),
               cast(func.avg(qp.c.probability), Float).label("raw"),
               cast(func.avg(qp.c.decayed_probability), Float).label("decayed"))
        .group_by(regime, age_hours).order_by(age_hours)
    )


@app.get("/api/analytics/queue-composition")
def queue_composition():
    qp = views.v_current_priority
    return rows(
        select(qp.c.priority_tier, qp.c.product_type, func.count().label("leads"),
               func.sum(qp.c.expected_value).label("expected_value"))
        .group_by(qp.c.priority_tier, qp.c.product_type)
        .order_by(qp.c.priority_tier, qp.c.product_type)
    )


# --- interpretation --------------------------------------------------------- #
@app.get("/api/interpret/importance")
def importance():
    """What the selected model relies on, and which way each feature pushes."""
    m = rows(select(ModelVersion.algorithm, ModelVersion.feature_importance)
             .where(ModelVersion.is_active))
    if not m:
        raise HTTPException(404, "no active model yet")
    fi = m[0]["feature_importance"] or {}
    return {"algorithm": m[0]["algorithm"],
            "permutation": fi.get("permutation", []),
            "equation": fi.get("equation")}


@app.get("/api/interpret/features")
def sweepable_features():
    return interpret.sweepable()


def _lead_frame(lead_id):
    vc = views.v_leads_curated
    df = db.query(select(vc).where(vc.c.lead_id == lead_id))
    if df.empty:
        raise HTTPException(404, f"no lead {lead_id}")
    return df


@app.get("/api/interpret/explain/{lead_id}")
def explain_lead(lead_id: str, top_n: int = Query(10, le=20)):
    """How this particular lead's score was arrived at, feature by feature."""
    version, pipe, bundle = predict.active_bundle()
    df = _lead_frame(lead_id)
    out = interpret.explain(pipe, df, bundle["reference"],
                            bundle.get("feature_ref"), top_n=top_n)
    out["lead_id"] = lead_id
    out["model_version"] = version
    out["lead"] = {k: interpret.to_native(v) for k, v in
                   df.iloc[0][["product_type", "channel", "payment_type",
                               "insurance_company", "minutes_since_abandonment",
                               "days_to_policy_expiry", "offer_views_last_7d",
                               "sessions_last_7d", "visited_offer_page",
                               "has_previous_purchase", "price", "expected_margin"]].items()}
    return out


@app.get("/api/interpret/sweep/{lead_id}")
def sweep_lead(lead_id: str, feature: str):
    """The model's response curve for this lead along one feature."""
    _, pipe, bundle = predict.active_bundle()
    try:
        return interpret.sweep(pipe, _lead_frame(lead_id), feature,
                               bundle.get("feature_ref"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# --- segmentation ----------------------------------------------------------- #
@app.get("/api/segments")
def segment_profiles():
    """Each segment's size, how it converts, and how much of the call queue it wins.

    Conversion is measured over every lead with a known outcome; the call share
    is measured over the current queue, which is the subset actually dialable
    today. They answer different questions and are deliberately kept apart.
    """
    version = db.scalar(select(ModelVersion.version).where(ModelVersion.is_active))
    if not version:
        raise HTTPException(404, "no active model yet")

    ls, vc, qp, seg = LeadSegment, views.v_leads_curated, views.v_current_priority, Segment

    hist = (
        select(
            ls.segment.label("segment"),
            func.count().label("leads"),
            func.avg(cast(vc.c.completed_purchase, Float)).label("conversion"),
            func.avg(vc.c.expected_margin).label("avg_margin"),
        )
        .select_from(ls.__table__.join(vc, ls.lead_id == vc.c.lead_id))
        .where(ls.model_version == version, vc.c.completed_purchase.isnot(None))
        .group_by(ls.segment)
        .cte("hist")
    )
    queued = (
        select(
            ls.segment.label("segment"),
            func.count().label("in_queue"),
            func.count().filter(qp.c.priority_tier.in_(("P1", "P2"))).label("called"),
            func.avg(qp.c.decayed_probability).label("avg_score"),
            func.sum(qp.c.expected_value).label("queue_value"),
        )
        .select_from(ls.__table__.join(qp, ls.lead_id == qp.c.lead_id))
        .where(ls.model_version == version)
        .group_by(ls.segment)
        .cte("queued")
    )
    stmt = (
        select(
            seg.segment, seg.label, seg.size, seg.traits,
            hist.c.leads, cast(hist.c.conversion, Float).label("conversion"),
            hist.c.avg_margin,
            func.coalesce(queued.c.in_queue, 0).label("in_queue"),
            func.coalesce(queued.c.called, 0).label("called"),
            cast(queued.c.avg_score, Float).label("avg_score"),
            queued.c.queue_value,
        )
        .select_from(
            seg.__table__
            .outerjoin(hist, seg.segment == hist.c.segment)
            .outerjoin(queued, seg.segment == queued.c.segment)
        )
        .where(seg.model_version == version)
        .order_by(hist.c.conversion.desc().nulls_last())
    )
    return {"model_version": version, "segments": rows(stmt)}


@app.get("/api/segments/scatter")
def segment_scatter(limit: int = Query(2500, le=6000)):
    """Leads in two dimensions, tagged with who we would call.

    Stratified on purpose: the queue is only a few hundred of fifty thousand
    leads, so a uniform sample would show almost no call decisions at all. Every
    queued lead is included, and the rest of the budget is a deterministic sample
    of the background. That over-represents the queue by design — the response
    says so in `queued`/`background` so the panel can label it.

    The projection is for looking at only. The clustering ran in the full feature
    space, so a group that appears split here is a projection artefact.
    """
    version = db.scalar(select(ModelVersion.version).where(ModelVersion.is_active))
    if not version:
        raise HTTPException(404, "no active model yet")

    ls, vc, qp = LeadSegment, views.v_leads_curated, views.v_current_priority

    queued = rows(
        select(ls.lead_id, ls.segment, ls.x, ls.y, vc.c.completed_purchase,
               qp.c.priority_tier, cast(qp.c.decayed_probability, Float).label("score"))
        .select_from(
            ls.__table__
            .join(vc, ls.lead_id == vc.c.lead_id)
            .join(qp, ls.lead_id == qp.c.lead_id)
        )
        .where(ls.model_version == version)
    )

    not_queued = ~select(literal_column("1")).select_from(qp) \
        .where(qp.c.lead_id == ls.lead_id).exists()
    sort_key = cast(cast(literal("x") + func.substr(func.md5(ls.lead_id), 1, 8),
                         BIT(32)), Integer)
    background = rows(
        select(ls.lead_id, ls.segment, ls.x, ls.y, vc.c.completed_purchase,
               literal_column("NULL::text").label("priority_tier"),
               literal_column("NULL::float").label("score"))
        .select_from(ls.__table__.join(vc, ls.lead_id == vc.c.lead_id))
        .where(ls.model_version == version, not_queued)
        .order_by(sort_key)
        .limit(max(limit - len(queued), 0))
    )

    return {"queued": len(queued), "background": len(background),
            "points": queued + background}


@app.post("/api/segments/rebuild")
def rebuild_segments():
    version = db.scalar(select(ModelVersion.version).where(ModelVersion.is_active))
    if not version:
        raise HTTPException(404, "no active model yet")
    return segments.fit(version)


# --- operations ------------------------------------------------------------- #
@app.get("/api/jobs")
def jobs(limit: int = Query(25, le=200)):
    j = JobRun
    return rows(
        select(j.id, j.job_name, j.status, j.trigger, j.started_at, j.finished_at,
               j.duration_ms, j.rows_processed, j.detail, j.error)
        .order_by(j.started_at.desc()).limit(limit)
    )


@app.get("/api/monitoring")
def monitoring(limit: int = Query(50, le=500)):
    ms = MonitoringSnapshot
    return rows(
        select(ms.captured_at, ms.model_version, ms.scored_leads, ms.mean_probability,
               ms.p10_probability, ms.p90_probability)
        .order_by(ms.captured_at.desc()).limit(limit)
    )


@app.post("/api/jobs/train")
def trigger_train():
    r = train.run()
    return {k: v for k, v in r.items() if k != "metrics"} | {
        "pr_auc": r["metrics"]["pr_auc"]}


@app.post("/api/jobs/predict")
def trigger_predict(limit: int | None = Query(None, description="cap rows this run")):
    return predict.run(limit)

