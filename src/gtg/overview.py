import calendar
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gtg.models import AppState, Config, DayType
from gtg.scheduling import advance_cycle, base_sets, day_type_for_position, set_reps, sets_for_day
from gtg.storage import load_state

_DAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTH = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_TYPE_LABEL = {
    DayType.LIGHT: "Light",
    DayType.MEDIUM: "Medium",
    DayType.HEAVY: "Heavy",
    DayType.REST: "Rest",
}


@dataclass
class SetStatus:
    tooltip: str
    done: bool
    next_notify: bool = False


@dataclass
class DayRow:
    date: date
    day_type: DayType | None  # None = past day with no history
    sets: list[SetStatus] = field(default_factory=list)
    reps_label: str = ""
    reps_tooltip: str = ""
    next_set_index: int | None = None


# ── Čistá logika ───────────────────────────────────────────────────────────────


def _read_history(data_dir: Path, year: int, month: int) -> dict[str, list[dict]]:
    path = data_dir / "history" / f"{year:04d}-{month:02d}.jsonl"
    out: dict[str, list[dict]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out.setdefault(rec["date"], []).append(rec)
    return out


def _reps_label(reps: dict[str, int], exercise_ids: list[str]) -> str:
    return "/".join(str(reps.get(eid, 0)) for eid in exercise_ids)


def _reps_tooltip(config: Config) -> str:
    return " / ".join(ex.name for ex in config.exercises)


def _day_from_history(d: date, records: list[dict], config: Config) -> DayRow:
    if not records:
        return DayRow(date=d, day_type=None)

    day_type = DayType(records[0]["day_type"])
    set_total: int = records[0]["set_total"]
    done_idx = {r["set_index"] for r in records if r["completed"]}
    reps: dict[str, int] = records[0]["planned_reps"]
    ex_ids = [ex.id for ex in config.exercises]

    sets = []
    for i in range(1, set_total + 1):
        if i in done_idx:
            rec = next(r for r in records if r["set_index"] == i)
            t = rec["time"][:5]
            sets.append(SetStatus(tooltip=f"{t} — done", done=True))
        else:
            sets.append(SetStatus(tooltip="missed", done=False))

    return DayRow(
        date=d,
        day_type=day_type,
        sets=sets,
        reps_label=_reps_label(reps, ex_ids),
        reps_tooltip=_reps_tooltip(config),
    )


def _day_today(
    d: date, state: AppState, config: Config, tz: ZoneInfo, hist_today: list[dict]
) -> DayRow:
    plan = state.today_plan
    if plan is None:
        return DayRow(date=d, day_type=DayType.REST)

    done_by_idx = {cs.index for cs in state.completed_sets_today if cs.completed}
    done_by_idx |= {r["set_index"] for r in hist_today if r["completed"]}
    ex_ids = [ex.id for ex in config.exercises]
    reps = plan.sets[0].reps if plan.sets else {}

    now = datetime.now(tz)
    next_idx = next(
        (ps.index for ps in plan.sets if ps.index not in done_by_idx and ps.scheduled_at > now),
        None,
    )

    sets = []
    for ps in plan.sets:
        t = ps.scheduled_at.astimezone(tz).strftime("%H:%M")
        if ps.index in done_by_idx:
            sets.append(SetStatus(tooltip=f"{t} — done", done=True))
        else:
            sets.append(SetStatus(
                tooltip=f"{t} — scheduled",
                done=False,
                next_notify=(ps.index == next_idx),
            ))

    return DayRow(
        date=d,
        day_type=plan.day_type,
        sets=sets,
        reps_label=_reps_label(reps, ex_ids),
        reps_tooltip=_reps_tooltip(config),
        next_set_index=next_idx,
    )


def _day_past_from_state(d: date, state: AppState, config: Config, tz: ZoneInfo) -> DayRow:
    """Minulý den, jehož plán je stále v state (rollover ještě neproběhl)."""
    plan = state.today_plan
    if plan is None:
        return DayRow(date=d, day_type=None)

    done_by_idx = {cs.index for cs in state.completed_sets_today if cs.completed}
    ex_ids = [ex.id for ex in config.exercises]
    reps = plan.sets[0].reps if plan.sets else {}

    sets = []
    for ps in plan.sets:
        if ps.index in done_by_idx:
            t = ps.scheduled_at.astimezone(tz).strftime("%H:%M")
            sets.append(SetStatus(tooltip=f"{t} — done", done=True))
        else:
            sets.append(SetStatus(tooltip="missed", done=False))

    return DayRow(
        date=d,
        day_type=plan.day_type,
        sets=sets,
        reps_label=_reps_label(reps, ex_ids),
        reps_tooltip=_reps_tooltip(config),
    )


def _day_future(d: date, day_type: DayType, state: AppState, config: Config) -> DayRow:
    if day_type == DayType.REST:
        return DayRow(date=d, day_type=DayType.REST)

    b = base_sets(state.max_reps, config)
    n = sets_for_day(day_type, b)
    reps = set_reps(state.max_reps)
    ex_ids = [ex.id for ex in config.exercises]

    sets = [SetStatus(tooltip="scheduled", done=False) for _ in range(n)]
    return DayRow(
        date=d,
        day_type=day_type,
        sets=sets,
        reps_label=_reps_label(reps, ex_ids),
        reps_tooltip=_reps_tooltip(config),
    )


def build_month_rows(
    state: AppState,
    config: Config,
    tz: ZoneInfo,
    data_dir: Path,
) -> list[DayRow]:
    today = date.today()
    year, month = today.year, today.month
    days_in_month = calendar.monthrange(year, month)[1]
    history = _read_history(data_dir, year, month)

    rows: list[DayRow] = []
    future_pos = state.cycle_position

    for day_num in range(1, days_in_month + 1):
        d = date(year, month, day_num)
        if d < today:
            hist = history.get(d.isoformat(), [])
            if not hist and state.today_plan and state.today_plan.date == d.isoformat():
                rows.append(_day_past_from_state(d, state, config, tz))
            else:
                rows.append(_day_from_history(d, hist, config))
        elif d == today:
            rows.append(_day_today(d, state, config, tz, history.get(today.isoformat(), [])))
        else:
            future_pos = advance_cycle(future_pos, config)
            day_type = day_type_for_position(future_pos, config)
            rows.append(_day_future(d, day_type, state, config))

    return rows


# ── HTML render ───────────────────────────────────────────────────────────────


def _square(s: SetStatus) -> str:
    if s.done:
        char, cls = "■", "sq"
    elif s.next_notify:
        char, cls = "■", "sq next"
    else:
        char, cls = "□", "sq"
    return f'<span class="{cls}" title="{s.tooltip}">{char}</span>'


def _actions_cell(row: DayRow, snooze_options: list[int]) -> str:
    def btn(label: str, url: str, enabled: bool = True) -> str:
        if enabled:
            js = f"fetch('{url}',{{method:'POST'}}).then(()=>location.reload())"
            return f'<button class="act" onclick="{js}">{label}</button>'
        return f'<button class="act" disabled>{label}</button>'

    si = row.next_set_index
    parts = [btn("Done", "/callback/done")]
    for m in snooze_options:
        parts.append(btn(f"Snooze {m}", f"/callback/snooze?set={si}&minutes={m}", si is not None))
    parts.append(btn("Skip day", "/callback/skip"))
    return '<td class="actions">' + " ".join(parts) + "</td>"


def _row_html(row: DayRow, is_today: bool, snooze_options: list[int]) -> str:
    day_abbrev = _DAY[row.date.weekday()]
    day_num = f"{row.date.day}.&nbsp;{row.date.month}."
    bold = ' class="today"' if is_today else ""

    if row.day_type is None:
        type_cell = ""
        sets_cell = '<span class="dash">—</span>'
        reps_cell = ""
    elif row.day_type == DayType.REST:
        type_cell = '<span class="dtype rest">Rest</span>'
        sets_cell = '<span class="dash">—</span>'
        reps_cell = ""
    else:
        lbl = _TYPE_LABEL[row.day_type]
        type_cell = f'<span class="dtype {row.day_type.value}">{lbl}</span>'
        sets_cell = " ".join(_square(s) for s in row.sets)
        reps_cell = f'<span class="reps" title="{row.reps_tooltip}">{row.reps_label}</span>'

    actions_cell = _actions_cell(row, snooze_options) if is_today else "<td></td>"

    return (
        f'  <tr{bold}>\n'
        f'    <td class="dow">{day_abbrev}</td>\n'
        f'    <td class="dnum">{day_num}</td>\n'
        f'    <td>{type_cell}</td>\n'
        f'    <td class="squares">{sets_cell}</td>\n'
        f'    <td>{reps_cell}</td>\n'
        f'    {actions_cell}\n'
        f'  </tr>'
    )


_CSS = """
  body{font-family:sans-serif;font-size:.9rem;padding:1rem 2rem;background:#fff;color:#111;max-width:700px}
  h1{font-size:.9rem;font-weight:bold;margin-bottom:1rem}
  table{border-collapse:collapse}
  td{padding:.15rem .55rem;vertical-align:middle;white-space:nowrap;font-size:.9rem}
  tr.today td{font-weight:bold}
  td.dow{color:#888;min-width:2rem}
  td.dnum{text-align:right;font-variant-numeric:tabular-nums;min-width:3.5rem}
  .dtype{text-transform:uppercase;letter-spacing:.05em;color:#999}
  .dtype.heavy{color:#333}
  .dtype.medium{color:#666}
  .dtype.rest{color:#bbb}
  .squares{letter-spacing:.2em}
  .sq{cursor:default}
  .sq.next{color:#aaa}
  .dash{color:#ccc}
  .reps{font-variant-numeric:tabular-nums;cursor:help;color:#555}
  .actions{padding-left:.8rem}
  .act{font-size:.8rem;padding:.1rem .4rem;margin-right:.2rem;cursor:pointer;border:1px solid #ccc;border-radius:3px;background:#f5f5f5;color:#333}
  .act:hover:not(:disabled){background:#e8e8e8}
  .act:disabled{color:#bbb;cursor:default}
  .legend{margin-top:1.5rem;color:#999;font-size:.85rem}
  .legend span{margin-right:1rem}
  .legend .sq{color:#111}
  .legend .sq.next{color:#aaa}
""".strip()


def render_html(rows: list[DayRow], year: int, month: int, snooze_options: list[int]) -> str:
    title = f"{_MONTH[month]} {year}"
    today = date.today()
    rows_html = "\n".join(_row_html(r, r.date == today, snooze_options) for r in rows)
    return (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        f'<meta charset="UTF-8">\n<title>GTG — {title}</title>\n'
        f'<style>\n{_CSS}\n</style>\n</head>\n<body>\n'
        f'<h1>{title}</h1>\n<table>\n{rows_html}\n</table>\n'
        f'<div class="legend">'
        f'<span><span class="sq">■</span> Done</span>'
        f'<span><span class="sq next">■</span> Next</span>'
        f'<span>□ Scheduled / missed</span>'
        f'</div>\n'
        f'</body>\n</html>\n'
    )


def generate(
    state_path: Path,
    data_dir: Path,
    output_path: Path,
    config: Config,
    tz: ZoneInfo,
) -> None:
    state = load_state(state_path, tz)
    if state is None:
        return
    today = date.today()
    rows = build_month_rows(state, config, tz, data_dir)
    html = render_html(rows, today.year, today.month, config.snooze_options_minutes)
    output_path.write_text(html, encoding="utf-8")
