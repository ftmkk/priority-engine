"""Training job: three-way temporal split, try both algorithms, keep the better one."""
import json
import logging
from datetime import datetime, timezone

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV

from . import features, interpret, metrics, segments
from .config import CFG
from .db import execute, migrate, training_data

log = logging.getLogger(__name__)


def run():
    cfg = CFG["train"]
    migrate()          # idempotent; keeps a long-lived worker on the current schema
    df = training_data()
    if df.empty:
        raise RuntimeError("no training rows in pe.v_leads_curated — load the CSV first")

    # Three-way temporal split. A random split would let the model see the
    # future: the conversion rate falls from ~9.5% (Apr-Jul) to 7.4% (Aug) and
    # stays down.
    #
    # The middle window chooses the algorithm; the newest one is scored once,
    # afterwards, and is the only number worth quoting. Doing both jobs on the
    # same window is selection-on-test — with four candidates and no tuning the
    # bias is small, but nothing about that structure stays true once a
    # hyperparameter or a threshold gets picked, and by then the leak is silent.
    newest = df["created_at"].max()
    cutoff_test = newest - np.timedelta64(cfg["holdout_days"], "D")
    cutoff_valid = cutoff_test - np.timedelta64(cfg["validation_days"], "D")
    train = df[df["created_at"] < cutoff_valid]
    valid = df[(df["created_at"] >= cutoff_valid) & (df["created_at"] < cutoff_test)]
    test = df[df["created_at"] >= cutoff_test]
    if valid.empty or test.empty:
        raise RuntimeError(
            f"validation_days={cfg['validation_days']} + holdout_days="
            f"{cfg['holdout_days']} leave no rows to select or score on")
    log.info("train=%s (to %s)  valid=%s (to %s)  holdout=%s (from %s)",
             len(train), cutoff_valid.date(), len(valid), cutoff_test.date(),
             len(test), cutoff_test.date())

    # Population statistics (price percentile, the medians that fill a gap) are
    # fitted on the training window only and reused for every later frame -- the
    # same rule the serving path follows, so a holdout score is comparable to a
    # served one.
    ref = features.fit_reference(train)
    X_train, y_train = features.build(train, ref), train["completed_purchase"].to_numpy(int)
    X_valid, y_valid = features.build(valid, ref), valid["completed_purchase"].to_numpy(int)
    y_test = test["completed_purchase"].to_numpy(int)
    margin_valid = valid["expected_margin"].to_numpy(float)
    margin_test = test["expected_margin"].to_numpy(float)
    # X_test is built after the refit below, against the population the final
    # model was actually fitted on.

    # Selection round: fitted on train only, scored on validation only. Nothing
    # here ever touches the holdout.
    candidates = {}
    for algo in cfg["candidates"]:
        pipe = features.make_pipeline(algo, cfg["random_state"])
        pipe.fit(X_train, y_train)
        prob = pipe.predict_proba(X_valid)[:, 1]
        candidates[algo] = (pipe, metrics.evaluate(y_valid, prob, margin_valid))
        log.info("%s on validation: pr_auc=%.4f roc_auc=%.4f",
                 algo, candidates[algo][1]["pr_auc"], candidates[algo][1]["roc_auc"])

    # Baselines it has to beat. Judged on validation like every other candidate;
    # recomputed on the holdout further down, where the honest gap is reported.
    rng = np.random.default_rng(cfg["random_state"])
    baselines = {
        "rule_based": metrics.evaluate(
            y_valid, features.rule_baseline(valid), margin_valid),
        "random": metrics.evaluate(y_valid, rng.random(len(y_valid)), margin_valid),
    }

    best = max(candidates, key=lambda a: candidates[a][1]["pr_auc"])
    selection = candidates[best][1]
    log.info("selected %s on validation (pr_auc %.4f vs rule-based %.4f)",
             best, selection["pr_auc"], baselines["rule_based"]["pr_auc"])

    # The algorithm is now fixed, so the validation window is no longer needed
    # to keep honest and is worth more as training data — it is the most recent
    # period available, and notebook 02 shows how much the recent regime differs.
    # Refit from scratch on train+validation, then score the holdout once.
    fit_rows = df[df["created_at"] < cutoff_test]
    ref = features.fit_reference(fit_rows)
    X_fit = features.build(fit_rows, ref)
    X_test = features.build(test, ref)
    y_fit = fit_rows["completed_purchase"].to_numpy(int)

    # class_weight="balanced" is good for ranking but inflates the raw scores,
    # so P(purchase) would be ~3x too high. Isotonic calibration fixes the level
    # without touching the order (AUC/PR-AUC are rank-based, so they don't move;
    # Brier does). Matters because the ranking multiplies probability by margin.
    # cv=3 refits the base pipeline internally, so it is passed unfitted.
    pipe = CalibratedClassifierCV(
        features.make_pipeline(best, cfg["random_state"]), method="isotonic", cv=3)
    pipe.fit(X_fit, y_fit)

    # First and only look at the holdout.
    result = metrics.evaluate(y_test, pipe.predict_proba(X_test)[:, 1], margin_test)
    holdout_baselines = {
        "rule_based": metrics.evaluate(
            y_test, features.rule_baseline(test), margin_test),
        "random": metrics.evaluate(y_test, rng.random(len(y_test)), margin_test),
    }
    log.info("holdout: pr_auc=%.4f roc_auc=%.4f brier=%.4f (rule-based %.4f)",
             result["pr_auc"], result["roc_auc"], result["brier"],
             holdout_baselines["rule_based"]["pr_auc"])

    # Interpretation is produced for whichever model was selected, not just for
    # the linear one — permutation importance is model-agnostic, and the linear
    # equation is included only when there actually is one.
    importance = interpret.global_importance(pipe, X_test, y_test)
    equation = interpret.linear_terms(pipe)
    reference = interpret.reference_row(X_fit)
    log.info("top features: %s",
             ", ".join(f"{d['feature']}({d['importance']:.4f})" for d in importance[:4]))

    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = CFG["artifacts_dir"] / f"model_{version}.joblib"
    # the reference row travels with the model so explanations stay reproducible
    joblib.dump({"pipeline": pipe, "reference": reference, "feature_ref": ref,
                 "algorithm": best, "version": version}, path)

    execute("UPDATE pe.model_versions SET is_active = FALSE WHERE is_active")
    execute(
        """
        INSERT INTO pe.model_versions
          (version, algorithm, is_active, trained_at, train_rows, valid_rows, test_rows,
           train_period_start, train_period_end, valid_period_start, valid_period_end,
           test_period_start, test_period_end,
           base_rate_train, base_rate_valid, base_rate_test, hyperparams, feature_spec,
           metrics, selection_metrics, candidate_results, feature_importance,
           artifact_path)
        VALUES
          (:version, :algorithm, TRUE, now(), :train_rows, :valid_rows, :test_rows,
           :tr_start, :tr_end, :va_start, :va_end, :te_start, :te_end,
           :br_train, :br_valid, :br_test, CAST(:hyperparams AS jsonb),
           CAST(:feature_spec AS jsonb), CAST(:metrics AS jsonb),
           CAST(:selection AS jsonb), CAST(:candidates AS jsonb),
           CAST(:importance AS jsonb), :artifact_path)
        """,
        version=version, algorithm=best,
        train_rows=len(train), valid_rows=len(valid), test_rows=len(test),
        tr_start=train["created_at"].min(), tr_end=train["created_at"].max(),
        va_start=valid["created_at"].min(), va_end=valid["created_at"].max(),
        te_start=test["created_at"].min(), te_end=test["created_at"].max(),
        br_train=float(y_train.mean()), br_valid=float(y_valid.mean()),
        br_test=float(y_test.mean()),
        hyperparams=json.dumps(candidates[best][0].named_steps["model"].get_params(), default=str),
        feature_spec=json.dumps({
            "categorical": features.CATEGORICAL,
            "numeric": features.NUMERIC,
            "excluded": ["expected_margin", "price_comparisons_last_7d", "city"],
        }),
        metrics=json.dumps(result),
        selection=json.dumps(selection),
        # each row says which window it was scored on: the algorithm comparison
        # happened on validation, the baselines are also recomputed on the
        # holdout so the gap that gets quoted is a like-for-like one.
        candidates=json.dumps(
            [{"algorithm": a, "scored_on": "validation",
              "pr_auc": r["pr_auc"], "roc_auc": r["roc_auc"]}
             for a, (_, r) in candidates.items()]
            + [{"algorithm": f"baseline:{n}", "scored_on": "validation",
                "pr_auc": r["pr_auc"], "roc_auc": r["roc_auc"]}
               for n, r in baselines.items()]
            + [{"algorithm": f"baseline:{n}", "scored_on": "holdout",
                "pr_auc": r["pr_auc"], "roc_auc": r["roc_auc"]}
               for n, r in holdout_baselines.items()]),
        importance=json.dumps({"permutation": importance, "equation": equation}),
        # Filename only. The registry is shared between the host and the
        # containers while the artifacts directory is not, so an absolute path
        # here resolves in exactly one of them; every reader joins this onto its
        # own `artifacts_dir` instead.
        artifact_path=path.name,
    )
    log.info("registered model %s", version)

    # Segmentation belongs to a model version so old assignments stay readable
    # after a retrain. It answers a different question from the ranking, so a
    # failure here must not lose a model that trained fine.
    try:
        seg = segments.fit(version, cfg["random_state"])
    except Exception:
        log.exception("segmentation failed; the model is still registered")
        seg = None

    return {"version": version, "algorithm": best, "metrics": result, "segments": seg,
            "selection": {"scored_on": "validation", "pr_auc": selection["pr_auc"],
                          "baselines": {k: v["pr_auc"] for k, v in baselines.items()}},
            "baselines": {k: v["pr_auc"] for k, v in holdout_baselines.items()},
            "top_features": [d["feature"] for d in importance[:5]]}
