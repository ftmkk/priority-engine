"""Feature building + the sklearn pipeline.

What we drop and why (all from the EDA, see the About page):
  expected_margin           - deterministic ~2.7%/3.9% band of price (corr 0.99).
                              Used as the business weight in ranking, not as input.
  price_comparisons_last_7d - conversion 9.09% -> 9.55% across its whole range.
  city                      - 11 levels, no coherent signal.
"""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (ExtraTreesClassifier, HistGradientBoostingClassifier,
                              RandomForestClassifier)
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

CATEGORICAL = ["product_type", "channel", "device", "partner",
               "insurance_company", "payment_type"]

# Raw `price` is deliberately absent: it is mostly a proxy for product_type
# (carbody median ~19.6M vs thirdparty ~7.5M), and measured head to head it adds
# nothing over the within-product percentile — identical PR-AUC, so it is one
# redundant feature the model no longer has to spend capacity on.
NUMERIC = ["minutes_since_abandonment", "days_to_policy_expiry",
           "discount_percent", "sessions_last_7d", "offer_views_last_7d",
           "days_since_last_visit", "has_previous_purchase", "visited_offer_page",
           "incoming_call_last_24h",
           # engineered below
           "price_pct_in_product", "is_expired", "expiry_x_abandonment",
           "price_missing", "discount_missing"]


# Two features are defined against a *population*, not against the row itself:
# the within-product price percentile, and the medians that fill a missing price
# or discount. Computing those from whatever rows happen to be in the current
# batch makes a lead's features depend on the company it keeps -- the same lead
# scored 0.47 in a batch of 2,000, 0.37 in a batch of 50 and 1.0 when explained
# on its own. So the population is fitted once, at training time, and travels
# with the model.
QUANTILES = np.linspace(0, 1, 101)


def fit_reference(df):
    """Population statistics the serving path must reuse. Stored in the artifact."""
    price = pd.to_numeric(df["price"], errors="coerce")
    discount = pd.to_numeric(df["discount_percent"], errors="coerce")
    return {
        "price_quantiles": {str(k): np.quantile(v.dropna(), QUANTILES).tolist()
                            for k, v in price.groupby(df["product_type"]) if v.notna().any()},
        "price_median": {str(k): float(v.median()) for k, v in price.groupby(df["product_type"])
                         if v.notna().any()},
        "discount_median": {str(k): float(v.median())
                            for k, v in discount.groupby(df["product_type"]) if v.notna().any()},
        "price_median_all": float(price.median()),
        "discount_median_all": float(discount.median()),
    }


def _pct_from(quantiles, product_type, price):
    """Where this price sits in the training population for its product."""
    grid = quantiles.get(str(product_type))
    if grid is None or np.isnan(price):
        return np.nan
    return float(np.searchsorted(grid, price) / (len(grid) - 1))


def build(df, ref=None):
    """Raw lead rows -> model input frame. Same code path for train and predict.

    `ref` is a fit_reference() dict. Without one the population is taken from the
    frame itself, which is correct only while fitting.
    """
    X = df.copy()

    for col in ("price", "discount_percent", "days_since_last_visit"):
        X[col] = pd.to_numeric(X[col], errors="coerce")

    # Missingness is itself a signal: price is absent 3.5% of the time on the
    # Referral channel vs ~1.5% elsewhere, so we flag it before imputing.
    X["price_missing"] = X["price"].isna().astype(int)
    X["discount_missing"] = X["discount_percent"].isna().astype(int)

    # Impute inside product_type — carbody median price ~19.6M vs thirdparty
    # ~7.5M, so one global median would distort both.
    for col, by_product, overall in (("price", "price_median", "price_median_all"),
                                     ("discount_percent", "discount_median",
                                      "discount_median_all")):
        fill = (X["product_type"].astype(str).map(ref[by_product]) if ref
                else X.groupby("product_type")[col].transform("median"))
        X[col] = X[col].fillna(fill).fillna(ref[overall] if ref else X[col].median())

    # Raw price is mostly a proxy for product_type; within-product rank isn't.
    X["price_pct_in_product"] = (
        [_pct_from(ref["price_quantiles"], p, v)
         for p, v in zip(X["product_type"], X["price"])] if ref
        else X.groupby("product_type")["price"].rank(pct=True)
    )

    # 14% of rows have a negative expiry: the policy already lapsed. Not an
    # outlier — the highest-converting group there is (13.1%).
    X["is_expired"] = (X["days_to_policy_expiry"] < 0).astype(int)

    # Leads far from expiry cool off faster (2.03x vs 1.59x decay), so the two
    # clocks interact rather than just adding up.
    X["expiry_x_abandonment"] = (
        X["days_to_policy_expiry"].clip(lower=0) * X["minutes_since_abandonment"] / 1000
    )

    X[CATEGORICAL] = X[CATEGORICAL].fillna("Unknown")
    return X[CATEGORICAL + NUMERIC]


# The candidates, one per family, so the comparison says something about the
# *kind* of model rather than about one library's defaults: a linear baseline,
# boosted trees, and two bagged-tree variants that differ only in how they pick
# splits. Every one of them is class-weighted -- at a 9% base rate an unweighted
# fit collapses onto the majority and ranks worse.
MODELS = {
    "logreg": lambda rs: LogisticRegression(max_iter=3000, class_weight="balanced"),
    "gbdt": lambda rs: HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.06, max_leaf_nodes=31, min_samples_leaf=40,
        l2_regularization=1.0, early_stopping=True, validation_fraction=0.15,
        n_iter_no_change=25, class_weight="balanced", random_state=rs),
    # Deep unpruned trees overfit a 9% target badly, so the leaves are held wide.
    # A 20-point sweep over min_samples_leaf (5-200) x max_features (sqrt, 0.3)
    # on the validation window kept the whole bagged-tree family between 0.18 and
    # 0.19 PR-AUC, against 0.205 for the linear model -- so the gap below is the
    # family, not the settings, and there is nothing to win by tuning harder.
    "rf": lambda rs: RandomForestClassifier(
        n_estimators=400, min_samples_leaf=50, max_features="sqrt",
        class_weight="balanced_subsample", n_jobs=-1, random_state=rs),
    "extratrees": lambda rs: ExtraTreesClassifier(
        n_estimators=400, min_samples_leaf=50, max_features="sqrt",
        class_weight="balanced_subsample", n_jobs=-1, random_state=rs),
}


def make_pipeline(algorithm, random_state=42):
    if algorithm not in MODELS:
        raise ValueError(f"unknown algorithm {algorithm!r}; pick from {sorted(MODELS)}")
    prep = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CATEGORICAL),
        ("num", StandardScaler(), NUMERIC),
    ])
    return Pipeline([("prep", prep), ("model", MODELS[algorithm](random_state))])


def rule_baseline(df):
    """The hand-written rule the model has to beat (2.8x lift on its own)."""
    return (
        (df["visited_offer_page"] == 1).astype(int)
        + (df["has_previous_purchase"] == 1).astype(int)
        + (df["days_to_policy_expiry"] <= 7).astype(int)
        + (df["minutes_since_abandonment"] <= 60).astype(int)
    ).to_numpy(dtype=float)
