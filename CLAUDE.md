# GTG Reminder — pokyny pro Claude Code

## O projektu

Osobní aplikace pro řízení Grease the Groove tréninku (StrongFirst metodika).
Plánuje série cviků (OAP / OLS / shyb) během dne, posílá notifikace přes ntfy,
ukládá historii do JSON. Plná specifikace je v `docs/spec.md` — vždy ji ber jako zdroj pravdy.

## Komunikace

- Čeština, tykání.
- Stručné odpovědi, žádné rozsáhlé úvody.
- Když si nejsi jistý zadáním, zeptej se — neimprovizuj.

## Technologický stack

- **Python 3.11+**, type hints všude.
- **Balíčkovač:** `uv` (preferovaný). Pokud není, fallback `pip` + `venv`.
- **Hlavní knihovny:** `apscheduler`, `fastapi`, `uvicorn`, `httpx`, `pyyaml`, `jsonlines`.
- **Testy:** `pytest`, `pytest-asyncio`. Pure-funkční logika (plánování, vlnění) musí být testovaná.
- **Lint/format:** `ruff` (lint + format v jednom).
- **Žádná databáze.** Persistence přes JSON soubory — viz spec.md sekce 4.

## Konvence kódu

- Funkční jádro × IO okraj: logika plánování a vlnění je čistá (žádné IO uvnitř), IO se děje v tenké vrstvě nad ní.
- Snake_case pro proměnné a funkce, PascalCase pro třídy.
- Dataclasses (nebo `pydantic` modely) pro datové struktury, ne raw dicty mimo IO vrstvu.
- Časy interně v `datetime` s tzinfo (Europe/Prague), serializace do ISO 8601.
- Žádné globální stavy. Konfigurace přes instance, ne moduly.

## Struktura repozitáře

Cíl (postupně se naplní):

```
gtg-reminder/
├── docs/spec.md
├── src/gtg/
│   ├── models.py           # datové struktury (Set, Day, Cycle, Config)
│   ├── scheduling.py       # čistá logika: vygeneruj plán dne, vlnění, snooze
│   ├── storage.py          # IO: state.json, history/*.jsonl, atomic write
│   ├── notifier.py         # ntfy klient
│   ├── scheduler.py        # APScheduler runtime
│   ├── server.py           # FastAPI endpointy pro callbacks z notifikací
│   └── overview.py         # generator HTML přehledu měsíce
├── tests/
├── data/                   # state.json + history/ (gitignored)
├── config.yaml             # uživatelská konfigurace
├── pyproject.toml
└── README.md
```

## Postup vývoje (preferovaný)

1. Modely + storage helpery (atomic write, JSONL append).
2. Čistá logika plánování (`scheduling.py`) + unit testy.
3. Notifier (ntfy klient, jednoduchý POST).
4. FastAPI server s callbacky.
5. APScheduler runtime, propojení všeho.
6. Snooze a přeplánování.
7. Overview HTML generator.

Po každém kroku: testy zelené, ruff čistý, commit.

## Co nedělat

- Nepřidávat SQLite nebo jinou DB.
- Nepřidávat frontend framework (React, Vue) — overview je statické HTML generované Pythonem.
- Nezavádět asynchronní komplexnost tam, kde stačí synchronní kód (notifier, storage).
- Nepřepisovat spec — pokud se v průběhu ukáže, že něco ve spec nesedí, nahlas to a počkej na rozhodnutí.

## Příkazy

- Spuštění testů: `uv run pytest`
- Lint + format: `uv run ruff check . && uv run ruff format .`
- Lokální dev server: `uv run uvicorn gtg.server:app --reload --port 8765`
- Spuštění scheduleru: `uv run python -m gtg.scheduler`
