from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from gtg.models import CompletedSet, Config, DayPlan
from gtg.notifier import Notifier
from gtg.scheduling import reschedule_remaining
from gtg.storage import append_history, load_state, save_state


@dataclass
class AppContext:
    config: Config
    state_path: Path
    data_dir: Path
    tz: ZoneInfo
    notifier: Notifier
    reschedule_fn: Callable[[DayPlan], None]
    cancel_today_fn: Callable[[], None]
    overview_path: Path | None = None  # None = overview generation disabled


def _regenerate_overview(ctx: AppContext) -> None:
    if ctx.overview_path is None:
        return
    from gtg.overview import generate
    from zoneinfo import ZoneInfo
    generate(ctx.state_path, ctx.data_dir, ctx.overview_path, ctx.config, ctx.tz)


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="GTG Reminder")

    @app.post("/callback/done")
    def callback_done(set: int = Query(...)):
        state = load_state(ctx.state_path, ctx.tz)
        if state is None or state.today_plan is None:
            raise HTTPException(404, "No active plan")

        plan = state.today_plan
        planned = next((s for s in plan.sets if s.index == set), None)
        if planned is None:
            raise HTTPException(404, f"Set {set} not in plan")

        now = datetime.now(ctx.tz)
        completed = CompletedSet(
            index=planned.index,
            total=planned.total,
            scheduled_at=planned.scheduled_at,
            completed_at=now,
            reps=planned.reps,
            completed=True,
        )
        state.completed_sets_today.append(completed)
        append_history(completed, plan.day_type, ctx.data_dir)
        save_state(state, ctx.state_path)
        _regenerate_overview(ctx)

        return {"status": "ok", "set": set}

    @app.post("/callback/snooze")
    def callback_snooze(set: int = Query(...), minutes: int = Query(...)):
        if minutes not in ctx.config.snooze_options_minutes:
            raise HTTPException(400, f"Invalid snooze duration: {minutes}")

        state = load_state(ctx.state_path, ctx.tz)
        if state is None or state.today_plan is None:
            raise HTTPException(404, "No active plan")

        now = datetime.now(ctx.tz)
        new_plan = reschedule_remaining(set, minutes, state.today_plan, ctx.config, now)
        state.today_plan = new_plan
        save_state(state, ctx.state_path)
        ctx.reschedule_fn(new_plan)
        _regenerate_overview(ctx)

        return {"status": "ok", "snoozed_minutes": minutes}

    @app.post("/callback/skip")
    def callback_skip():
        state = load_state(ctx.state_path, ctx.tz)
        if state is None or state.today_plan is None:
            raise HTTPException(404, "No active plan")

        state.today_plan.skipped = True
        save_state(state, ctx.state_path)
        ctx.cancel_today_fn()
        ctx.notifier.send_skip_confirmation()
        _regenerate_overview(ctx)

        return {"status": "ok"}

    @app.get("/overview", response_class=HTMLResponse)
    def overview():
        if ctx.overview_path is None or not ctx.overview_path.exists():
            raise HTTPException(404, "Overview not generated yet")
        return ctx.overview_path.read_text(encoding="utf-8")

    return app
