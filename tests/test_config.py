import importlib
import os


def test_env_overrides_yaml_and_keeps_type():
    os.environ["PE_TRAIN__ALGORITHM"] = "logreg"
    os.environ["PE_TRAIN__HOLDOUT_DAYS"] = "14"
    try:
        from priority_engine import config
        cfg = importlib.reload(config).load()
        assert cfg["train"]["algorithm"] == "logreg"
        assert cfg["train"]["holdout_days"] == 14        # int, not "14"
        assert isinstance(cfg["train"]["holdout_days"], int)
    finally:
        del os.environ["PE_TRAIN__ALGORITHM"], os.environ["PE_TRAIN__HOLDOUT_DAYS"]
        importlib.reload(config)


def test_db_url_is_built_from_postgres_env():
    from priority_engine.config import load
    os.environ["POSTGRES_HOST"] = "somehost"
    try:
        assert "somehost" in load()["db_url"]
    finally:
        del os.environ["POSTGRES_HOST"]
