"""The decay lives in SQL now, so it is tested against a real Postgres.

These assert the property that matters: the model prices the abandonment age it
was given, and the view decays only the time that has passed *since* then.
"""
import numpy as np
import pytest

from priority_engine import db
from priority_engine.config import CFG


@pytest.fixture(scope="module", autouse=True)
def schema():
    """Tests share the running Postgres, so the synthetic leads they insert must
    not survive into the real queue."""
    db.wait_ready()
    db.migrate()
    _purge()
    yield
    _purge()


def _purge():
    db.execute("DELETE FROM pe.predictions WHERE lead_id LIKE 'TEST\\_%'")
    db.execute("DELETE FROM pe.leads WHERE lead_id LIKE 'TEST\\_%'")


def seed(lead_id, minutes_since_abandonment, age_minutes, probability=0.2,
         margin=1_000_000, scored_at_age=None):
    """One lead whose features were captured `age_minutes` ago.

    `scored_at_age` is the age the stored score was computed at; it defaults to
    what the scoring job would have produced (current age, capped at support).
    """
    db.execute("DELETE FROM pe.predictions WHERE lead_id = :l", l=lead_id)
    db.execute("DELETE FROM pe.leads WHERE lead_id = :l", l=lead_id)
    db.execute("""
        INSERT INTO pe.leads (lead_id, created_at, product_type, expected_margin,
                              minutes_since_abandonment, completed_purchase)
        VALUES (:l, (SELECT max(created_at) FROM pe.leads) - make_interval(mins => :age),
                'thirdparty', :m, :msa, 0)
    """, l=lead_id, age=age_minutes, m=margin, msa=minutes_since_abandonment)
    support = CFG["priority"]["decay_support_minutes"]
    if scored_at_age is None:
        scored_at_age = min(minutes_since_abandonment + age_minutes, support)
    version = db.scalar("SELECT version FROM pe.model_versions WHERE is_active")
    db.execute("""
        INSERT INTO pe.predictions
          (lead_id, model_version, probability, score, scored_at_age_minutes,
           lead_created_at, predicted_at, batch_id)
        VALUES (:l, :v, :p, :s, :age,
                (SELECT created_at FROM pe.leads WHERE lead_id = :l), now(), :b)
    """, l=lead_id, v=version, p=probability, s=int(probability * 1000),
         age=scored_at_age, b=f"test-{lead_id}")


def read(lead_id):
    r = db.query("SELECT * FROM pe.v_current_priority WHERE lead_id = :l", l=lead_id)
    assert not r.empty, f"{lead_id} missing from v_current_priority"
    return r.iloc[0]


def test_inside_support_the_score_is_used_as_is():
    """The job re-inferred at this age, so the stored number is already current
    and the view must not decay it a second time."""
    seed("TEST_INSIDE", minutes_since_abandonment=30, age_minutes=120)
    row = read("TEST_INSIDE")
    assert row["current_age_minutes"] == pytest.approx(150, abs=1)
    assert row["excess_minutes"] == pytest.approx(0, abs=1e-6)
    assert row["decayed_probability"] == pytest.approx(0.2, abs=1e-6)
    assert not row["is_stale"]


def test_past_the_boundary_the_anchor_decays():
    """Two hours beyond the boundary decays the anchor by rate^2."""
    support = CFG["priority"]["decay_support_minutes"]
    rate = CFG["priority"]["decay_per_hour"]
    seed("TEST_OUTSIDE", minutes_since_abandonment=60,
         age_minutes=support - 60 + 120)          # 120 min past the boundary
    row = read("TEST_OUTSIDE")
    assert row["excess_minutes"] == pytest.approx(120, abs=1)
    odds = (0.2 / 0.8) * rate ** 2
    assert row["decayed_probability"] == pytest.approx(odds / (1 + odds), abs=1e-4)
    assert row["is_stale"]


def test_decay_depends_on_total_age_not_on_age_at_capture():
    """Two leads at the same current age decay identically, whatever their
    abandonment age was when captured. Otherwise the model's own handling of
    that age would be double-counted here."""
    support = CFG["priority"]["decay_support_minutes"]
    target = support + 90
    seed("TEST_WAS_YOUNG", minutes_since_abandonment=10, age_minutes=target - 10)
    seed("TEST_WAS_OLD", minutes_since_abandonment=300, age_minutes=target - 300)
    young, old = read("TEST_WAS_YOUNG"), read("TEST_WAS_OLD")
    assert young["excess_minutes"] == pytest.approx(old["excess_minutes"], abs=1)
    assert young["decayed_probability"] == pytest.approx(
        old["decayed_probability"], abs=1e-6)


def test_a_lead_past_the_queue_horizon_leaves_the_queue():
    """Not decayed to a rounding error and left at the bottom -- removed. Nobody
    calls a lead this old, and decaying over months isn't something the fitted
    constant can support."""
    horizon = CFG["priority"]["queue_horizon_hours"] * 60
    seed("TEST_ANCIENT", minutes_since_abandonment=100, age_minutes=horizon + 600)
    assert db.query("SELECT 1 FROM pe.v_current_priority WHERE lead_id = 'TEST_ANCIENT'").empty


def test_decay_is_capped_so_the_arithmetic_stays_representable():
    horizon = CFG["priority"]["queue_horizon_hours"] * 60
    cap = CFG["priority"]["decay_max_excess_hours"] * 60
    seed("TEST_NEAR_EDGE", minutes_since_abandonment=10, age_minutes=horizon - 20)
    row = read("TEST_NEAR_EDGE")
    assert row["excess_minutes"] <= cap + 1
    assert row["decayed_probability"] > 0
    assert np.isfinite(row["decayed_probability"])


def test_expected_value_uses_margin_and_ranks_the_queue():
    seed("TEST_CHEAP", 30, 0, probability=0.30, margin=100_000)
    seed("TEST_RICH", 30, 0, probability=0.15, margin=1_000_000)
    cheap, rich = read("TEST_CHEAP"), read("TEST_RICH")
    assert float(rich["expected_value"]) > float(cheap["expected_value"])
    assert rich["priority_rank"] < cheap["priority_rank"]
    assert rich["priority_tier"] in {"P1", "P2", "P3", "P4"}


def test_scoring_job_walks_a_lead_through_its_support_window():
    """A lead inside the window is picked up as needing work; the same lead once
    its stored score already sits at the boundary is not."""
    from priority_engine.predict import leads_needing_score
    version = db.scalar("SELECT version FROM pe.model_versions WHERE is_active")
    support = CFG["priority"]["decay_support_minutes"]

    # aged 200 min but only ever scored at age 30 -> needs a fresh inference
    seed("TEST_DUE", minutes_since_abandonment=30, age_minutes=170, scored_at_age=30)
    assert "TEST_DUE" in set(leads_needing_score(version)["lead_id"])

    # already anchored at the boundary -> never needs scoring again
    seed("TEST_DONE", minutes_since_abandonment=100, age_minutes=5_000,
         scored_at_age=support)
    assert "TEST_DONE" not in set(leads_needing_score(version)["lead_id"])


def test_advance_clock_moves_both_clocks():
    """Abandonment age up, days-to-expiry down, by the same elapsed amount."""
    import pandas as pd
    from priority_engine.predict import advance_clock
    df = pd.DataFrame({"minutes_since_abandonment": [30], "target_age": [1470.0],
                       "days_to_policy_expiry": [10]})
    out = advance_clock(df)
    assert out["minutes_since_abandonment"].iloc[0] == 1470.0
    assert out["days_to_policy_expiry"].iloc[0] == pytest.approx(9.0)  # 1440 min = 1 day
