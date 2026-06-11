# Stats Dashboard Setup

`stats.html` is a mobile-first dashboard on your GitHub Pages site showing your weight trend (raw + 7-day moving average), daily calories vs. goal, daily protein vs. goal, meal distribution per week and daily score — with a 30 days / 90 days / all-time toggle.

It reads data live from your Apps Script `doGet` endpoint, protected by the API key. Nothing sensitive is stored in the repo.

## First-time setup (per device)

1. Open `https://<username>.github.io/<repo>/stats.html` (or tap 📊 in the recipe book header).
2. Fill in:
   - **Apps Script URL** — the full `/exec` URL (same value as the `APPS_SCRIPT_URL` secret)
   - **API key** — same value as the `APPS_SCRIPT_KEY` secret / `API_KEY` script property
3. Both are stored in your device's **localStorage only** — they never touch the repo or any server. Repeat once per device (phone, laptop).

Tip: add the page to your phone's home screen for an app-like experience.

## Changing URL or key

Tap the ⚙️ icon in the header to re-enter both values (e.g. after redeploying the Apps Script as a *new deployment*, which changes the URL).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Laden mislukt: unauthorized" | The key doesn't match the `API_KEY` script property — re-enter via ⚙️, check for stray spaces |
| "Laden mislukt: onverwacht antwoord" | Wrong URL (typo, or an old deployment URL) — verify the URL in a browser with `?type=maaltijden&limit=2&key=...` |
| Charts empty | No data yet in the period — log a few days first |
| Goals look wrong | The dashboard reads `data/config/config.json` from the repo; push your own goals |
