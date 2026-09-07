"""Model interpretation.

Two questions, two methods — both model-agnostic, so they work whichever
algorithm the training run selected:

  "what does the model rely on?"   permutation importance on the holdout, scored
                                   in PR-AUC. Reads directly as "shuffling this
                                   column costs the model this much ranking".

  "how was THIS lead's score
   computed?"                      one-feature ablation: set the feature to the
                                   population reference (median for numbers, the
                                   most common level for categories), re-score,
                                   and take the shift in log-odds. That shift is
                                   exactly what this lead's own value contributes
                                   relative to an average lead.

The ablation is the honest general answer, not a Shapley value: the parts are not
expected to sum to the whole, so the residual is reported rather than hidden.
That holds even when the underlying model is linear — the isotonic calibration
layer is monotone but not linear, so it does not preserve additivity in log-odds.
Read a contribution as "this feature's own value moves this lead's score by
roughly this much", and read the residual as how much of the gap the one-at-a-time
view cannot account for.
"""
from decimal import Decimal

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from . import features

LOGIT_FLOOR = 1e-9


def logit(p):
    p = np.clip(p, LOGIT_FLOOR, 1 - LOGIT_FLOOR)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def reference_row(X):
    """The 'average lead' every explanation is measured against."""
    ref = {}
    for col in X.columns:
        if col in features.CATEGORICAL:
            ref[col] = X[col].mode().iloc[0]
        else:
            ref[col] = float(np.nanmedian(pd.to_numeric(X[col], errors="coerce")))
    return ref


def global_importance(pipe, X, y, n_repeats=5, random_state=42):
    """Permutation importance in PR-AUC, plus the direction of each effect."""
    r = permutation_importance(pipe, X, y, scoring="average_precision",
                               n_repeats=n_repeats, random_state=random_state)
    rows = []
    for i, col in enumerate(X.columns):
        rows.append({
            "feature": col,
            "importance": round(float(r.importances_mean[i]), 6),
            "std": round(float(r.importances_std[i]), 6),
            "direction": _direction(X[col], y),
        })
    rows.sort(key=lambda d: -d["importance"])
    return rows


def _direction(col, y):
    """Does a higher value of this feature go with more conversion, or less?"""
    if col.name in features.CATEGORICAL:
        return "categorical"
    v = pd.to_numeric(col, errors="coerce")
    if v.nunique() < 2:
        return "flat"
    c = np.corrcoef(v.fillna(v.median()), y)[0, 1]
    return "up" if c > 0.005 else "down" if c < -0.005 else "flat"


def linear_terms(pipe):
    """The literal equation, when the selected model is a linear one.

    Returns None for a tree ensemble, where no such equation exists — better to
    say so than to invent one.
    """
    inner = _unwrap(pipe)
    if inner is None:
        return None
    model = inner.named_steps["model"]
    if not hasattr(model, "coef_"):
        return None
    names = inner.named_steps["prep"].get_feature_names_out()
    coefs = model.coef_[0]
    terms = [{"term": n.split("__", 1)[-1], "weight": round(float(w), 4)}
             for n, w in zip(names, coefs)]
    terms.sort(key=lambda d: -abs(d["weight"]))
    return {"intercept": round(float(model.intercept_[0]), 4), "terms": terms}


def _unwrap(pipe):
    """Reach the fitted Pipeline inside the calibration wrapper."""
    if hasattr(pipe, "named_steps"):
        return pipe
    cc = getattr(pipe, "calibrated_classifiers_", None)
    if cc:
        est = getattr(cc[0], "estimator", None)
        if est is not None and hasattr(est, "named_steps"):
            return est
    return None


def explain(pipe, lead_row, reference, top_n=10):
    """Per-feature contribution to one lead's score, in log-odds.

    Each contribution answers: how much higher (or lower) is this lead's score
    than it would be if this one feature were average, everything else held?
    """
    X = features.build(lead_row).iloc[[0]]
    p_actual = float(pipe.predict_proba(X)[:, 1][0])

    # the same lead with every feature set to the reference — the baseline
    base_frame = X.copy()
    for col, val in reference.items():
        if col in base_frame.columns:
            base_frame.loc[base_frame.index[0], col] = val
    p_base = float(pipe.predict_proba(base_frame)[:, 1][0])

    # ablate one feature at a time, in a single batched call
    cols = [c for c in X.columns if c in reference]
    probe = pd.concat([X] * len(cols), ignore_index=True)
    for i, col in enumerate(cols):
        probe.loc[i, col] = reference[col]
    probe_p = pipe.predict_proba(probe)[:, 1]

    z_actual = logit(p_actual)
    contributions = []
    for i, col in enumerate(cols):
        contributions.append({
            "feature": col,
            "value": _fmt(X.iloc[0][col]),
            "reference": _fmt(reference[col]),
            # removing this feature's own value moves the score by this much,
            # so its contribution is the amount it was adding
            "contribution": round(float(z_actual - logit(probe_p[i])), 4),
        })
    contributions.sort(key=lambda d: -abs(d["contribution"]))

    explained = sum(c["contribution"] for c in contributions)
    return {
        "probability": round(p_actual, 5),
        "base_probability": round(p_base, 5),
        "base_logit": round(float(logit(p_base)), 4),
        "final_logit": round(float(z_actual), 4),
        "contributions": contributions[:top_n],
        "other_contributions": round(float(sum(
            c["contribution"] for c in contributions[top_n:])), 4),
        # what one-at-a-time ablation cannot account for: feature interactions,
        # plus the non-linearity of the calibration layer
        "residual": round(float(z_actual - logit(p_base) - explained), 4),
    }


def sweep(pipe, lead_row, feature, points=24):
    """The model's response curve for one lead along one feature.

    Everything about the lead is held fixed and the single feature is swept, so
    the curve is the model's actual behaviour for this lead — not a population
    average.
    """
    X = features.build(lead_row).iloc[[0]]
    if feature not in X.columns:
        raise ValueError(f"unknown feature: {feature}")

    if feature in features.CATEGORICAL:
        values = sorted(features_levels(feature))
    else:
        lo, hi = FEATURE_RANGE.get(feature, (0.0, float(X.iloc[0][feature]) * 2 + 1))
        values = list(np.linspace(lo, hi, points))

    probe = pd.concat([X] * len(values), ignore_index=True)
    for i, v in enumerate(values):
        probe.loc[i, feature] = v
    probs = pipe.predict_proba(probe)[:, 1]

    return {
        "feature": feature,
        "current": _fmt(X.iloc[0][feature]),
        "points": [{"value": _fmt(v), "probability": round(float(p), 5)}
                   for v, p in zip(values, probs)],
    }


# Sweep bounds, taken from the ranges actually present in the data so the curve
# never wanders outside what the model has seen.
FEATURE_RANGE = {
    "minutes_since_abandonment": (1, 360),
    "days_to_policy_expiry": (-20, 60),
    "discount_percent": (0, 18),
    "sessions_last_7d": (1, 14),
    "offer_views_last_7d": (0, 12),
    "days_since_last_visit": (0, 60),
    "price_pct_in_product": (0, 1),
    "has_previous_purchase": (0, 1),
    "visited_offer_page": (0, 1),
    "incoming_call_last_24h": (0, 1),
    "is_expired": (0, 1),
}

_LEVELS = {
    "product_type": ["thirdparty", "carbody"],
    "channel": ["CRM", "SEO", "Paid", "Referral"],
    "device": ["mobile", "desktop"],
    "partner": ["direct", "shoraka", "autoabzar", "other_partner"],
    "insurance_company": ["Asia", "Iran", "Saman", "Alborz", "Dana", "Parsian", "Pasargad"],
    "payment_type": ["cash", "installment", "bnpl"],
}


def features_levels(col):
    return _LEVELS.get(col, [])


def sweepable():
    return sorted(list(FEATURE_RANGE) + list(_LEVELS))


def to_native(v):
    """numpy / Decimal scalars into something JSON can carry."""
    if v is None:
        return None
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else round(float(v), 4)
    if isinstance(v, np.bool_):
        return bool(v)
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, Decimal):
        return float(v)
    return str(v)


_fmt = to_native
