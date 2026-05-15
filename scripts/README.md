# Nasazení na Raspberry Pi

## První instalace

```bash
curl -fsSL https://raw.githubusercontent.com/DeziderMesko/gogtg/main/scripts/setup.sh | bash
```

nebo po ručním nakopírování:

```bash
bash setup.sh
ngrok config add-authtoken <TVUJ_TOKEN>
```

## Spuštění

```bash
~/gogtg/scripts/start.sh
```

Script:
1. Zastaví předchozí instanci (pokud běží)
2. Spustí ngrok a počká až naběhne (max 15 s)
3. Ověří ntfy (`200 OK` nebo varování)
4. Spustí `gtg.scheduler` s `GTG_CALLBACK_URL` nastaveným na ngrok URL

Pro běh na pozadí:

```bash
nohup ~/gogtg/scripts/start.sh > /tmp/gtg-app.log 2>&1 &
```

## Aktualizace

```bash
~/gogtg/scripts/update.sh
```

Provede `git pull` + `uv sync`, pak restartuje aplikaci pokud běžela.

## Poznámka k ngrok

URL se mění při každém restartu (volný plán). Každý restart `start.sh` automaticky zjistí novou URL a předá ji aplikaci — ntfy akce v notifikacích pak budou ukazovat na novou URL. Stará notifikace (před restartem) tedy nebude fungovat.
