"""Pipeline commands.  docker compose run --rm cli <command>"""
import json
import logging

import typer

from . import db, ingest, predict, train

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = typer.Typer(add_completion=False, help="Lead Priority Engine")


@app.command()
def bootstrap():
    """Wait for Postgres, apply migrations, load the CSV. Runs once at stack start."""
    db.wait_ready()
    db.migrate()
    rows = ingest.load_csv()
    typer.echo(f"ready — {rows} lead rows in Postgres")


@app.command("load-data")
def load_data(force: bool = typer.Option(False, help="truncate and reload")):
    """Load data/leads.csv into Postgres."""
    db.wait_ready()
    db.migrate()
    typer.echo(f"{ingest.load_csv(force=force)} rows")


@app.command()
def migrate():
    """Apply db/migrations/*.sql."""
    db.wait_ready()
    db.migrate()
    typer.echo("migrations applied")


@app.command("train")
def train_model():
    """Train on the historical period, evaluate on the held-out tail, register."""
    db.wait_ready()
    db.migrate()
    result = train.run()
    typer.echo(json.dumps({k: v for k, v in result.items() if k != "metrics"}, indent=2))
    typer.echo(f"holdout pr_auc={result['metrics']['pr_auc']:.4f} "
               f"roc_auc={result['metrics']['roc_auc']:.4f}")


@app.command()
def evaluate():
    """Print the registered metrics for the active model."""
    db.wait_ready()
    db.migrate()
    row = db.query("SELECT version, algorithm, metrics, selection_metrics, "
                   "candidate_results FROM pe.model_versions WHERE is_active")
    if row.empty:
        typer.echo("no active model — run `train` first")
        raise typer.Exit(1)
    r = row.iloc[0]
    m = r["metrics"]
    typer.echo(f"model {r['version']} ({r['algorithm']})")
    typer.echo("  holdout (scored once, after the algorithm was fixed):")
    typer.echo(f"  pr_auc  {m['pr_auc']:.4f}\n  roc_auc {m['roc_auc']:.4f}\n"
               f"  brier   {m['brier']:.4f}\n  base    {m['base_rate']:.4f}  n={m['n']}")
    for k in m["at_k"]:
        typer.echo(f"  @{k['k']:>5}: precision {k['precision']:.3f}  "
                   f"recall {k['recall']:.3f}  lift {k['lift']:.2f}x  "
                   f"margin {k['margin_capture']:.3f}")
    sel = r["selection_metrics"] or {}
    if sel.get("pr_auc") is not None:
        typer.echo(f"  selection window pr_auc {sel['pr_auc']:.4f} "
                   "(validation — this is what chose the algorithm)")
    for window in ("validation", "holdout"):
        scored = [c for c in r["candidate_results"] if c.get("scored_on", "validation") == window]
        if scored:
            typer.echo(f"  candidates on {window}: " + ", ".join(
                f"{c['algorithm']} {c['pr_auc']:.4f}" for c in scored))


@app.command("predict")
def predict_batch(limit: int = typer.Option(None, help="cap rows this run")):
    """Score leads whose age has moved past their last score."""
    _predict(limit)


def _predict(limit=None):
    """The body, callable from Python. A typer command is not: its defaults are
    OptionInfo objects, so `predict_batch()` would hand `limit=OptionInfo(...)`
    straight to the scoring job."""
    db.wait_ready()
    db.migrate()
    typer.echo(json.dumps(predict.run(limit), indent=2, default=str))


@app.command()
def pipeline():
    """Everything end to end: load -> train -> predict."""
    bootstrap()
    train_model()
    _predict()


if __name__ == "__main__":
    app()
