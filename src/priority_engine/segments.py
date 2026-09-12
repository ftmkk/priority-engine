"""Lead segmentation — who the leads are, separate from how they rank.

The ranking answers "call this one first". It does not answer "what kind of lead
is this", and those are different questions: two leads can score alike for
completely different reasons. Segmentation groups leads by their own shape, then
we look at how the call queue falls across those groups.

k-means in the same feature space the model reasons about (so the segments are
comparable to the scores), with k chosen by silhouette rather than by hand. The
2-D coordinates are PCA and exist only for the scatter plot — the clustering
itself never sees them, so a segment that looks split on screen is a projection
artefact, not a clustering failure.
"""
import logging

import numpy as np
from sklearn.cluster import KMeans
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import select

from . import features, views
from .db import engine, query, session
from .models import LeadSegment, Segment

log = logging.getLogger(__name__)

K_RANGE = (3, 4, 5, 6, 7)
SILHOUETTE_SAMPLE = 5000

# Traits used to describe a segment in words. Each is (column, label, threshold
# style) — the description says how a segment differs from the population.
DESCRIBE = [
    ("visited_offer_page", "reached the offer page"),
    ("has_previous_purchase", "returning customer"),
    ("offer_views_last_7d", "offer views"),
    ("sessions_last_7d", "sessions"),
    ("minutes_since_abandonment", "minutes since abandoning"),
    ("days_to_policy_expiry", "days to expiry"),
    ("discount_percent", "discount"),
    ("price_pct_in_product", "price percentile"),
    ("incoming_call_last_24h", "inbound call"),
]


def _preprocessor():
    return ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=50),
         features.CATEGORICAL),
        ("num", StandardScaler(), features.NUMERIC),
    ])


def _choose_k(Z, random_state):
    """Pick k by silhouette on a sample. Reported, not silently assumed."""
    rng = np.random.default_rng(random_state)
    idx = rng.choice(len(Z), size=min(SILHOUETTE_SAMPLE, len(Z)), replace=False)
    scores = {}
    for k in K_RANGE:
        km = KMeans(n_clusters=k, n_init=4, random_state=random_state).fit(Z[idx])
        scores[k] = float(silhouette_score(Z[idx], km.labels_))
    best = max(scores, key=scores.get)
    log.info("silhouette: %s -> k=%d",
             {k: round(v, 4) for k, v in scores.items()}, best)
    return best, scores


def _label(seg_means, overall, n_leads, total):
    """Describe a segment by what actually sets it apart."""
    traits = []
    for col, name in DESCRIBE:
        if col not in seg_means:
            continue
        mu, ref = seg_means[col], overall[col]
        spread = overall.get(f"{col}__std", 1.0) or 1.0
        z = (mu - ref) / spread
        if abs(z) < 0.4:
            continue
        traits.append({"trait": name, "value": round(float(mu), 2),
                       "population": round(float(ref), 2), "z": round(float(z), 2)})
    traits.sort(key=lambda t: -abs(t["z"]))

    if not traits:
        return f"Average across the board ({n_leads / total:.0%} of leads)", traits
    top = traits[:2]
    parts = [f"{'high' if t['z'] > 0 else 'low'} {t['trait']}" for t in top]
    return " · ".join(parts), traits


def fit(model_version, random_state=42):
    """Cluster every lead, project to 2-D, and write both to Postgres."""
    df = query(select(views.v_leads_curated))
    if df.empty:
        raise RuntimeError("no leads to segment")

    # No fitted reference needed: this frame IS the whole population, which is
    # what those features are defined against.
    X = features.build(df)
    Z = _preprocessor().fit_transform(X)
    Z = Z.toarray() if hasattr(Z, "toarray") else np.asarray(Z)

    k, scores = _choose_k(Z, random_state)
    km = KMeans(n_clusters=k, n_init=10, random_state=random_state).fit(Z)
    coords = PCA(n_components=2, random_state=random_state).fit_transform(Z)

    df = df.assign(segment=km.labels_, x=coords[:, 0], y=coords[:, 1])

    # population reference, in the original units people can read
    numeric = [c for c, _ in DESCRIBE if c in X.columns]
    overall = {c: float(X[c].mean()) for c in numeric}
    overall.update({f"{c}__std": float(X[c].std()) or 1.0 for c in numeric})

    with session() as s:
        s.query(LeadSegment).filter_by(model_version=model_version).delete()
        s.query(Segment).filter_by(model_version=model_version).delete()

    out = df[["lead_id", "segment", "x", "y"]].copy()
    out["model_version"] = model_version
    out.to_sql("lead_segments", engine, schema="pe", if_exists="append",
               index=False, chunksize=1000, method="multi")

    Xs = X.assign(segment=km.labels_)
    rows = []
    for seg in range(k):
        block = Xs[Xs["segment"] == seg]
        seg_means = {c: float(block[c].mean()) for c in numeric}
        label, traits = _label(seg_means, overall, len(block), len(Xs))
        rows.append(Segment(model_version=model_version, segment=int(seg), label=label,
                            size=int(len(block)), centroid=seg_means, traits=traits))

    with session() as s:
        s.add_all(rows)

    log.info("segmented %s leads into %s groups", len(df), k)
    return {"k": k, "silhouette": scores, "leads": int(len(df))}
