"""Training job: temporal split, try both algorithms, keep the better one."""
import json
import logging
from datetime import datetime, timezone

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV

from . import features, metrics
from .config import CFG
from .db import execute, training_data

log = logging.getLogger(__name__)


def run():
    cfg = CFG["train"]
    df = training_data()
    if df.empty:
        raise RuntimeError("no training rows in pe.v_leads_curated — load the CSV first")

    # Temporal split. A random split would let the model see the future: the
    # conversion rate falls from ~9.5% (Apr-Jul) to 7.4% (Aug) and stays down.
    cutoff = df["created_at"].max() - np.timedelta64(cfg["holdout_days"], "D")
    train, test = df[df["created_at"] < cutoff], df[df["created_at"] >= cutoff]
    log.info("train=%s (to %s)  holdout=%s (from %s)",
             len(train), cutoff.date(), len(test), cutoff.date())

    X_train, y_train = features.build(train), train["completed_purchase"].to_numpy(int)
    X_test, y_test = features.build(test), test["completed_purchase"].to_numpy(int)
    margin_test = test["expected_margin"].to_numpy(float)

    candidates = {}
    for algo in ("gbdt", "logreg"):
        pipe = features.make_pipeline(algo, cfg["random_state"])
        pipe.fit(X_train, y_train)
        prob = pipe.predict_proba(X_test)[:, 1]
        candidates[algo] = (pipe, metrics.evaluate(y_test, prob, margin_test))
        log.info("%s: pr_auc=%.4f roc_auc=%.4f",
                 algo, candidates[algo][1]["pr_auc"], candidates[algo][1]["roc_auc"])

    # Baselines it has to beat, on the same holdout.
    baselines = {
        "rule_based": metrics.evaluate(
            y_test, features.rule_baseline(test), margin_test),
        "random": metrics.evaluate(
            y_test,
            np.random.default_rng(cfg["random_state"]).random(len(y_test)),
            margin_test),
    }

    best = max(candidates, key=lambda a: candidates[a][1]["pr_auc"])
    pipe, result = candidates[best]
    log.info("selected %s (pr_auc %.4f vs rule-based %.4f)",
             best, result["pr_auc"], baselines["rule_based"]["pr_auc"])

    # class_weight="balanced" is good for ranking but inflates the raw scores,
    # so P(purchase) would be ~3x too high. Isotonic calibration fixes the level
    # without touching the order (AUC/PR-AUC are rank-based, so they don't move;
    # Brier does). Matters because the ranking multiplies probability by margin.
    pipe = CalibratedClassifierCV(pipe, method="isotonic", cv=3)
    pipe.fit(X_train, y_train)
    result = metrics.evaluate(y_test, pipe.predict_proba(X_test)[:, 1], margin_test)
    log.info("after calibration: pr_auc=%.4f brier=%.4f (was %.4f)",
             result["pr_auc"], result["brier"], candidates[best][1]["brier"])

    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = CFG["artifacts_dir"] / f"model_{version}.joblib"
    joblib.dump(pipe, path)

    execute("UPDATE pe.model_versions SET is_active = FALSE WHERE is_active")
    execute(
        """
        INSERT INTO pe.model_versions
          (version, algorithm, is_active, trained_at, train_rows, test_rows,
           train_period_start, train_period_end, test_period_start, test_period_end,
           base_rate_train, base_rate_test, hyperparams, feature_spec, metrics,
           candidate_results, feature_importance, artifact_path)
        VALUES
          (:version, :algorithm, TRUE, now(), :train_rows, :test_rows,
           :tr_start, :tr_end, :te_start, :te_end,
           :br_train, :br_test, CAST(:hyperparams AS jsonb),
           CAST(:feature_spec AS jsonb), CAST(:metrics AS jsonb),
           CAST(:candidates AS jsonb), CAST(:importance AS jsonb), :artifact_path)
        """,
        version=version, algorithm=best,
        train_rows=len(train), test_rows=len(test),
        tr_start=train["created_at"].min(), tr_end=train["created_at"].max(),
        te_start=test["created_at"].min(), te_end=test["created_at"].max(),
        br_train=float(y_train.mean()), br_test=float(y_test.mean()),
        hyperparams=json.dumps(candidates[best][0].named_steps["model"].get_params(), default=str),
        feature_spec=json.dumps({
            "categorical": features.CATEGORICAL,
            "numeric": features.NUMERIC,
            "excluded": ["expected_margin", "price_comparisons_last_7d", "city"],
        }),
        metrics=json.dumps(result),
        candidates=json.dumps(
            [{"algorithm": a, "pr_auc": r["pr_auc"], "roc_auc": r["roc_auc"]}
             for a, (_, r) in candidates.items()]
            + [{"algorithm": f"baseline:{n}", "pr_auc": r["pr_auc"], "roc_auc": r["roc_auc"]}
               for n, r in baselines.items()]),
        importance=json.dumps([]),
        artifact_path=str(path),
    )
    log.info("registered model %s", version)
    return {"version": version, "algorithm": best, "metrics": result,
            "baselines": {k: v["pr_auc"] for k, v in baselines.items()}}
