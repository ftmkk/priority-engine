"""FastAPI backend for the admin panel. All endpoints under /api."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import db, interpret, predict, segments, train
from .config import CFG

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


def rows(sql, **params):
    """Query -> JSON-safe dicts. SQL NULL arrives as NaN via pandas, and NaN is
    not valid JSON, so it becomes None here rather than 500-ing the response."""
    df = db.query(sql, **params)
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
        "leads": db.scalar("SELECT count(*) FROM pe.leads"),
        "predictions": db.scalar("SELECT count(*) FROM pe.predictions"),
        "active_model": db.scalar(
            "SELECT version FROM pe.model_versions WHERE is_active"),
        "clock": clock_state(),
    }


@app.get("/api/clock")
def clock():
    return clock_state()


@app.get("/api/summary")
def summary():
    """Dashboard KPIs."""
    kpi = rows("""
        SELECT count(*)                              AS leads,
               avg(completed_purchase)::float        AS conversion,
               sum(completed_purchase)              AS converters,
               sum(CASE WHEN completed_purchase = 1 THEN expected_margin END) AS margin_won
        FROM pe.v_leads_curated WHERE completed_purchase IS NOT NULL
    """)[0]
    queue = rows("""
        SELECT priority_tier, count(*) AS leads,
               avg(probability)::float  AS avg_probability,
               sum(expected_value)      AS expected_value
        FROM pe.v_current_priority GROUP BY priority_tier ORDER BY priority_tier
    """)
    model = rows("""
        SELECT version, algorithm, trained_at, train_rows, valid_rows, test_rows,
               base_rate_train, base_rate_valid, base_rate_test,
               metrics, selection_metrics, candidate_results
        FROM pe.model_versions WHERE is_active
    """)
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

    Column names are literals from the dict below and values are bound, so the
    interpolated clause carries nothing a caller supplied.
    """
    given = {k: v for k, v in (("priority_tier", tier), ("channel", channel),
                               ("product_type", product_type)) if v}
    clause = " AND ".join(f"{k} = :{k}" for k in given) or "TRUE"
    return {
        "total": db.scalar(
            f"SELECT count(*) FROM pe.v_current_priority WHERE {clause}", **given),
        "items": rows(f"""
            SELECT lead_id, probability, decayed_probability, score, expected_value,
                   priority_tier, priority_rank, is_stale, current_age_minutes, excess_minutes,
                   predicted_at, model_version,
                   product_type, channel, payment_type, insurance_company,
                   price, expected_margin, days_to_policy_expiry,
                   minutes_since_abandonment, offer_views_last_7d,
                   visited_offer_page, has_previous_purchase, completed_purchase
            FROM pe.v_current_priority WHERE {clause}
            ORDER BY expected_value DESC LIMIT :limit OFFSET :offset
        """, limit=limit, offset=offset, **given),
    }


@app.get("/api/model")
def model_detail():
    m = rows("SELECT * FROM pe.model_versions WHERE is_active")
    if not m:
        raise HTTPException(404, "no active model — the training job hasn't run yet")
    return m[0]


@app.get("/api/model/versions")
def model_versions():
    return rows("""
        SELECT version, algorithm, is_active, trained_at, train_rows, valid_rows,
               test_rows, base_rate_train, base_rate_valid, base_rate_test,
               -- `metrics` is the holdout; selection_metrics is the validation
               -- window the algorithm was actually picked on.
               (metrics->>'pr_auc')::float  AS pr_auc,
               (metrics->>'roc_auc')::float AS roc_auc,
               (selection_metrics->>'pr_auc')::float AS selection_pr_auc
        FROM pe.model_versions ORDER BY trained_at DESC
    """)


# --- analytics behind the dashboards --------------------------------------- #
@app.get("/api/analytics/conversion-by/{dimension}")
def conversion_by(dimension: str):
    allowed = {"channel", "payment_type", "insurance_company", "product_type",
               "device", "partner", "city"}
    if dimension not in allowed:
        raise HTTPException(400, f"dimension must be one of {sorted(allowed)}")
    return rows(f"""
        SELECT {dimension} AS label, count(*) AS leads,
               avg(completed_purchase)::float AS conversion
        FROM pe.v_leads_curated WHERE completed_purchase IS NOT NULL
        GROUP BY {dimension} HAVING count(*) >= 40
        ORDER BY conversion DESC
    """)


@app.get("/api/analytics/urgency")
def urgency():
    """The two clocks that pull in opposite directions."""
    return {
        "abandonment": rows("""
            SELECT width_bucket(minutes_since_abandonment, 0, 360, 9) * 40 - 40 AS bucket,
                   count(*) AS leads, avg(completed_purchase)::float AS conversion
            FROM pe.v_leads_curated WHERE completed_purchase IS NOT NULL
            GROUP BY bucket ORDER BY bucket
        """),
        "expiry": rows("""
            SELECT CASE WHEN days_to_policy_expiry < 0 THEN 'expired'
                        WHEN days_to_policy_expiry < 4 THEN '0-3'
                        WHEN days_to_policy_expiry < 8 THEN '4-7'
                        WHEN days_to_policy_expiry < 14 THEN '8-13'
                        WHEN days_to_policy_expiry < 20 THEN '14-19'
                        WHEN days_to_policy_expiry < 28 THEN '20-27'
                        ELSE '28+' END AS bucket,
                   min(days_to_policy_expiry) AS sort_key,
                   count(*) AS leads, avg(completed_purchase)::float AS conversion
            FROM pe.v_leads_curated WHERE completed_purchase IS NOT NULL
            GROUP BY bucket ORDER BY sort_key
        """),
    }


@app.get("/api/analytics/engagement")
def engagement():
    return {
        col: rows(f"""
            SELECT least({col}, 6) AS bucket, count(*) AS leads,
                   avg(completed_purchase)::float AS conversion
            FROM pe.v_leads_curated WHERE completed_purchase IS NOT NULL
            GROUP BY bucket HAVING count(*) >= 100 ORDER BY bucket
        """)
        for col in ("offer_views_last_7d", "sessions_last_7d")
    }


@app.get("/api/analytics/weekly")
def weekly():
    return rows("""
        SELECT date_trunc('week', created_at)::date AS week, count(*) AS leads,
               avg(completed_purchase)::float AS conversion
        FROM pe.v_leads_curated WHERE completed_purchase IS NOT NULL
        GROUP BY week HAVING count(*) > 300 ORDER BY week
    """)


@app.get("/api/analytics/target-balance")
def target_balance():
    return rows("""
        SELECT completed_purchase AS outcome, count(*) AS leads
        FROM pe.v_leads_curated WHERE completed_purchase IS NOT NULL
        GROUP BY completed_purchase ORDER BY completed_purchase
    """)


@app.get("/api/analytics/calibration")
def calibration():
    """Predicted vs observed on the held-out period.

    Read from the model registry, not from the served scores: the scoring job
    advances a lead's clock before asking the model, so a served score answers
    "what now?" while the recorded outcome answers "what happened at the original
    age". Comparing those two would look like a 3x miscalibration that isn't one.
    """
    m = rows("SELECT metrics FROM pe.model_versions WHERE is_active")
    if not m:
        raise HTTPException(404, "no active model yet")
    return m[0]["metrics"].get("calibration", [])


@app.get("/api/analytics/score-distribution")
def score_distribution():
    return rows("""
        SELECT (width_bucket(probability, 0, 0.6, 30) - 1) * 2 AS score_pct,
               count(*) AS leads,
               sum(completed_purchase) AS converters
        FROM pe.v_latest_prediction
        GROUP BY score_pct ORDER BY score_pct
    """)


@app.get("/api/analytics/decay-impact")
def decay_impact():
    """How much the read-time decay actually moves the queue, by lead age."""
    return rows(f"""
        SELECT CASE WHEN current_age_minutes <= {CFG["priority"]["decay_support_minutes"]}
                    THEN 'inside support' ELSE 'past boundary' END AS regime,
               (floor(current_age_minutes / 240) * 4)::int  AS age_hours,
               count(*)                                     AS leads,
               avg(probability)::float                       AS raw,
               avg(decayed_probability)::float               AS decayed
        FROM pe.v_current_priority
        GROUP BY regime, age_hours ORDER BY age_hours
    """)


@app.get("/api/analytics/queue-composition")
def queue_composition():
    return rows("""
        SELECT priority_tier, product_type, count(*) AS leads,
               sum(expected_value) AS expected_value
        FROM pe.v_current_priority
        GROUP BY priority_tier, product_type ORDER BY priority_tier, product_type
    """)


# --- interpretation --------------------------------------------------------- #
@app.get("/api/interpret/importance")
def importance():
    """What the selected model relies on, and which way each feature pushes."""
    m = rows("SELECT algorithm, feature_importance FROM pe.model_versions WHERE is_active")
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
    df = db.query("SELECT * FROM pe.v_leads_curated WHERE lead_id = :l", l=lead_id)
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
    version = db.scalar("SELECT version FROM pe.model_versions WHERE is_active")
    if not version:
        raise HTTPException(404, "no active model yet")
    return {
        "model_version": version,
        "segments": rows("""
            WITH hist AS (
                SELECT s.segment,
                       count(*)                              AS leads,
                       avg(l.completed_purchase::float)      AS conversion,
                       avg(l.expected_margin)                AS avg_margin
                FROM pe.lead_segments s
                JOIN pe.v_leads_curated l USING (lead_id)
                WHERE s.model_version = :v AND l.completed_purchase IS NOT NULL
                GROUP BY s.segment
            ),
            queued AS (
                SELECT s.segment,
                       count(*)                                           AS in_queue,
                       count(*) FILTER (WHERE q.priority_tier IN ('P1','P2')) AS called,
                       avg(q.decayed_probability)                          AS avg_score,
                       sum(q.expected_value)                               AS queue_value
                FROM pe.lead_segments s
                JOIN pe.v_current_priority q USING (lead_id)
                WHERE s.model_version = :v
                GROUP BY s.segment
            )
            SELECT g.segment, g.label, g.size, g.traits,
                   h.leads, h.conversion::float, h.avg_margin,
                   COALESCE(q.in_queue, 0)  AS in_queue,
                   COALESCE(q.called, 0)    AS called,
                   q.avg_score::float, q.queue_value
            FROM pe.segments g
            LEFT JOIN hist   h USING (segment)
            LEFT JOIN queued q USING (segment)
            WHERE g.model_version = :v
            ORDER BY h.conversion DESC NULLS LAST
        """, v=version),
    }


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
    version = db.scalar("SELECT version FROM pe.model_versions WHERE is_active")
    if not version:
        raise HTTPException(404, "no active model yet")

    queued = rows("""
        SELECT s.lead_id, s.segment, s.x, s.y, l.completed_purchase,
               q.priority_tier, q.decayed_probability::float AS score
        FROM pe.lead_segments s
        JOIN pe.v_leads_curated l USING (lead_id)
        JOIN pe.v_current_priority q USING (lead_id)
        WHERE s.model_version = :v
    """, v=version)

    background = rows("""
        SELECT s.lead_id, s.segment, s.x, s.y, l.completed_purchase,
               NULL::text AS priority_tier, NULL::float AS score
        FROM pe.lead_segments s
        JOIN pe.v_leads_curated l USING (lead_id)
        WHERE s.model_version = :v
          AND NOT EXISTS (SELECT 1 FROM pe.v_current_priority q
                          WHERE q.lead_id = s.lead_id)
        ORDER BY ('x' || substr(md5(s.lead_id), 1, 8))::bit(32)::int
        LIMIT :n
    """, v=version, n=max(limit - len(queued), 0))

    return {"queued": len(queued), "background": len(background),
            "points": queued + background}


@app.post("/api/segments/rebuild")
def rebuild_segments():
    version = db.scalar("SELECT version FROM pe.model_versions WHERE is_active")
    if not version:
        raise HTTPException(404, "no active model yet")
    return segments.fit(version)


# --- operations ------------------------------------------------------------- #
@app.get("/api/jobs")
def jobs(limit: int = Query(25, le=200)):
    return rows("""
        SELECT id, job_name, status, trigger, started_at, finished_at,
               duration_ms, rows_processed, detail, error
        FROM pe.job_runs ORDER BY started_at DESC LIMIT :limit
    """, limit=limit)


@app.get("/api/monitoring")
def monitoring(limit: int = Query(50, le=500)):
    return rows("""
        SELECT captured_at, model_version, scored_leads, mean_probability,
               p10_probability, p90_probability
        FROM pe.monitoring_snapshots ORDER BY captured_at DESC LIMIT :limit
    """, limit=limit)


@app.post("/api/jobs/train")
def trigger_train():
    r = train.run()
    return {k: v for k, v in r.items() if k != "metrics"} | {
        "pr_auc": r["metrics"]["pr_auc"]}


@app.post("/api/jobs/predict")
def trigger_predict(limit: int | None = Query(None, description="cap rows this run")):
    return predict.run(limit)

