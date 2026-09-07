"""FastAPI backend for the admin panel. All endpoints under /api."""
import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import db, interpret, predict, train
from .config import CFG

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("api")

app = FastAPI(title="Lead Priority Engine", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=CFG["api"]["cors_origins"],
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    db.wait_ready()
    db.migrate()
    log.info("api ready")


def rows(sql, **params):
    """Query -> JSON-safe dicts. SQL NULL arrives as NaN via pandas, and NaN is
    not valid JSON, so it becomes None here rather than 500-ing the response."""
    df = db.query(sql, **params)
    return df.astype(object).where(df.notna(), None).to_dict("records")


# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "leads": db.scalar("SELECT count(*) FROM pe.leads"),
        "predictions": db.scalar("SELECT count(*) FROM pe.predictions"),
        "active_model": db.scalar(
            "SELECT version FROM pe.model_versions WHERE is_active"),
    }


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
        SELECT version, algorithm, trained_at, train_rows, test_rows,
               base_rate_train, base_rate_test, metrics, candidate_results
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
    """The call list: highest expected value first."""
    where, params = ["1=1"], {"limit": limit, "offset": offset}
    for col, val in (("priority_tier", tier), ("channel", channel),
                     ("product_type", product_type)):
        if val:
            where.append(f"{col} = :{col}")
            params[col] = val
    clause = " AND ".join(where)
    total = db.scalar(f"SELECT count(*) FROM pe.v_current_priority WHERE {clause}",
                      **{k: v for k, v in params.items() if k not in ("limit", "offset")})
    return {
        "total": total,
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
        """, **params),
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
        SELECT version, algorithm, is_active, trained_at, train_rows, test_rows,
               base_rate_train, base_rate_test,
               (metrics->>'pr_auc')::float  AS pr_auc,
               (metrics->>'roc_auc')::float AS roc_auc
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
    return rows("""
        SELECT CASE WHEN current_age_minutes <= 360 THEN 'inside support'
                    ELSE 'past boundary' END                AS regime,
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
    version, pipe, reference = predict.active_bundle()
    df = _lead_frame(lead_id)
    out = interpret.explain(pipe, df, reference, top_n=top_n)
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
    _, pipe, _ = predict.active_bundle()
    try:
        return interpret.sweep(pipe, _lead_frame(lead_id), feature)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


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
def trigger_predict(lookback_hours: int | None = None):
    return predict.run(lookback_hours)

