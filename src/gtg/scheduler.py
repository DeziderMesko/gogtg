import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from gtg.models import CompletedSet, Config, DayPlan, DayType, MaxReps
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
        overview_path: Path | None = None,
        _scheduler: BackgroundScheduler | None = None,
    ) -> None:
        self.config = config
        self.state_path = state_path
        self.data_dir = data_dir
        self.notifier = notifier
        self.tz = tz
        self.overview_path = overview_path
        self._sched = _scheduler or BackgroundScheduler(
            timezone=tz,
            job_defaults={"misfire_grace_time": 600},
        )

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

    def cancel_set(self, plan_date: str, index: int) -> None:
        import contextlib

        from apscheduler.jobstores.base import JobLookupError as ApsJobLookupError

        with contextlib.suppress(ApsJobLookupError):
            self._sched.remove_job(self._job_id(plan_date, index))

    # ── Interní logika ────────────────────────────────────────────────────────

    def _job_id(self, plan_date: str, index: int) -> str:
        return f"{_SET_JOB_PREFIX}{plan_date}_{index}"

    def _cancel_set_jobs(self) -> None:
        import contextlib

        from apscheduler.jobstores.base import JobLookupError as ApsJobLookupError

        for job in self._sched.get_jobs():
            if job.id.startswith(_SET_JOB_PREFIX):
                with contextlib.suppress(ApsJobLookupError):
                    job.remove()

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

        for s in plan.sets:
            if s.scheduled_at <= now:
                logger.info("Set #%d (%s) v minulosti — přeskočen", s.index, s.scheduled_at)
                continue

            payload = {
                "index": s.index,
                "total": s.total,
                "scheduled_at": s.scheduled_at.isoformat(),
                "reps": s.reps,
            }
            self._sched.add_job(
                self._fire_notification,
                trigger=DateTrigger(run_date=s.scheduled_at),
                id=self._job_id(plan.date, s.index),
                args=[payload],
                replace_existing=True,
            )

    def _ensure_today_plan(self) -> None:
        state = load_state(self.state_path, self.tz)
        if state is None:
            logger.warning("state.json nenalezen — sety se nenaplánují")
            return
        today = date.today()

        # Fast path: plán je aktuální
        if state.today_plan and state.today_plan.date == today.isoformat():
            return
        if state.plan_date == today.isoformat():
            return  # REST den — rollover dnes už proběhl

        # Urči datum posledního rolloveru
        if state.plan_date:
            last = date.fromisoformat(state.plan_date)
        elif state.today_plan:
            last = date.fromisoformat(state.today_plan.date)
        else:
            # Stará state.json bez plan_date, today_plan=None (REST nebo první spuštění).
            # Zkontroluj cycle_position: pokud říká REST, rollover proběhl — jen orazítkuj.
            day_type = day_type_for_position(state.cycle_position, self.config)
            if day_type == DayType.REST:
                logger.info("Stará state.json, REST den — razítkuji plan_date bez rolloveru")
                state.plan_date = today.isoformat()
                save_state(state, self.state_path)
                return
            self._rollover(today)
            return

        if last >= today:
            return
        missed = (today - last).days
        if missed > 1:
            logger.info("Zmeškáno %d dní — dohánění rolloveru", missed)
        for i in range(1, missed + 1):
            self._rollover(last + timedelta(days=i))

    def _rollover(self, for_date: date | None = None) -> None:
        state = load_state(self.state_path, self.tz)
        if state is None:
            return

        target = for_date or date.today()

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

        day_type = day_type_for_position(state.cycle_position, self.config)

        if day_type == DayType.REST:
            state.today_plan = None
            logger.info("%s: REST den", target)
        else:
            state.today_plan = plan_day(target, day_type, state.max_reps, self.config, self.tz)
            logger.info("%s: nový plán %s, %d setů", target, day_type, len(state.today_plan.sets))

        state.plan_date = target.isoformat()
        save_state(state, self.state_path)

        if needs_recalibration(state, self.config):
            self.notifier.send_calibration_reminder()

        if state.today_plan and target == date.today():
            self._cancel_set_jobs()
            self._schedule_sets(state.today_plan)

        if target == date.today():
            self._regenerate_overview()

    def _schedule_today_sets(self) -> None:
        state = load_state(self.state_path, self.tz)
        if state and state.today_plan:
            self._schedule_sets(state.today_plan)

    def apply_config(self, new_config: Config, new_max_reps: MaxReps, calibrate: bool) -> None:
        self.config = new_config
        self.notifier.config = new_config

        state = load_state(self.state_path, self.tz)
        if state is None:
            return

        state.max_reps = new_max_reps
        if calibrate:
            state.last_calibration_cycle = state.cycle_position.cycle_number

        if state.today_plan and calibrate:
            today = date.today()
            state.today_plan = plan_day(
                today, state.today_plan.day_type, new_max_reps, new_config, self.tz
            )
            save_state(state, self.state_path)
            self._cancel_set_jobs()
            self._schedule_sets(state.today_plan)
        else:
            save_state(state, self.state_path)

        self._regenerate_overview()

    def _regenerate_overview(self) -> None:
        if self.overview_path is None:
            return
        from gtg.overview import generate as generate_overview

        generate_overview(self.state_path, self.data_dir, self.overview_path, self.config, self.tz)

    def _add_rollover_job(self) -> None:
        self._sched.add_job(
            self._rollover,
            trigger=CronTrigger(hour=0, minute=1, timezone=self.tz),
            id=_ROLLOVER_JOB_ID,
            replace_existing=True,
        )
        self._sched.add_job(
            self._ensure_today_plan,
            trigger=CronTrigger(minute="*/5", timezone=self.tz),
            id="gtg_watchdog",
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
    overview_path = data_dir / "overview.html"
    gtg = GTGScheduler(
        config=config,
        state_path=state_path,
        data_dir=data_dir,
        notifier=notifier,
        tz=tz,
        overview_path=overview_path,
    )
    gtg.start()
    gtg._regenerate_overview()

    ctx = AppContext(
        config=config,
        config_path=config_path,
        state_path=state_path,
        data_dir=data_dir,
        tz=tz,
        notifier=notifier,
        reschedule_fn=gtg.reschedule,
        cancel_today_fn=gtg.cancel_today,
        cancel_set_fn=gtg.cancel_set,
        apply_config_fn=gtg.apply_config,
        overview_path=overview_path,
    )
    app = create_app(ctx)

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        gtg.shutdown()


if __name__ == "__main__":
    main()
