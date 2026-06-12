# How everything works — feature reference

The complete reference for every feature: what runs when, the exact rules and thresholds, where data lives and what happens when something fails. Setup guides live in the other docs; this explains behaviour.

```
You (Telegram) ──→ GitHub Actions (scripts) ──→ Google Sheets ──→ dashboard / reports / Google Doc
Garmin ──→ intervals.icu ──⇄ GitHub Actions        (read: sport + wellness · write: weight + nutrition)
cron-job.org ──→ triggers every workflow at exact times
```

**Failure philosophy:** every integration fails silently. No intervals.icu key, an API outage, a missing custom field — meal processing, weight logging and reminders always keep working; you just miss that one enrichment. Look for lines starting with `intervals.icu:` in the Actions log when something seems off.

## The daily runs

### 07:00 — Morning question (`gewicht_vraag.py`)
Sends "Wat is je gewicht vandaag?". Nothing else — deliberately no recovery context here, because wake-up times vary and the overnight Garmin sync isn't guaranteed to have completed yet.

### 15:00 — Weight check (`gewicht_check.py`)
1. Scans today's Telegram messages for a bare number between 30–200 (optionally followed by `kg`/`kilo`). Messages like "200 gram rijst" don't match. The *latest* number of the day wins.
2. Saves it to the `Gewicht` tab and **uploads it to intervals.icu** (`weight` in the wellness record), so W/kg, eFTP and power stats there always match your morning weight. Confirmed in Telegram with 📤.
3. **Recovery check**: if your HRV has been below its 7-day baseline for `hrv_alert_dagen` (default 3) consecutive nights *and* your average resting HR over those nights is at least `rhr_alert_boven_baseline` (default +3 bpm) above its baseline, you get a one-time 🟠 warning suggesting a rest day. It fires only on the first day the condition becomes true (it re-evaluates yesterday: if the alert was already true then, it stays silent) and needs at least 4 baseline nights of data to judge at all.

### 21:00 — Smart reminder (`remind.py`)
- Already logged food → shows how many messages, which meal slots are covered (🌅☀️🌙🍎), an estimated kcal total so far and your remaining budget against the **dynamic day goal** (see Sport below).
- Logged nothing → friendly generic reminder, plus a 🚴 line if you did sport today ("eet voldoende terug!").
- **Carb advice**: if tomorrow's intervals.icu calendar contains a planned workout with load ≥ `tss_zware_dag` or ≥ 90 minutes, a 📅 line recommends extra carbs tonight. Silent while the calendar is unused.
- Any error in the smart path → falls back to the plain generic reminder. The reminder never silently disappears.

### 23:58 — Day processing (`process_food.py`)
The core run, deliberately *before* midnight (the row gets today's date, and Telegram only keeps unconfirmed messages 24h).

1. **Collects** all of today's Telegram messages. Excluded: `/commands`, recipe additions, and bare numbers (those are weights).
2. **Weight catch-net**: a weight sent after 15:00 is saved now (with a duplicate check against the Gewicht tab) and uploaded to intervals.icu.
3. **Sport**: fetches today's *and yesterday's* activities from intervals.icu (yesterday catches activities that synced after the previous run). All go to the `Sport` tab — Apps Script dedupes on the Intervals ID, so nothing is ever double. Today's burned kcal set the **dynamic day goal**: `kcal-doel + sport_compensatie × burned kcal`.
4. **Wellness**: fetches last night's HRV/RHR/sleep/readiness and upserts the last two days into the `Wellness` tab (one row per date, updated in place).
5. **AI analysis** (Groq, llama-3.3-70b): estimates kcal and macros per meal slot using Belgian portion sizes. Recipes from `recepten.json` recognised in your text are used with their *exact* values instead of estimates. The prompt includes the dynamic day goal, last night's recovery and — on heavy training days (load ≥ `tss_zware_dag`) — a protein goal raised by `eiwit_extra_g`. The 1–10 score is judged against those adjusted goals.
6. **Telegram summary**: per-meal breakdown, 🚴 sport block with the goal calculation (e.g. "2750 + 824 = 3574 kcal"), 💪 protein line on heavy days, totals, score and an AI note. A score below 5 triggers an extra concrete tip for tomorrow.
7. **Storage**: one row in `Maaltijden` (incl. per-meal kcal and the day's sport kcal) — the streak counter only looks at this tab.
8. **Write-back to intervals.icu** (after the Telegram flow is fully done): kcal intake into the wellness field `kcal_veld`, score/protein into your custom fields, the day summary as a 🍽️ calendar NOTE (upserted — re-runs update it, other notes are untouched) and a fueling line on each of today's activities ("Gevoed: 2800 kcal · 150g eiwit (score 8/10)" — your own description text is preserved, an old Gevoed line is replaced).

### Every 10 minutes — `/tips` (`tips.py`)
On `/tips`: estimates what you've eaten so far, shows remaining budget against the dynamic day goal, macro progress (protein vs. the possibly raised goal) and 2–3 concrete suggestions for the rest of the day, recovery-aware. Without logged food it still shows your sport and raised budget.

### Every 30 minutes — recipes (`recept_verwerken.py`)
`/recept_ai naam: ingrediënten` (AI computes macros) or `/recept naam: ... | kcal, eiwit, koolh, vet`. Stored in `recepten.json`, instantly on the recipe website, and from then on recognised in meal logs for exact values.

## Weekly report (Monday 08:00, `weekly_summary.py`)
- Averages for kcal, macros and score over the last 7 logged days, compared against your goals — the kcal comparison uses the **average dynamic goal** (base goal + compensated sport per day).
- 🚴 sport week block: activities, sport days, total burned.
- 🫀 recovery block: average HRV, RHR and sleep vs. the previous week (read straight from the intervals.icu API, so history from before the integration counts).
- 🍺 **Food↔recovery correlation**: compares HRV and sleep score in the night *after* alcohol days vs. other days. Alcohol days are detected with a word-boundary keyword list (bier(tje/s), pint(je/s), wijn, cava, tripel, gin, ...). Only shown with ≥ 21 nights of HRV data *and* ≥ 3 days in both groups — below that, correlations would be noise.
- ⚖️ weight trend on a 7-day moving average (needs ≥ 3 weighings per window).
- 🔬 **TDEE estimate**: `average intake − (Δ smoothed weight × 7700 / days)` over an adaptive 10–14 day window, requiring ~70% logged days. Deliberately *not* adjusted for sport — sport is already implicit in the intake-vs-weight arithmetic; the sport compensation only steers daily feedback. Estimates outside 1500–4500 kcal are flagged as unreliable instead of shown.

## Monthly report (1st, 08:30, `monthly_report.py`)
Photo with six charts — weight + 7d average, kcal/day (bars coloured against the dynamic goal, purple overlay bars for burned sport kcal), protein/day, stacked meal distribution per week, HRV + resting HR, sleep hours + score — plus a caption with stats, sport and wellness summaries, best week, TDEE and an AI reflection. `test_mode` input runs it for the current month.

## Dashboard (`stats.html`)
Mobile-first GitHub Pages dashboard reading the sheets via the key-protected `doGet`. Cards (weight, avg kcal, score, logged days) and charts: weight, 🫀 recovery (HRV + sleep score left axis, RHR right), kcal/day — with a 🚴 marker above sport-day bars and a goal line that rises with the dynamic goal — protein, meal distribution and score. 30/90/all-time toggle. URL + API key live only in your device's localStorage.

## Data model (Google Sheets)

| Tab | Granularity | Written by | Dedupe |
|---|---|---|---|
| Maaltijden | 1 row per day | 23:58 run | none (one run per day) |
| Gewicht | 1 row per weighing | 15:00 run + 23:58 catch-net | catch-net checks the tab first |
| Sport | 1 row per activity | 23:58 run + import | on Intervals ID |
| Wellness | 1 row per day | 23:58 run + import | upsert on date |

Empty cells mean "not measured", missing rows mean "not logged" — never zero. The Apps Script `doGet` (API-key protected) serves all tabs as JSON for the reports and dashboard; `exportNaarDoc()` mirrors everything daily into a Google Doc.

## Historical backfill (`import_wellness.py`)
Manual *Wellness-import* workflow: imports wellness (and optionally activities) from any start date — default 2026-06-01 — in batches of 50. Safe to re-run thanks to the upsert/dedupe above.

## Configuration reference (`data/config/config.json`)

| Block | Key | Default | Meaning |
|---|---|---|---|
| `doelen` | `kcal`, `eiwitten`, `koolhydraten`, `vetten`, `vezels` | — | Daily targets |
| | `richting` | aankomen | `aankomen` / `afvallen` / `onderhouden` — steers all AI feedback |
| | `sport_compensatie` | 1.0 | Share of burned kcal added to the day goal (1.0 = eat it all back; 0.5 = buffer while cutting; 0 = log only) |
| `wellness` | `tss_zware_dag` | 100 | Training load from which a day counts as "heavy" (protein bump + carb advice) |
| | `eiwit_extra_g` | 20 | Extra protein (g) on heavy days |
| | `hrv_alert_dagen` | 3 | Consecutive nights below HRV baseline before the recovery alert |
| | `rhr_alert_boven_baseline` | 3 | Required resting-HR elevation (bpm) for the alert |
| `intervals_upload` | `gewicht` | true | Upload morning weight |
| | `gewicht_locked` | **false** | Send `"locked": true`. Off by default: the lock is record-level and could block later Garmin syncs that day — only useful if another source keeps overwriting your weight |
| | `kcal` / `kcal_veld` | true / kcalConsumed | Upload intake; field name adjustable without code changes |
| | `custom_velden` | Voedingsscore + built-ins | Wellness-field name → bot metric (`score`/`eiwitten`/`koolhydraten`/`vetten`). Protein/carbs/fat use intervals.icu's built-in fields (`protein`, `carbohydrates`, `fatTotal`); only `Voedingsscore` is a custom field you create once ([how-to](intervals.md)) |
| | `kalendernotitie` | true | Day summary as 🍽️ NOTE in the training calendar |
| | `activiteit_beschrijving` | true | Fueling line on each activity |

Edit, commit, push — every workflow picks up the new values on its next run.

## Testing
`tests/` contains an offline suite (no network, no keys): `python tests/test_sport_integratie.py` (~120 checks: parsing, alert edge cases, prompts, full main-runs against mocked APIs) and `node tests/test_apps_script.js` (sheet wiring incl. dedupe/upsert). Run both before pushing changes to the scripts.
