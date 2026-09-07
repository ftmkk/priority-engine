"""Tests for the parts that are easy to get quietly wrong."""
import numpy as np
import pandas as pd
import pytest

from priority_engine import features, metrics


def make_leads(n=200, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "lead_id": [f"L{i}" for i in range(n)],
        "created_at": pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC"),
        "product_type": rng.choice(["thirdparty", "carbody"], n),
        "channel": rng.choice(["SEO", "Paid", "CRM", "Referral"], n),
        "device": rng.choice(["mobile", "desktop"], n),
        "partner": rng.choice(["direct", "shoraka"], n),
        "insurance_company": rng.choice(["Asia", "Iran", "Saman"], n),
        "payment_type": rng.choice(["cash", "bnpl", "installment"], n),
        "minutes_since_abandonment": rng.integers(1, 360, n),
        "days_to_policy_expiry": rng.integers(-20, 60, n),
        "price": rng.integers(1_500_000, 40_000_000, n).astype(float),
        "discount_percent": rng.uniform(0, 18, n),
        "sessions_last_7d": rng.integers(1, 14, n),
        "offer_views_last_7d": rng.integers(0, 12, n),
        "days_since_last_visit": rng.uniform(0, 60, n),
        "has_previous_purchase": rng.integers(0, 2, n),
        "visited_offer_page": rng.integers(0, 2, n),
        "incoming_call_last_24h": rng.integers(0, 2, n),
        "expected_margin": rng.integers(35_000, 1_500_000, n).astype(float),
        "completed_purchase": rng.integers(0, 2, n),
    })


# --- features -------------------------------------------------------------- #
def test_build_produces_expected_columns():
    X = features.build(make_leads())
    assert list(X.columns) == features.CATEGORICAL + features.NUMERIC


def test_build_leaves_no_nulls_when_price_is_missing():
    df = make_leads()
    df.loc[:20, "price"] = np.nan
    df.loc[:10, "discount_percent"] = np.nan
    X = features.build(df)
    assert not X[features.NUMERIC].isna().any().any()
    assert X["price_missing"].sum() == 21          # flag survives imputation
    assert X["discount_missing"].sum() == 11


def test_excluded_columns_never_reach_the_model():
    X = features.build(make_leads())
    for col in ("expected_margin", "price_comparisons_last_7d", "city"):
        assert col not in X.columns


def test_is_expired_matches_negative_expiry():
    df = make_leads()
    X = features.build(df)
    assert (X["is_expired"] == (df["days_to_policy_expiry"] < 0).astype(int)).all()


def test_pipeline_fits_and_predicts_in_range():
    df = make_leads(400)
    pipe = features.make_pipeline("gbdt")
    pipe.fit(features.build(df), df["completed_purchase"])
    p = pipe.predict_proba(features.build(df))[:, 1]
    assert len(p) == len(df) and ((p >= 0) & (p <= 1)).all()


# --- metrics --------------------------------------------------------------- #
def test_perfect_ranking_scores_better_than_inverted():
    y = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    margin = np.ones(8) * 1000
    good = metrics.evaluate(y, np.arange(8) / 8, margin, capacity_k=(4,))
    bad = metrics.evaluate(y, -np.arange(8) / 8, margin, capacity_k=(4,))
    assert good["pr_auc"] > bad["pr_auc"]
    assert good["at_k"][0]["precision"] == 1.0
    assert bad["at_k"][0]["precision"] == 0.0


def test_lift_at_k_is_one_for_a_random_ranking():
    rng = np.random.default_rng(0)
    y = (rng.random(4000) < 0.1).astype(int)
    r = metrics.evaluate(y, rng.random(4000), np.ones(4000), capacity_k=(2000,))
    assert 0.8 < r["at_k"][0]["lift"] < 1.2


def test_gains_curve_is_monotonic_and_ends_at_one():
    y = (np.arange(500) % 10 == 0).astype(int)
    g = metrics.evaluate(y, np.arange(500)[::-1] / 500, np.ones(500))["gains"]
    captured = [p["captured"] for p in g]
    assert captured == sorted(captured)
    assert captured[-1] == pytest.approx(1.0, abs=0.02)


def test_rule_baseline_ranges_zero_to_four():
    s = features.rule_baseline(make_leads())
    assert s.min() >= 0 and s.max() <= 4
