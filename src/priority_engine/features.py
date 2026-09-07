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
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

CATEGORICAL = ["product_type", "channel", "device", "partner",
               "insurance_company", "payment_type"]

NUMERIC = ["minutes_since_abandonment", "days_to_policy_expiry", "price",
           "discount_percent", "sessions_last_7d", "offer_views_last_7d",
           "days_since_last_visit", "has_previous_purchase", "visited_offer_page",
           "incoming_call_last_24h",
           # engineered below
           "price_pct_in_product", "is_expired", "expiry_x_abandonment",
           "price_missing", "discount_missing"]


def build(df):
    """Raw lead rows -> model input frame. Same code path for train and predict."""
    X = df.copy()

    for col in ("price", "discount_percent", "days_since_last_visit"):
        X[col] = pd.to_numeric(X[col], errors="coerce")

    # Missingness is itself a signal: price is absent 3.5% of the time on the
    # Referral channel vs ~1.5% elsewhere, so we flag it before imputing.
    X["price_missing"] = X["price"].isna().astype(int)
    X["discount_missing"] = X["discount_percent"].isna().astype(int)

    # Impute inside product_type — carbody median price ~19.6M vs thirdparty
    # ~7.5M, so one global median would distort both.
    for col in ("price", "discount_percent"):
        X[col] = X[col].fillna(X.groupby("product_type")[col].transform("median"))
        X[col] = X[col].fillna(X[col].median())

    # Raw price is mostly a proxy for product_type; within-product rank isn't.
    X["price_pct_in_product"] = X.groupby("product_type")["price"].rank(pct=True)

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


def make_pipeline(algorithm, random_state=42):
    prep = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CATEGORICAL),
        ("num", StandardScaler(), NUMERIC),
    ])
    if algorithm == "logreg":
        model = LogisticRegression(max_iter=3000, class_weight="balanced")
    else:
        model = HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
            min_samples_leaf=40, l2_regularization=1.0,
            early_stopping=True, validation_fraction=0.15, n_iter_no_change=25,
            class_weight="balanced", random_state=random_state,
        )
    return Pipeline([("prep", prep), ("model", model)])


def rule_baseline(df):
    """The hand-written rule the model has to beat (2.8x lift on its own)."""
    return (
        (df["visited_offer_page"] == 1).astype(int)
        + (df["has_previous_purchase"] == 1).astype(int)
        + (df["days_to_policy_expiry"] <= 7).astype(int)
        + (df["minutes_since_abandonment"] <= 60).astype(int)
    ).to_numpy(dtype=float)
