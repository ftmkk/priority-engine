"""Config: config.yaml + PE_* env overrides. DB creds from POSTGRES_* only."""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _apply_env_overrides(cfg):
    """PE_TRAIN__ALGORITHM=logreg  ->  cfg["train"]["algorithm"] = "logreg" """
    for key, val in os.environ.items():
        if not key.startswith("PE_"):
            continue
        parts = key[3:].lower().split("__")
        node = cfg
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        old = node.get(parts[-1])
        # keep the yaml value's type
        if isinstance(old, bool):
            val = val.lower() in ("1", "true", "yes")
        elif isinstance(old, int):
            val = int(val)
        elif isinstance(old, float):
            val = float(val)
        node[parts[-1]] = val
    return cfg


def load():
    path = Path(os.getenv("PE_CONFIG_PATH", ROOT / "config" / "config.yaml"))
    cfg = _apply_env_overrides(yaml.safe_load(path.read_text()))

    cfg["db_url"] = (
        f"postgresql+psycopg://{os.getenv('POSTGRES_USER', 'priority')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'priority')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'priority_engine')}"
    )
    for k in ("artifacts_dir",):
        cfg[k] = ROOT / cfg[k]
        cfg[k].mkdir(parents=True, exist_ok=True)
    cfg["csv_path"] = ROOT / cfg["csv_path"]
    return cfg


CFG = load()
