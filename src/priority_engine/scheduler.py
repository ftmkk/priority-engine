"""The two scheduled jobs: monthly training, 5-minute prediction.

Run as `python -m priority_engine.scheduler` (the worker container's command).
"""
import json
import logging
import time
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import db, predict, train
from .config import CFG
from .models import JobRun

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("scheduler")


def _tracked(name, fn, trigger="schedule"):
    """Run a job, recording start/finish/failure in pe.job_runs."""
    with db.session() as s:
        run = JobRun(job_name=name, status="running", trigger=trigger)
        s.add(run)
        s.flush()
        run_id = run.id
    started = time.monotonic()

    def finish(**fields):
        with db.session() as s:
            run = s.get(JobRun, run_id)
            for k, v in fields.items():
                setattr(run, k, v)

    try:
        detail = fn() or {}
        finish(status="success", finished_at=datetime.now(timezone.utc),
               duration_ms=int((time.monotonic() - started) * 1000),
               rows_processed=detail.get("scored") or detail.get("rows"),
               detail=json.loads(json.dumps(detail, default=str)))
        log.info("%s ok: %s", name, detail)
    except Exception as exc:
        finish(status="failed", finished_at=datetime.now(timezone.utc),
               duration_ms=int((time.monotonic() - started) * 1000), error=str(exc))
        log.exception("%s failed", name)


def main():
    db.wait_ready()
    db.migrate()
    jobs = CFG["jobs"]

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(lambda: _tracked("training", train.run), CronTrigger.from_crontab(jobs["train_cron"]),
                  id="training", misfire_grace_time=3600)
    sched.add_job(lambda: _tracked("prediction", predict.run), CronTrigger.from_crontab(jobs["predict_cron"]),
                  id="prediction", misfire_grace_time=120, max_instances=1)
    sched.start()
    log.info("scheduled: training=%s prediction=%s", jobs["train_cron"], jobs["predict_cron"])

    if jobs["run_on_startup"]:
        # A fresh stack has no model, and scoring needs one.
        if not db.scalar("SELECT count(*) FROM pe.model_versions WHERE is_active"):
            _tracked("training", train.run, trigger="startup")
        _tracked("prediction", predict.run, trigger="startup")

    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()


if __name__ == "__main__":
    main()
