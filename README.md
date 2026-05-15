# GTG Reminder

Aplikace pro řízení **Grease the Groove** tréninku — během dne připomíná
cvičení (OAP / jednonožní dřep / shyb), hlídá odstupy a denní objem, mění
intenzitu mezi dny podle vlnění light → heavy → medium → rest.

Notifikace přes [ntfy.sh](https://ntfy.sh) (Android + Garmin), persistence
v JSON souborech. Plná specifikace v [`docs/spec.md`](docs/spec.md).

---

## Požadavky

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) (doporučeno) nebo `pip`
- Účet na ntfy.sh (nebo vlastní ntfy instance)
- [ngrok](https://ngrok.com) pro callback notifikací

---

## Instalace

```bash
git clone https://github.com/DeziderMesko/gogtg.git
cd gogtg
uv sync
```

---

## Konfigurace

Zkopíruj a uprav `config.yaml`:

```yaml
window:
  start: "08:00"        # začátek aktivního okna
  end: "16:00"          # konec okna; snooze může prodloužit o max_extension_hours
  max_extension_hours: 2

scheduling:
  min_gap_minutes: 15
  daily_reps_target:
    min: 15
    max: 30

cycle:
  work_days: 3          # 3 cvičební dny → 1 den odpočinku
  rest_days: 1
  recalibrate_after_cycles: 2   # po 2 cyklech (8 dnech) vyzve k novému max reps

snooze_options_minutes: [15, 30, 60]

ntfy:
  base_url: "https://ntfy.sh"
  topic: "tvuj-unikatni-topic"   # ← změň na vlastní

exercises:
  - id: oap
    name: "OAP"
    unit: reps
  - id: ols
    name: "OLS"
    unit: reps
  - id: pullup
    name: "Shyb"
    unit: reps

timezone: "Europe/Prague"
```

---

## Inicializace stavu

Před prvním spuštěním vytvoř `data/state.json` se svými aktuálními maximy:

```json
{
  "max_reps": { "oap": 3, "ols": 5, "pullup": 6 },
  "cycle_position": { "cycle_number": 0, "day_in_cycle": 0 },
  "today_plan": null,
  "completed_sets_today": [],
  "last_calibration_cycle": 0
}
```

---

## Spuštění

### Env proměnné

| Proměnná | Výchozí | Popis |
|---|---|---|
| `GTG_CONFIG` | `config.yaml` | cesta ke konfiguračnímu souboru |
| `GTG_STATE` | `data/state.json` | cesta ke stavu aplikace |
| `GTG_DATA_DIR` | `data` | složka s historií a overview.html |
| `GTG_CALLBACK_URL` | `http://localhost:8765` | veřejná URL serveru (tunel) |
| `GTG_HOST` | `0.0.0.0` | bind adresa FastAPI serveru |
| `GTG_PORT` | `8765` | port FastAPI serveru |

### Lokálně (bez tunelu — pro testování)

```bash
uv run python -m gtg.scheduler
```

### Na Raspberry Pi (ngrok)

Viz [`scripts/README.md`](scripts/README.md) — skripty pro jednorázovou instalaci,
spuštění s ngrok a aktualizaci přes `git pull`.

---

## Datové soubory

```
data/
  state.json          # živý stav: max reps, dnešní plán, pozice v cyklu
  overview.html       # měsíční přehled (přegeneruje se po každém setu)
  history/
    2026-05.jsonl     # append-only log splněných setů
    2026-06.jsonl
```

`state.json` se přepisuje atomicky (write tmp + rename). `history/*.jsonl` je
append-only — každý řádek je jeden splněný set. Oboje je čitelné textovým
editorem.

---

## Měsíční přehled

Po každém záznamu setu se přegeneruje `data/overview.html`. Otevři ji
v prohlížeči a refreshuj pro aktuální stav.

---

## Vývoj a testování

```bash
# Testy
uv run pytest

# Lint + format
uv run ruff check . && uv run ruff format .

# Pouze dev server (bez scheduleru)
uv run uvicorn gtg.server:app --reload --port 8765
```
