from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from gtg.models import CompletedSet, Config, DayPlan, MaxReps, WindowConfig
from gtg.notifier import Notifier
from gtg.scheduling import nearest_past_uncompleted, reschedule_remaining
from gtg.storage import append_history, load_state, save_config, save_state


@dataclass
class AppContext:
    config: Config
    config_path: Path
    state_path: Path
    data_dir: Path
    tz: ZoneInfo
    notifier: Notifier
    reschedule_fn: Callable[[DayPlan], None]
    cancel_today_fn: Callable[[], None]
    apply_config_fn: Callable[[Config, MaxReps, bool], None]
    overview_path: Path | None = None  # None = overview generation disabled


def _regenerate_overview(ctx: AppContext) -> None:
    if ctx.overview_path is None:
        return
    from gtg.overview import generate

    generate(ctx.state_path, ctx.data_dir, ctx.overview_path, ctx.config, ctx.tz)


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="GTG Reminder")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://ntfy.sh"],
        allow_methods=["POST"],
    )

    @app.post("/callback/done")
    def callback_done(set: int | None = Query(default=None)):
        state = load_state(ctx.state_path, ctx.tz)
        if state is None or state.today_plan is None:
            raise HTTPException(404, "No active plan")

        plan = state.today_plan
        now = datetime.now(ctx.tz)
        done_indices = {cs.index for cs in state.completed_sets_today if cs.completed}
        planned = nearest_past_uncompleted(plan, done_indices, now)
        if planned is None:
            raise HTTPException(404, "No uncompleted past set found")

        completed = CompletedSet(
            index=planned.index,
            total=planned.total,
            scheduled_at=planned.scheduled_at,
            completed_at=now,
            reps=planned.reps,
            completed=True,
        )
        state.completed_sets_today.append(completed)
        append_history(completed, plan.day_type, plan.date, ctx.data_dir)
        save_state(state, ctx.state_path)
        _regenerate_overview(ctx)

        return {"status": "ok", "set": planned.index}

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

    @app.get("/ntfytest")
    def ntfytest():
        state = load_state(ctx.state_path, ctx.tz)
        if state is None or state.today_plan is None or not state.today_plan.sets:
            raise HTTPException(404, "No active plan")
        ctx.notifier.send_set_notification(state.today_plan.sets[0])
        return {"status": "ok"}

    @app.get("/config", response_class=HTMLResponse)
    def config_get():
        state = load_state(ctx.state_path, ctx.tz)
        max_reps = state.max_reps if state else MaxReps(oap=0, ols=0, pullup=0)
        c = ctx.config
        snooze = ", ".join(str(m) for m in c.snooze_options_minutes)
        return _render_config_form(c, max_reps, snooze)

    @app.post("/config")
    def config_post(
        action: str = Form(...),
        max_reps_oap: int = Form(...),
        max_reps_ols: int = Form(...),
        max_reps_pullup: int = Form(...),
        window_start: str = Form(...),
        window_end: str = Form(...),
        window_max_extension_hours: int = Form(...),
        min_gap_minutes: int = Form(...),
        daily_reps_target_min: int = Form(...),
        daily_reps_target_max: int = Form(...),
        work_days: int = Form(...),
        rest_days: int = Form(...),
        recalibrate_after_cycles: int = Form(...),
        snooze_options: str = Form(...),
        ntfy_base_url: str = Form(...),
        ntfy_topic: str = Form(...),
        timezone: str = Form(...),
    ):
        def _parse_time(s: str) -> time:
            h, m = map(int, s.split(":"))
            return time(h, m)

        new_config = Config(
            window=WindowConfig(
                start=_parse_time(window_start),
                end=_parse_time(window_end),
                max_extension_hours=window_max_extension_hours,
            ),
            min_gap_minutes=min_gap_minutes,
            daily_reps_target_min=daily_reps_target_min,
            daily_reps_target_max=daily_reps_target_max,
            work_days=work_days,
            rest_days=rest_days,
            recalibrate_after_cycles=recalibrate_after_cycles,
            snooze_options_minutes=[int(x.strip()) for x in snooze_options.split(",") if x.strip()],
            ntfy_base_url=ntfy_base_url.rstrip("/"),
            ntfy_topic=ntfy_topic.strip(),
            exercises=ctx.config.exercises,
            timezone=timezone.strip(),
        )
        new_max_reps = MaxReps(oap=max_reps_oap, ols=max_reps_ols, pullup=max_reps_pullup)

        save_config(ctx.config_path, new_config)
        ctx.config = new_config
        ctx.notifier.config = new_config

        calibrate = action == "calibrate"
        ctx.apply_config_fn(new_config, new_max_reps, calibrate)

        return RedirectResponse("/config", status_code=303)

    return app


_CONFIG_CSS = """
body{font-family:sans-serif;max-width:600px;margin:2rem auto;padding:0 1rem}
h1{font-size:1.3rem}
h2{font-size:.95rem;margin-top:1.5rem;color:#666;border-bottom:1px solid #eee;padding-bottom:.2rem}
label{display:block;margin-top:.8rem;font-size:.88rem;color:#444}
input{width:100%;box-sizing:border-box;padding:.35rem .5rem;border:1px solid #ccc;
      border-radius:3px;font-size:.92rem;margin-top:.2rem}
.actions{margin-top:2rem;display:flex;gap:.8rem}
.btn{padding:.5rem 1.4rem;border:1px solid #ccc;border-radius:3px;cursor:pointer;
     font-size:.92rem;background:#f5f5f5;color:#333}
.btn-primary{background:#4a90d9;color:#fff;border-color:#3a7bc8}
""".strip()


def _render_config_form(c: Config, max_reps: MaxReps, snooze: str) -> str:
    def field(label: str, name: str, value: object, type_: str = "text") -> str:
        return f'<label>{label}<input name="{name}" type="{type_}" value="{value}"></label>'

    ws = c.window.start.strftime("%H:%M")
    we = c.window.end.strftime("%H:%M")

    body = "\n".join(
        [
            "<h2>Max reps</h2>",
            field("OAP", "max_reps_oap", max_reps.oap, "number"),
            field("OLS", "max_reps_ols", max_reps.ols, "number"),
            field("Pull-ups", "max_reps_pullup", max_reps.pullup, "number"),
            "<h2>Training window</h2>",
            field("Start", "window_start", ws, "time"),
            field("End", "window_end", we, "time"),
            field(
                "Max extension (hours)",
                "window_max_extension_hours",
                c.window.max_extension_hours,
                "number",
            ),
            "<h2>Scheduling</h2>",
            field("Min gap between sets (min)", "min_gap_minutes", c.min_gap_minutes, "number"),
            field(
                "Daily reps target — min",
                "daily_reps_target_min",
                c.daily_reps_target_min,
                "number",
            ),
            field(
                "Daily reps target — max",
                "daily_reps_target_max",
                c.daily_reps_target_max,
                "number",
            ),
            "<h2>Cycle</h2>",
            field("Work days", "work_days", c.work_days, "number"),
            field("Rest days", "rest_days", c.rest_days, "number"),
            field(
                "Recalibrate after N cycles",
                "recalibrate_after_cycles",
                c.recalibrate_after_cycles,
                "number",
            ),
            "<h2>Snooze</h2>",
            field("Options (minutes, comma-separated)", "snooze_options", snooze),
            "<h2>Notifications</h2>",
            field("ntfy base URL", "ntfy_base_url", c.ntfy_base_url),
            field("ntfy topic", "ntfy_topic", c.ntfy_topic),
            "<h2>Other</h2>",
            field("Timezone", "timezone", c.timezone),
            '<div class="actions">',
            '<button class="btn" type="submit" name="action" value="save">Save</button>',
            '<button class="btn btn-primary" type="submit"'
            ' name="action" value="calibrate">Save &amp; Calibrate</button>',
            "</div>",
        ]
    )

    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n<title>GTG — Config</title>\n'
        f"<style>\n{_CONFIG_CSS}\n</style>\n</head>\n<body>\n"
        "<h1>GTG — Configuration</h1>\n"
        f'<form method="post" action="/config">\n{body}\n</form>\n'
        "</body>\n</html>\n"
    )
