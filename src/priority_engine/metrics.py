"""Evaluation metrics.

Accuracy is meaningless at a 9.2% base rate, and the floor has finite capacity,
so precision@k / lift@k at realistic k ARE the business metric. PR-AUC is the
headline; ROC-AUC is secondary.
"""
import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def at_k(y, score, margin, k):
    order = np.argsort(-score)
    top = order[:k]
    caught = y[top].sum()
    total = y.sum()
    return {
        "k": int(k),
        "precision": float(caught / k) if k else 0.0,
        "recall": float(caught / total) if total else 0.0,
        "lift": float((caught / k) / (total / len(y))) if k and total else 0.0,
        "margin_capture": float(
            margin[top][y[top] == 1].sum() / margin[y == 1].sum()
        ) if margin[y == 1].sum() else 0.0,
    }


def gains_curve(y, score, steps=50):
    """Share of all converters captured as you work down the ranked queue."""
    order = np.argsort(-score)
    cum = np.cumsum(y[order])
    total = y.sum() or 1
    n = len(y)
    return [
        {"depth": round((i + 1) / steps, 4),
         "captured": round(float(cum[min(int(n * (i + 1) / steps), n - 1)] / total), 4)}
        for i in range(steps)
    ]


def calibration_curve(y, score, bins=12):
    """Predicted vs observed, by score bucket.

    Measured here rather than from the served scores: the scoring job advances a
    lead's clock before asking the model, so a served score answers "what now?"
    while the recorded outcome answers "what happened at the original age". Only
    on the holdout do the two refer to the same moment.
    """
    edges = np.quantile(score, np.linspace(0, 1, bins + 1))
    edges = np.unique(edges)
    idx = np.clip(np.searchsorted(edges, score, side="right") - 1, 0, len(edges) - 2)
    out = []
    for b in range(len(edges) - 1):
        m = idx == b
        if m.sum() < 20:
            continue
        out.append({"bucket": b, "leads": int(m.sum()),
                    "predicted": round(float(score[m].mean()), 5),
                    "observed": round(float(y[m].mean()), 5)})
    return out


def evaluate(y, score, margin, capacity_k=(250, 500, 1000, 2500)):
    y = np.asarray(y, dtype=int)
    score = np.asarray(score, dtype=float)
    margin = np.asarray(margin, dtype=float)
    return {
        "pr_auc": float(average_precision_score(y, score)),
        "roc_auc": float(roc_auc_score(y, score)),
        "brier": float(brier_score_loss(y, np.clip(score, 0, 1))),
        "base_rate": float(y.mean()),
        "n": int(len(y)),
        "at_k": [at_k(y, score, margin, k) for k in capacity_k if k <= len(y)],
        "gains": gains_curve(y, score),
        "calibration": calibration_curve(y, score),
    }
