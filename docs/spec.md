# Specifikace: GTG Reminder

Aplikace pro podporu metody Grease the Groove (GTG) podle StrongFirst — chytrý plánovač cvičení s notifikacemi, snoozem a vlněním intenzity přes týdenní cyklus.

**Autor:** Dežo
**Verze:** 1.0
**Datum:** 2026-05-13

---

## 1. Cíl a kontext

Grease the Groove je metoda Pavla Tsatsouline pro budování dovednostně-silových cviků (one-arm pushup, pull-up, pistol squat). Princip: během dne dělat malé série daleko od selhání, často, **vždy svěží**. Aplikace má tento režim řídit — připomenout cvičení, dodržet odstup, hlídat denní objem a měnit intenzitu mezi dny.

Cvičené pohyby: **OAP (one-arm pushup), jednonožní dřep (pistol), shyb / vis** (postupně přejde na shyby).

---

## 2. Funkční požadavky

### 2.1 Časové okno a frekvence

- Aktivní okno během dne: **08:00–16:00** (výchozí; **konfigurovatelné** — start, konec).
- **Maximální rozšíření okna při snoozu: +2 hodiny** za konec okna (např. výchozí konec 16:00 → max 18:00). Konfigurovatelné.
- **Minimální odstup mezi sety: 15 minut** (konfigurovatelné).
- **Cílový počet setů za den: 4–8** (viz vlnění níže).
- Cvičení probíhá **každý den v týdnu (7 dní)**.

### 2.2 Struktura setu (superset)

Každý naplánovaný set obsahuje všechny tři cviky v supersetu (jeden po druhém, krátká pauza mezi cviky uvnitř supersetu):

1. OAP — N opakování
2. Jednonožní dřep — N opakování (na každou nohu)
3. Shyb / vis — N opakování (nebo N sekund visu)

Počet opakování v setu se odvozuje od maximálního počtu opakování (max reps) na cvik — viz vlnění.

### 2.3 Max reps a cykly

- Uživatel zadá **max reps** pro každý cvik (počet opakování v jednom setu na hranici, ale **bez selhání**).
- **Cyklus:** 3 dny cvičení → 1 den odpočinku.
- Po **dvou cyklech** (= 8 kalendářních dnů) aplikace **vyzve k novému zadání max reps** (test/aktualizace).
- Během cvičebních dnů: **každý set = max ⌊½ × max_reps⌋** na daný cvik. (Tj. nikdy nepřesáhne polovinu maxima, v duchu *Naked Warrior*.)

### 2.4 Vlnění (light / medium / heavy)

V rámci 3 cvičebních dnů cyklu rotují tři úrovně objemu (počet **setů za den**):

| Den v cyklu | Úroveň | Počet setů |
|-------------|--------|------------|
| 1 | Light  | base × 0.8 |
| 2 | Heavy  | base × 1.2 |
| 3 | Medium | base |
| 4 | Rest   | 0 (jen klid) |

`base` se volí tak, aby celkový denní počet opakování **per cvik** byl **15–30**. Při ½ max reps = `base ≈ ⌈denní_cíl / (½ × max_reps)⌉`. Heavy/light dny zachovají rozdíl ~20 % v počtu setů oproti medium.

Pořadí light → heavy → medium uvnitř cyklu je výchozí.

### 2.5 Plánování setů během dne

- Po startu dne aplikace **rozloží N setů rovnoměrně** do okna 08:00–16:00 s tím, že odstup ≥ 15 min.
- Při odstupu menším, než dovoluje okno (např. 8 setů × min. 15 min = 105 min, dost), počítá s rezervou.
- Konkrétní časy notifikací jsou **plovoucí** — viz snooze.

### 2.6 Notifikace

- V naplánovaném čase aplikace pošle **push notifikaci** s informací:
  - „Čas na GTG set #X z Y. OAP: 3 / Pistol: 2 / Shyb: 1."
- Notifikace nabízí **akce**:
  - ✅ **Hotovo** — zaznamená set, naplánuje další.
  - ⏸️ **Snooze 15 min**
  - ⏸️ **Snooze 30 min**
  - ⏸️ **Snooze 60 min**
  - ❌ **Skip dnešek** (pouze pro celý den, ne pro jednotlivý set).

### 2.7 Snooze a přeplánování

Při snoozu aplikace:

1. Posune aktuální set o zvolený interval.
2. **Přepočítá zbývající sety dne** tak, aby:
   - Dodržela minimální odstup 15 min.
   - Zachovala denní cíl (počet setů). Pokud se do konce okna nevejdou, povolí **rozšíření okna o max 2 hodiny** (konfigurovatelné).
   - Pokud se ani tak nevejdou, **zachová maximum setů možných** a varuje, že denní cíl nebude splněn.

### 2.8 Záznam splnění

- Po každé akci „Hotovo" se uloží: datum, čas, číslo setu, plánované opakování per cvik.
- **Žádné RPE, žádné poznámky** — jen splnil/nesplnil.
- **Skip dnešek** označí den jako přerušený; cyklus se posune (rest day se nepřesouvá, prostě dnes nic).

### 2.9 Export dat

- Export celé historie do **CSV** a **JSON**.
- Pole: `date`, `time`, `set_index`, `set_total`, `exercise`, `planned_reps`, `completed` (bool), `day_type` (light/medium/heavy/rest).

### 2.10 Měsíční přehled (overview stránka)

Statická HTML stránka generovaná skriptem, zobrazující aktuální měsíc — jeden řádek na den.

**Layout řádku (zleva doprava):**

1. **Datum** ve formátu `Pá 1. 5.` (zkratka dne v týdnu + den + měsíc). Dnešní den je vizuálně zvýrazněný (tučně / tmavší).
2. **Štítek úrovně dne** — `Light` / `Medium` / `Heavy` / `Rest` (malá uppercase písmena, sekundární barva).
3. **Řada čtverečků** — jeden čtvereček per naplánovaný set v daném dni:
   - **Plný čtvereček** = set splněn.
   - **Prázdný čtvereček s obrysem** = naplánovaný (budoucí), nebo nesplněný (minulost).
   - **Tooltip nad čtverečkem** (atribut `title`) zobrazuje **čas setu a stav**, např. `09:00 — splněno`, `10:45 — naplánováno`, `14:15 — nesplněno`.
4. **Popisek opakování** — kompaktní formát `3/3/2` (počet reps OAP / OLS / Shyb v jednom setu daného dne).
   - **Tooltip nad popiskem** zobrazuje, ke kterým cvikům se čísla vztahují: `OAP / OLS / Shyb`.
   - Vizuální náznak hoveru: kurzor `help` (otazník).
5. **Rest day** — místo čtverečků a popisku se zobrazí jen pomlčka `—`.

**Záhlaví stránky:**

- Název měsíce a rok (`Květen 2026`).

**Patička stránky — legenda:**

- Plný čtvereček = Splněno.
- Prázdný čtvereček = Naplánováno / nesplněno.

**Generování:**

- Skript `overview.py` (nebo `generate_overview.py`) čte `state.json` a `history/YYYY-MM.jsonl` aktuálního měsíce, vyrenderuje **statickou HTML stránku** do `data/overview.html`.
- Stránka **není interaktivní** (žádné kliky, žádný JS pro fetch dat) — pouze CSS tooltipy přes `title` atribut.
- Stránka se přegeneruje:
  - Po každém záznamu setu (callback z notifikace).
  - Po přeplánování dne (snooze).
  - Volitelně cron/scheduled task každou hodinu jako pojistka.
- Stránka může být otevřená v prohlížeči — po refresh zobrazí aktuální stav.

**Vizuální styl:**

- Minimalistický, žádné barvy navíc (jen plný vs prázdný čtvereček).
- Použít `font-variant-numeric: tabular-nums` na popisku `3/3/2` pro zarovnání čísel.
- Bezserifové písmo, monospace pouze pro popisek reps (volitelné).

---

## 3. Nefunkční požadavky

- **Spolehlivost notifikací** — pokud cílová platforma notifikaci nedoručí (offline telefon), naplánované sety se po obnovení připomenou (catch-up: pokud zmeškaný set < 30 min, jinak posun do dalšího slotu).
- **Persistence stavu** — všechen stav (max reps, dnešní plán, historie) přežívá restart služby/zařízení.
- **Časová zóna** — Europe/Prague.
- **Konfigurovatelnost** — okno dne, denní cíl, délky snoozu, délka cyklu by měly být v konfigu, ne v kódu.
- **Soukromí** — vše lokálně, žádný cloud kromě tunelu pro push notifikace (ntfy / Pushover).

---

## 4. Implementační volba — vyměnitelná vrstva

Tahle sekce je **kandidátem na výměnu**, pokud něco z níže uvedeného nebude vyhovovat. Funkční specifikace v sekci 2 zůstává nezávislá.

### 4.1 Doporučené řešení: Python + ntfy.sh (nebo Pushover)

**Komponenty:**

| Vrstva | Volba | Poznámka |
|--------|-------|----------|
| Runtime | Python 3.11+ na Windows (jako Scheduled Task nebo služba přes NSSM) | Případně RaspberryPi pro 24/7 |
| Plánovač | `APScheduler` s `MemoryJobStore` | Jobs se přegenerují při startu ze `state.json` |
| Persistence | **JSON / JSON Lines soubory** | Bez DB; vše čitelné textovým editorem |
| Notifikace | **ntfy.sh** (self-hosted nebo public) — actionable notifications | Alternativa: Pushover ($5 jednorázově, robustnější) |
| Garmin | Notifikace na telefon → Garmin Connect zrcadlí na hodinky | Žádná dedikovaná Garmin app potřeba |
| Konfigurace | `config.yaml` | Editovatelný textákem |
| Export | Python skript `export.py --format csv\|json` | Čte JSONL, vypisuje CSV nebo agregovaný JSON |

**Struktura datových souborů:**

```
data/
  config.yaml          # statická konfigurace (okno, snooze, cíle)
  state.json           # živý stav: max reps, dnešní plán, pozice v cyklu
  history/
    2026-05.jsonl      # append-only log splněných setů, jeden řádek = jeden záznam
    2026-06.jsonl
```

**Proč JSON / JSONL místo SQLite:**

- Objem dat je triviální (~9 000 záznamů/rok, < 1 MB).
- Jeden proces, sekvenční zápis — žádné race conditions.
- `state.json` je malý a přepisuje se atomicky (write to tmp + rename).
- `history/*.jsonl` je append-only — zápis = jeden řádek na konec souboru, bez parsování celku.
- Měsíční rozdělení historie drží soubory malé a usnadňuje zálohu.
- Čitelné textovým editorem, snadné ruční opravy, dobré pro git verzování.
- Export do CSV = jeden průchod přes `jsonlines` knihovnu.

**Tok:**

1. `scheduler.py` běží na pozadí (Windows Task Scheduler spustí při loginu, nebo NSSM jako služba).
2. Při startu načte `state.json` a podle něj přegeneruje jobs do APScheduler (`MemoryJobStore`).
3. V čase setu POST na `ntfy.sh/<tvuj-topic>` s actionable buttons.
4. Akce z notifikace volá HTTP endpoint malého Flask/FastAPI serveru (lokálně na `localhost:8765`, exposed přes reverse tunel — Cloudflare Tunnel nebo ngrok — pokud nejsi v lokální síti).
5. Server zaeviduje akci: append do `history/YYYY-MM.jsonl`, update `state.json` (atomic write přes tmp + rename), přeplánuje zbytek dne v APScheduleru.

**Proč ntfy:**
- Self-hostable (kontrola dat).
- Actionable notifications zdarma.
- Funguje s každým Androidem; nevyžaduje Google.

**Proč Pushover (alternativa):**
- Velmi spolehlivý, robustní iOS i Android client.
- $5 jednorázově, žádné účty.
- Actionable: částečně (vyžaduje custom URL endpoint).

### 4.2 Záložní možnosti při změně technologie

Pokud Python + ntfy z nějakého důvodu nebude fungovat, lze nahradit za:

- **Home Assistant** — pokud bude k dispozici. Automatizace + Companion app na Androidu zvládne všechno, co je v sekci 2.
- **PWA** — webová aplikace s Web Push API. Funguje na Android (notifikace přes prohlížeč Chrome), na Windows méně spolehlivě.
- **n8n / Node-RED** — pokud chceš no-code/low-code workflow engine místo Pythonu.
- **Tasker (Android)** — pokud bys chtěl jen Android-only řešení s lokálním plánováním.

V každé variantě **zůstává specifikace sekce 2 platná**; mění se jen technologická vrstva.

---

## 5. Akceptační kritéria (MVP)

- [ ] Po zadání max reps a startu dne aplikace vygeneruje plán setů s odstupem ≥ 15 min v okně 08:00–16:00.
- [ ] Notifikace dorazí na Android telefon i do Garmin hodinek.
- [ ] Snooze 15/30/60 přeplánuje zbytek dne tak, aby odstupy a cíl byly dodrženy (pokud možno).
- [ ] Týdenní vlnění funguje: medium → light → heavy → rest, opakovaně 2× = výzva k novému zadání max reps.
- [ ] Historie se ukládá a jde exportovat do CSV i JSON.
- [ ] Stav přežije restart počítače.
- [ ] Měsíční overview stránka se generuje a zobrazuje všechny dny aktuálního měsíce s naplánovanými / splněnými sety a tooltipy.

---

## 6. Otevřené otázky / budoucí rozšíření

- **Postupná progrese:** později nahradit shyb/vis za standardní shyby — schéma cviků by mělo umožňovat „upgrade" cviku bez ztráty historie.
- **Více pohybů v rotaci:** dnes superset všech 3, později možná A/B den.
- **Integrace s Garmin Connect:** zapisovat sety jako manual activity (zatím není potřeba).
- **Notifikace přes Slack / Discord:** alternativní kanál, pokud by ntfy nevyhovoval.
- **Vizualizace progrese:** týdenní/měsíční graf objemu (zatím out of scope, data v CSV stačí).
