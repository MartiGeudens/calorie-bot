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

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| No 🚴 block in the summary | Secret `INTERVALS_API_KEY` missing or workflow not updated; check the Actions log for "intervals.icu:" lines |
| HTTP 401/403 in the log | Wrong/expired API key — regenerate in Developer Settings |
| Activity missing | Garmin → intervals.icu sync can take a few minutes; yesterday's late activities are caught by the next 23:58 run |
| Duplicate rows in Sport tab | Old Apps Script version still deployed — deploy a new version (step 5) |
| kcal is 0 for an activity | Activity has no calorie data in Garmin (e.g. manually created activity) |
