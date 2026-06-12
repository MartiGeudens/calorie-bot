# intervals.icu Setup (sport integration)

The bot reads sport activities (cycling, running, strength training, ...) with **exact calorie data** from [intervals.icu](https://intervals.icu) — a free training platform with an official Garmin Connect sync and a free open API.

Why not Garmin or Strava directly? Garmin has no free consumer API, and the Strava API requires a paid subscription since June 2026. intervals.icu is free, syncs activities from Garmin within ~5 minutes, and uses a simple API key (no OAuth dance, no token refresh).

## 1. Create an intervals.icu account

1. Go to [intervals.icu](https://intervals.icu) and sign up (free).
2. During signup — or later via **Settings** — connect **Garmin Connect** (one-time OAuth login with your Garmin account).
3. Wait for the initial sync; your Garmin activities appear automatically.

> Garmin dedupes multiple devices (watch + bike computer recording the same ride) before the sync, so no double activities arrive.

## 2. Generate an API key

1. Open [intervals.icu/settings](https://intervals.icu/settings).
2. Scroll to the bottom → **Developer Settings**.
3. Click **API Key** → generate and copy the key.

> The bot authenticates with HTTP Basic auth: username `API_KEY`, password = your key. Athlete ID `0` in API paths means "the owner of this key", so no athlete ID is needed anywhere.

## 3. Add the GitHub secret

GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:

- Name: `INTERVALS_API_KEY`
- Value: the API key from step 2

That's the only secret. Without it, everything keeps working — the bot simply skips sport.

## 4. Add the Sport column and tab in Google Sheets

1. Tab `Maaltijden`: add header `Sport (kcal)` in cell **N1** (column 14).
2. The `Sport` tab is **created automatically** by Apps Script on the first activity. To create it manually instead, add a sheet named `Sport` with headers:

| A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|
| Datum | Activiteit | Type | Duur (min) | Afstand (km) | Kcal | Gem. HS | Intervals ID |

## 5. Deploy the new Apps Script version

1. Copy the full contents of `scripts/apps_script.js` into your Apps Script editor.
2. **Deploy → Manage deployments → Edit (✏️) → Version: New version → Deploy.**

> Without a new deployment the web app keeps running the old code and sport data is silently ignored.

## 6. Test

1. Record any activity with your Garmin (or pick a day that already has one).
2. Run the **Verwerking** workflow manually: Actions → *Maaltijden verwerken* → Run workflow.
3. Check that:
   - the Telegram summary shows a 🚴 block with burned kcal and the raised day goal,
   - the `Sport` tab contains one row per activity,
   - column `Sport (kcal)` in `Maaltijden` has the day total.
4. In Apps Script you can also run `testSport()` and check the `Sport` tab (dedupe: running it twice must not create duplicate rows).

## How it works

```
Garmin device → Garmin Connect → (official sync) → intervals.icu
                                                      ↓ API key (HTTP Basic)
GitHub Actions workflows (verwerking, tips, herinnering, weekly, monthly)
                                                      ↓
Google Sheets: "Sport" tab + "Sport (kcal)" column in "Maaltijden"
```

- `scripts/intervals.py` fetches activities for today (the 23:58 run also re-checks yesterday, catching activities that synced after midnight). Deduplication happens in Apps Script on the `Intervals ID` column.
- **Day budget = `kcal` goal + `sport_compensatie` × burned kcal.** With `"sport_compensatie": 1.0` in `data/config/config.json` (advised while bulking) a 600 kcal ride raises a 2750 kcal goal to 3350. Use `0.5` while cutting to buffer against overestimation.
- The TDEE estimate is **not** changed by sport — it is based on intake vs. weight trend and already includes sport implicitly. The compensation only steers the daily feedback.
- Activities without calories (e.g. manually added ones) are logged with 0 kcal and don't affect the budget.
- intervals.icu unreachable or no key set → everything works exactly as before, without the sport line. Sport can never block meal processing.

## Wellness (phase 2)

The same API key also unlocks Garmin's daily wellness data (overnight HRV, resting heart rate, sleep duration + score, readiness) via `GET /api/v1/athlete/0/wellness?oldest=&newest=`. No extra setup — if the sport integration works, wellness works.

What the bot does with it:

- **Nightly storage (23:58)** — the day-processing run fetches today + yesterday and upserts them into a `Wellness` tab (Datum | HRV | RHR | Slaap (u) | Slaapscore | Readiness). The tab is created automatically.
- **Recovery-aware AI (23:58 + /tips)** — the analysis and tips prompts receive last night's recovery ("HRV 58 · RHR 50 · 6.8u slaap (score 72)"), steering advice toward earlier meals, less alcohol and enough carbs/protein when recovery is poor.
- **Overtraining/illness signal (15:00)** — if HRV stays below its 7-day baseline for 3 consecutive days *and* resting HR is elevated (defaults: 3 days, +3 bpm), the weight-check run sends a one-time warning suggesting a rest day. It only fires on the first day the condition becomes true.
- **Dynamic protein goal** — on days with training load (TSS) ≥ `tss_zware_dag`, the protein goal is raised by `eiwit_extra_g` in the analysis, /tips and the daily summary.
- **Planned-workout carb advice (21:00)** — if tomorrow's intervals.icu calendar contains a heavy workout (load ≥ threshold or ≥ 90 min), the evening reminder adds "extra koolhydraten vanavond is slim". Silent while the calendar is unused.
- **Reports & dashboard** — weekly report shows HRV/RHR/sleep averages vs. last week plus a food↔recovery correlation ("night after alcohol days: HRV −12 · sleep score −15", shown only after ≥21 nights of data and ≥3 days in both groups); monthly report gets two extra chart panels (HRV & RHR, sleep) and a wellness line in the caption; the dashboard gets a 🫀 recovery chart. Reports read wellness directly from the intervals.icu API, so history from before this integration counts too.

Thresholds live in `data/config/config.json`:

```json
"wellness": {
  "tss_zware_dag": 100,
  "eiwit_extra_g": 20,
  "hrv_alert_dagen": 3,
  "rhr_alert_boven_baseline": 3
}
```

> By deliberate choice there is **no recovery context in the morning question**: wake-up times vary and the Garmin sync isn't guaranteed to have happened yet at that hour.

**Backfilling history (both directions):**

- *Wellness-import* workflow — intervals.icu → Sheets: imports wellness (and optionally activities) from a start date (default 2026-06-01) into the tabs. Locally: `python scripts/import_wellness.py [start] [eind] [--zonder-sport]`.
- *Export naar intervals.icu* workflow — Sheets → intervals.icu: pushes the existing history (weight + kcal/macros/score per day) into the wellness records in one go, so the /fitness plots cover the whole tracking period. Optional `met_notities` input also creates the 🍽️ calendar note for every logged day. Locally: `python scripts/export_naar_intervals.py [start] [eind] [--met-notities]`.

Both are safe to re-run: wellness upserts per date, sport dedupes on Intervals ID and calendar notes are updated rather than duplicated.

## Writing back to intervals.icu (phase 3)

The bot also pushes data *to* intervals.icu — every part individually switchable in `config.json` → `intervals_upload`:

```json
"intervals_upload": {
  "gewicht": true,
  "gewicht_locked": false,
  "kcal": true,
  "kcal_veld": "kcalConsumed",
  "custom_velden": { "Voedingsscore": "score", "protein": "eiwitten", "carbohydrates": "koolhydraten", "fatTotal": "vetten" },
  "kalendernotitie": true,
  "activiteit_beschrijving": true
}
```

- **Weight (15:00 + 23:58 catch-net)** — your morning weight goes to the intervals.icu wellness record, so W/kg, eFTP and power stats are always correct there. `gewicht_locked` is **off by default**: the lock works at record level and could block later Garmin wellness syncs for that day; only enable it if another source (e.g. a smart scale sync) keeps overwriting your weight.
- **Calorie intake (23:58)** — the AI day total is written to the wellness field named by `kcal_veld` (default `kcalConsumed`). After the first run, check the wellness page in intervals.icu; if the value doesn't show up, the field name differs on your account — adjust `kcal_veld` in config, no code change needed.
- **Macros & nutrition score (23:58)** — protein, carbs and fat go into intervals.icu's **built-in** nutrition fields (API names `protein`, `carbohydrates`, `fatTotal`, all grams — [announcement](https://forum.intervals.icu/t/capture-carbs-protein-and-fat-intake/122594)); no setup needed beyond ticking them in the wellness dialog if you want to see them. Only the nutrition score needs one **custom field**: open the calendar → click a day → **Wellness** → **Fields** → **+** icon → code **`Voedingsscore`** (CamelCase, used by the API — don't change it once in use), type INPUT/number. All of them are plottable against HRV, sleep and training load on the /fitness page. The `custom_velden` config maps any wellness field (built-in or custom) to a bot metric (`score`/`eiwitten`/`koolhydraten`/`vetten`). To show fields on the calendar: Options → Wellness. ([Custom fields announcement](https://forum.intervals.icu/t/custom-wellness-fields/23188))
- **Calendar note (23:58)** — the day summary (kcal, macros, score, AI note) appears as a 🍽️ NOTE in your training calendar. Upserted: re-runs update the existing note; other notes on that day are left alone.
- **Activity description (23:58)** — every activity of the day gets a fueling line appended: "Gevoed: 2800 kcal · 150g eiwit (score 8/10)". Your own description text is preserved; on re-runs the old Gevoed line is replaced, never duplicated.

All uploads run *after* the Telegram flow has fully completed and fail silently — a missing key, missing custom field or API outage never affects meal processing.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| No 🚴 block in the summary | Secret `INTERVALS_API_KEY` missing or workflow not updated; check the Actions log for "intervals.icu:" lines |
| HTTP 401/403 in the log | Wrong/expired API key — regenerate in Developer Settings |
| Activity missing | Garmin → intervals.icu sync can take a few minutes; yesterday's late activities are caught by the next 23:58 run |
| Duplicate rows in Sport tab | Old Apps Script version still deployed — deploy a new version (step 5) |
| kcal is 0 for an activity | Activity has no calorie data in Garmin (e.g. manually created activity) |
| No wellness data in the tab | Apps Script version without wellness support — deploy a new version |
| Nutrition upload logs "check veldnamen" | The `Voedingsscore` custom field doesn't exist yet, or `kcal_veld` doesn't match your account — fix the field or the config |
| Recovery alert never fires | That's good — it needs 3 consecutive low-HRV nights *plus* elevated resting HR, and won't repeat while the dip lasts |