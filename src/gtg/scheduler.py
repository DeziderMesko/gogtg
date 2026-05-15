import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from gtg.models import CompletedSet, Config, DayPlan, DayType
from gtg.notifier import Notifier
from gtg.scheduling import (
    advance_cycle,
    day_type_for_position,
    needs_recalibration,
    plan_day,
)
from gtg.server import AppContext, create_app
from gtg.storage import append_history, load_config, load_state, save_state

logger = logging.getLogger(__name__)

_CATCHUP_MINUTES = 30
_SET_JOB_PREFIX = "gtg_set_"
_ROLLOVER_JOB_ID = "gtg_rollover"


class GTGScheduler:
    def __init__(
        self,
        config: Config,
        state_path: Path,
        data_dir: Path,
        notifier: Notifier,
        tz: ZoneInfo,
        _scheduler: BackgroundScheduler | None = None,
    ) -> None:
        self.config = config
        self.state_path = state_path
        self.data_dir = data_dir
        self.notifier = notifier
        self.tz = tz
        self._sched = _scheduler or BackgroundScheduler(timezone=tz)

    def start(self) -> None:
        self._ensure_today_plan()
        self._schedule_today_sets()
        self._add_rollover_job()
        if not self._sched.running:
            self._sched.start()

    def shutdown(self) -> None:
        if self._sched.running:
            self._sched.shutdown(wait=False)

    # ── Callbacks pro AppContext ───────────────────────────────────────────────

    def reschedule(self, new_plan: DayPlan) -> None:
        self._cancel_set_jobs()
        self._schedule_sets(new_plan)

    def cancel_today(self) -> None:
        self._cancel_set_jobs()

    # ── Interní logika ────────────────────────────────────────────────────────

    def _job_id(self, plan_date: str, index: int) -> str:
        return f"{_SET_JOB_PREFIX}{plan_date}_{index}"

    def _cancel_set_jobs(self) -> None:
        from apscheduler.jobstores.base import JobLookupError as ApsJobLookupError

        for job in self._sched.get_jobs():
            if job.id.startswith(_SET_JOB_PREFIX):
                try:
                    job.remove()
                except ApsJobLookupError:
                    pass  # job already fired and self-removed

    def _fire_notification(self, payload: dict) -> None:
        from gtg.models import PlannedSet

        planned_set = PlannedSet(
            index=payload["index"],
            total=payload["total"],
            scheduled_at=datetime.fromisoformat(payload["scheduled_at"]),
            reps=payload["reps"],
        )
        self.notifier.send_set_notification(planned_set)

    def _schedule_sets(self, plan: DayPlan) -> None:
        now = datetime.now(self.tz)
        cutoff = now - timedelta(minutes=_CATCHUP_MINUTES)

        for s in plan.sets:
            if s.scheduled_at < cutoff:
                logger.info("Set #%d (%s) příliš starý — přeskočen", s.index, s.scheduled_at)
                continue

            run_at = s.scheduled_at if s.scheduled_at >= now else now
            payload = {
                "index": s.index,
                "total": s.total,
                "scheduled_at": s.scheduled_at.isoformat(),
                "reps": s.reps,
            }
            self._sched.add_job(
                self._fire_notification,
                trigger=DateTrigger(run_date=run_at),
                id=self._job_id(plan.date, s.index),
                args=[payload],
                replace_existing=True,
            )

    def _ensure_today_plan(self) -> None:
        state = load_state(self.state_path, self.tz)
        if state is None:
            logger.warning("state.json nenalezen — sety se nenaplánují")
            return
        today = date.today().isoformat()
        if state.today_plan is None or state.today_plan.date != today:
            self._rollover()

    def _rollover(self) -> None:
        state = load_state(self.state_path, self.tz)
        if state is None:
            return

        if state.today_plan is not None and not state.today_plan.skipped:
            done_indices = {cs.index for cs in state.completed_sets_today if cs.completed}
            plan = state.today_plan
            for ps in plan.sets:
                if ps.index not in done_indices:
                    skipped = CompletedSet(
                        index=ps.index,
                        total=ps.total,
                        scheduled_at=ps.scheduled_at,
                        completed_at=ps.scheduled_at,
                        reps=ps.reps,
                        completed=False,
                    )
                    append_history(skipped, plan.day_type, plan.date, self.data_dir)

        state.completed_sets_today = []
        state.cycle_position = advance_cycle(state.cycle_position, self.config)

        today = date.today()
        day_type = day_type_for_position(state.cycle_position, self.config)

        if day_type == DayType.REST:
            state.today_plan = None
            logger.info("Dnešek je REST den")
        else:
            state.today_plan = plan_day(today, day_type, state.max_reps, self.config, self.tz)
            logger.info("Nový plán: %s, %d setů", day_type, len(state.today_plan.sets))

        save_state(state, self.state_path)

        if needs_recalibration(state, self.config):
            self.notifier.send_calibration_reminder()

        if state.today_plan:
            self._cancel_set_jobs()
            self._schedule_sets(state.today_plan)

    def _schedule_today_sets(self) -> None:
        state = load_state(self.state_path, self.tz)
        if state and state.today_plan:
            self._schedule_sets(state.today_plan)

    def _add_rollover_job(self) -> None:
        self._sched.add_job(
            self._rollover,
            trigger=CronTrigger(hour=0, minute=1, timezone=self.tz),
            id=_ROLLOVER_JOB_ID,
            replace_existing=True,
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config_path = Path(os.environ.get("GTG_CONFIG", "config.yaml"))
    state_path = Path(os.environ.get("GTG_STATE", "data/state.json"))
    data_dir = Path(os.environ.get("GTG_DATA_DIR", "data"))
    callback_base_url = os.environ.get("GTG_CALLBACK_URL", "http://localhost:8765")
    host = os.environ.get("GTG_HOST", "0.0.0.0")
    port = int(os.environ.get("GTG_PORT", "8765"))

    config = load_config(config_path)
    tz = ZoneInfo(config.timezone)
    data_dir.mkdir(parents=True, exist_ok=True)

    notifier = Notifier(config=config, callback_base_url=callback_base_url)
    gtg = GTGScheduler(
        config=config,
        state_path=state_path,
        data_dir=data_dir,
        notifier=notifier,
        tz=tz,
    )
    gtg.start()

    overview_path = data_dir / "overview.html"
    from gtg.overview import generate as generate_overview
    generate_overview(state_path, data_dir, overview_path, config, tz)

    ctx = AppContext(
        config=config,
        state_path=state_path,
        data_dir=data_dir,
        tz=tz,
        notifier=notifier,
        reschedule_fn=gtg.reschedule,
        cancel_today_fn=gtg.cancel_today,
        overview_path=overview_path,
    )
    app = create_app(ctx)

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        gtg.shutdown()


if __name__ == "__main__":
    main()
