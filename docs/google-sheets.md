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

1. In the spreadsheet, go to **Extensions > Apps Script**.
2. Delete the default code and paste the following:

```javascript
const SPREADSHEET_ID = "YOUR_SPREADSHEET_ID_HERE";

function doPost(e) {
  const data = JSON.parse(e.postData.contents);
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);

  if (data.type === "gewicht") {
    const sheet = ss.getSheetByName("Gewicht");
    sheet.appendRow([data.datum, data.gewicht]);
    return ContentService.createTextOutput("OK");
  }

  const sheet = ss.getSheetByName("Maaltijden");
  sheet.appendRow([
    data.datum,
    data.maaltijden,
    data.calories,
    data.eiwitten,
    data.koolhydraten,
    data.vetten,
    data.vezels,
    data.score,
    data.notities,
    data.ontbijt_kcal,
    data.lunch_kcal,
    data.avondeten_kcal,
    data.snacks_kcal,
  ]);
  return ContentService.createTextOutput("OK");
}

function doGet(e) {
  const type = e.parameter.type || "maaltijden";
  const limit = parseInt(e.parameter.limit) || 14;
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);

  const sheetName = type === "gewicht" ? "Gewicht" : "Maaltijden";
  const sheet = ss.getSheetByName(sheetName);
  const data = sheet.getDataRange().getValues();

  if (data.length <= 1) return ContentService.createTextOutput(JSON.stringify([])).setMimeType(ContentService.MimeType.JSON);

  const headers = data[0].map(h => h.toString().toLowerCase().replace(/[^a-z0-9]/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, ""));
  const rows = data.slice(1).slice(-limit).map(row =>
    Object.fromEntries(headers.map((h, i) => [h, row[i]]))
  );
  return ContentService.createTextOutput(JSON.stringify(rows)).setMimeType(ContentService.MimeType.JSON);
}

function exportNaarDoc() {
  const DOC_ID = "YOUR_GOOGLE_DOC_ID_HERE";
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const doc = DocumentApp.openById(DOC_ID);
  const body = doc.getBody();
  body.clear();

  const maaltijden = ss.getSheetByName("Maaltijden").getDataRange().getValues();
  const gewicht = ss.getSheetByName("Gewicht").getDataRange().getValues();

  body.appendParagraph("Maaltijden").setHeading(DocumentApp.ParagraphHeading.HEADING1);
  maaltijden.forEach(row => body.appendParagraph(row.join(" | ")));

  body.appendParagraph("Gewicht").setHeading(DocumentApp.ParagraphHeading.HEADING1);
  gewicht.forEach(row => body.appendParagraph(row.join(" | ")));

  doc.saveAndClose();
}
```

3. Replace `YOUR_SPREADSHEET_ID_HERE` with your spreadsheet ID.
4. If you use the Claude Project sync (optional): replace `YOUR_GOOGLE_DOC_ID_HERE` with your Google Doc ID.
5. Save the script (Ctrl+S).

## 4. Deploy as web app

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

Save this URL as the `APPS_SCRIPT_URL` GitHub secret.

## 5. Add to GitHub secrets

1. Go to **Settings > Secrets and variables > Actions** in your repo.
2. Add:

| Name | Value |
|---|---|
| `APPS_SCRIPT_URL` | The web app URL from step 4 |

## 6. Set up daily export trigger (optional)

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

- Every time you redeploy the Apps Script, the URL changes. Update the `APPS_SCRIPT_URL` secret if you redeploy.
- To update the script without changing the URL: use **Deploy > Manage deployments > Edit** (pencil icon) and select "New version".
