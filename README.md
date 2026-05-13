# GTG Reminder

Aplikace pro řízení **Grease the Groove** tréninku — během dne připomíná
cvičení (OAP / jednonožní dřep / shyb), hlídá odstupy a denní objem, mění
intenzitu mezi dny podle vlnění light → heavy → medium → rest.

Notifikace přes [ntfy.sh](https://ntfy.sh) (Android + Garmin), persistence
v JSON souborech. Plná specifikace v [`docs/spec.md`](docs/spec.md).

## Spuštění

```bash
uv sync
uv run python -m gtg.scheduler
```

## Konfigurace

`config.yaml` — okno dne, denní cíle, snooze intervaly, ntfy topic.
