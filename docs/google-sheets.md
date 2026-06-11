# Google Sheets Setup

## 1. Create the spreadsheet

1. Go to [Google Sheets](https://sheets.google.com) and create a new spreadsheet.
2. Rename it (e.g. `Calorie Tracker`).
3. Copy the **spreadsheet ID** from the URL:
   ```
   https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
   ```

## 2. Create the tabs and column headers

### Tab: Maaltijden

Rename the default sheet to `Maaltijden` and add these headers in row 1:

| A | B | C | D | E | F | G | H | I | J | K | L | M |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Datum | Maaltijden | Calorieën | Eiwitten (g) | Koolhydraten (g) | Vetten (g) | Vezels (g) | Score | Notities | Ontbijt (kcal) | Lunch (kcal) | Avondeten (kcal) | Snacks (kcal) |

### Tab: Gewicht

Add a second sheet named `Gewicht` with headers in row 1:

| A | B |
|---|---|
| Datum | Gewicht (kg) |

## 3. Set up Apps Script

1. In the spreadsheet, go to **Extensions > Apps Script** (this binds the script to the spreadsheet — no spreadsheet ID needed).
2. Delete the default code and paste the full contents of [`scripts/apps_script.js`](../scripts/apps_script.js) from this repo.
3. In `exportNaarDoc()`: replace the Google Doc ID with your own, or delete the whole function if you don't use the Doc sync (optional feature, see step 6).
4. Save the script (Ctrl+S).

The script contains:
- `doPost(e)` — receives data from GitHub Actions and appends rows
- `doGet(e)` — returns the last N rows as JSON (used by the weekly/monthly reports, streak checks and the stats dashboard). Protected by an API key.
- `exportNaarDoc()` — optional daily export to a Google Doc
- `testMaaltijd()` / `testGewicht()` — run these from the editor to verify the sheet wiring

## 4. Set the API key

`doGet` only responds when the request carries the right key, so your weight/meal data stays private even though the web app URL is callable by anyone.

1. Choose a long random string (30+ characters).
2. In Apps Script: **Project Settings (⚙️) > Script Properties > Add script property**
   - Property: `API_KEY`
   - Value: your random string

You will use this same value as the `APPS_SCRIPT_KEY` GitHub secret and in the stats dashboard.

## 5. Deploy as web app

1. Click **Deploy > New deployment**.
2. Click the gear icon next to "Select type" and choose **Web app**.
3. Set:
   - **Execute as**: Me
   - **Who has access**: Anyone
4. Click **Deploy**.
5. Authorize the permissions when prompted.
6. Copy the **Web app URL** — it looks like:
   ```
   https://script.google.com/macros/s/AKfycb.../exec
   ```

Verify in a browser: `<URL>?type=maaltijden&limit=2&key=<your key>` should return JSON (an empty `[]` is fine); without the key you should get `{"error":"unauthorized"}`.

## 6. Add to GitHub secrets

1. Go to **Settings > Secrets and variables > Actions** in your repo.
2. Add:

| Name | Value |
|---|---|
| `APPS_SCRIPT_URL` | The web app URL from step 5 |
| `APPS_SCRIPT_KEY` | The API key from step 4 |

## 7. Set up daily export trigger (optional)

If you want data synced to a Google Doc for use in Claude:

1. In Apps Script, go to **Triggers** (clock icon on the left).
2. Click **+ Add Trigger**.
3. Set:
   - Function: `exportNaarDoc`
   - Event source: Time-driven
   - Type: Day timer
   - Time: 5am – 6am
4. Save.

## Notes

- **Updating the script later?** Always use **Deploy > Manage deployments > Edit (✏️) > Version: New** — this keeps the URL stable. Creating a *new deployment* generates a new URL and breaks everything pointing at the old one (GitHub secret, dashboard).
- The `Gewicht` tab is created automatically on the first weight entry if it doesn't exist.
