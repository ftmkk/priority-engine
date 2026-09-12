import importlib
import os


def test_env_overrides_yaml_and_keeps_type():
    os.environ["PE_JOBS__PREDICT_CRON"] = "*/2 * * * *"
    os.environ["PE_TRAIN__HOLDOUT_DAYS"] = "14"
    try:
        from priority_engine import config
        cfg = importlib.reload(config).load()
        assert cfg["jobs"]["predict_cron"] == "*/2 * * * *"
        assert cfg["train"]["holdout_days"] == 14        # int, not "14"
        assert isinstance(cfg["train"]["holdout_days"], int)
    finally:
        del os.environ["PE_JOBS__PREDICT_CRON"], os.environ["PE_TRAIN__HOLDOUT_DAYS"]
        importlib.reload(config)


def test_db_url_is_built_from_postgres_env():
    from priority_engine.config import load
    os.environ["POSTGRES_HOST"] = "somehost"
    try:
        assert "somehost" in load()["db_url"]
    finally:
        del os.environ["POSTGRES_HOST"]


def _clock(value):
    """Reload config with priority.current_time set, and read the clock through it."""
    import importlib
    from priority_engine import config
    if value is None:
        os.environ.pop("PE_PRIORITY__CURRENT_TIME", None)
    else:
        os.environ["PE_PRIORITY__CURRENT_TIME"] = value
    cfg = importlib.reload(config).load()
    from priority_engine import db
    db.CFG = cfg
    try:
        return db.clock_mode(), db.clock_sql()
    finally:
        os.environ.pop("PE_PRIORITY__CURRENT_TIME", None)
        db.CFG = importlib.reload(config).CFG


def test_current_time_dataset_reads_the_newest_row():
    mode, sql = _clock("dataset")
    assert mode == "dataset"
    assert "max(created_at)" in sql


def test_current_time_accepts_an_explicit_instant():
    """A fixed instant is parsed and re-emitted, never interpolated as typed:
    this string is compiled into a CREATE VIEW."""
    mode, sql = _clock("2026-08-20T12:00:00Z")
    assert mode == "fixed"
    assert sql == "TIMESTAMPTZ '2026-08-20T12:00:00+00:00'"


def test_a_hostile_current_time_cannot_reach_the_view():
    import pytest
    with pytest.raises(ValueError):
        _clock("2026-08-20'; DROP TABLE pe.leads; --")


def test_blank_current_time_means_the_real_clock():
    mode, sql = _clock("")
    assert (mode, sql) == ("wall", "now()")
