function exportNaarDoc() {
  var ss   = SpreadsheetApp.getActiveSpreadsheet();
  var doc  = DocumentApp.openById("1li2Brmmtea_ud2hAPNh8Wx87qTTQS9S6kR94rxKyQNE");
  var body = doc.getBody();
  body.clear();

  // Gewicht — max laatste 365 rijen, alles in 1 appendParagraph ipv loop
  var gewichtSheet = ss.getSheetByName("Gewicht");
  var gewicht = gewichtSheet ? gewichtSheet.getDataRange().getValues() : [];
  body.appendParagraph("GEWICHT").setHeading(DocumentApp.ParagraphHeading.HEADING1);
  if (gewicht.length > 0) {
    body.appendParagraph(gewicht.slice(-365).map(r => r.join(" | ")).join("\n"));
  }

  // Maaltijden — laatste 31 dagen, alles in 1 appendParagraph ipv loop
  var maaltijdenSheet = ss.getSheetByName("Maaltijden");
  var maaltijden = maaltijdenSheet ? maaltijdenSheet.getDataRange().getValues() : [];
  body.appendParagraph("MAALTIJDEN").setHeading(DocumentApp.ParagraphHeading.HEADING1);
  if (maaltijden.length > 0) {
    body.appendParagraph(maaltijden.slice(-31).map(r => r.join(" | ")).join("\n"));
  }

  // Sport — laatste 60 activiteiten
  var sportSheet = ss.getSheetByName("Sport");
  var sport = sportSheet ? sportSheet.getDataRange().getValues() : [];
  body.appendParagraph("SPORT").setHeading(DocumentApp.ParagraphHeading.HEADING1);
  if (sport.length > 0) {
    body.appendParagraph(sport.slice(-60).map(r => r.join(" | ")).join("\n"));
  }

  // Wellness — laatste 60 dagen
  var wellnessSheet = ss.getSheetByName("Wellness");
  var wellness = wellnessSheet ? wellnessSheet.getDataRange().getValues() : [];
  body.appendParagraph("WELLNESS").setHeading(DocumentApp.ParagraphHeading.HEADING1);
  if (wellness.length > 0) {
    body.appendParagraph(wellness.slice(-60).map(r => r.join(" | ")).join("\n"));
  }

  doc.saveAndClose();
}


function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var ss   = SpreadsheetApp.getActiveSpreadsheet();

    if (data.type === "gewicht") {
      var sheet = ss.getSheetByName("Gewicht");
      if (!sheet) {
        sheet = ss.insertSheet("Gewicht");
        sheet.appendRow(["Datum", "Gewicht (kg)"]);
      }
      sheet.appendRow([data.datum, data.gewicht]);

    } else if (data.type === "sport") {
      // 1 rij per activiteit, dedupe op Intervals ID (kolom 8) — dezelfde
      // activiteit kan meermaals binnenkomen (vandaag + gisteren-vangnet).
      var sheet = ss.getSheetByName("Sport");
      if (!sheet) {
        sheet = ss.insertSheet("Sport");
        sheet.appendRow(["Datum", "Activiteit", "Type", "Duur (min)", "Afstand (km)", "Kcal", "Gem. HS", "Intervals ID"]);
      }
      var bestaande = {};
      var lastRow = sheet.getLastRow();
      if (lastRow > 1) {
        sheet.getRange(2, 8, lastRow - 1, 1).getValues().forEach(function(r) {
          if (r[0] !== "") bestaande[String(r[0])] = true;
        });
      }
      var nieuw = 0;
      (data.activiteiten || []).forEach(function(a) {
        if (!a || !a.id || bestaande[String(a.id)]) return;
        sheet.appendRow([
          a.datum      || "",
          a.naam       || "",
          a.type       || "",
          a.duur_min   || 0,
          a.afstand_km || 0,
          a.kcal       || 0,
          a.gem_hs     || 0,
          String(a.id)
        ]);
        bestaande[String(a.id)] = true;
        nieuw++;
      });
      return jsonResponse({ status: "ok", nieuw: nieuw });

    } else if (data.type === "wellness") {
      // 1 rij per dag, upsert op datum — de 23:58-run stuurt vandaag én gisteren,
      // dus dezelfde dag kan een tweede keer binnenkomen met vollediger data.
      var sheet = ss.getSheetByName("Wellness");
      if (!sheet) {
        sheet = ss.insertSheet("Wellness");
        sheet.appendRow(["Datum", "HRV", "RHR", "Slaap (u)", "Slaapscore", "Readiness"]);
      }
      var rijVanDatum = {};
      var lastRow = sheet.getLastRow();
      if (lastRow > 1) {
        sheet.getRange(2, 1, lastRow - 1, 1).getValues().forEach(function(r, i) {
          var d = r[0] instanceof Date
            ? Utilities.formatDate(r[0], "Europe/Brussels", "yyyy-MM-dd")
            : String(r[0]);
          if (d) rijVanDatum[d] = i + 2;
        });
      }
      var verwerkt = 0;
      (data.records || []).forEach(function(w) {
        if (!w || !w.datum) return;
        var rij = [w.datum, w.hrv || "", w.rhr || "", w.slaap_u || "", w.slaapscore || "", w.readiness || ""];
        if (rijVanDatum[w.datum]) {
          sheet.getRange(rijVanDatum[w.datum], 1, 1, 6).setValues([rij]);
        } else {
          sheet.appendRow(rij);
          rijVanDatum[w.datum] = sheet.getLastRow();
        }
        verwerkt++;
      });
      return jsonResponse({ status: "ok", verwerkt: verwerkt });

    } else {
      var sheet = ss.getSheetByName("Maaltijden") || ss.getActiveSheet();
      sheet.appendRow([
        data.datum              || "",
        data.maaltijden         || "",
        data.calories           || "",
        data.eiwitten           || "",
        data.koolhydraten       || "",
        data.vetten             || "",
        data.vezels             || "",
        data.score              || "",
        data.notities           || "",
        data.ontbijt_kcal       !== undefined ? data.ontbijt_kcal   : "",
        data.lunch_kcal         !== undefined ? data.lunch_kcal     : "",
        data.avondeten_kcal     !== undefined ? data.avondeten_kcal : "",
        data.snacks_kcal        !== undefined ? data.snacks_kcal    : "",
        data.sport_kcal         !== undefined ? data.sport_kcal     : ""
      ]);
    }

    return ContentService
      .createTextOutput(JSON.stringify({ status: "ok" }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ status: "fout", bericht: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}


function doGet(e) {
  // Key-check: doGet werkt enkel met de juiste key, meegestuurd als ?key=...
  // De key staat bewust NIET in deze file (publieke repo) maar in een Script
  // Property: Projectinstellingen → Scripteigenschappen → "API_KEY".
  // Zelfde waarde als de GitHub secret APPS_SCRIPT_KEY.
  var apiKey = PropertiesService.getScriptProperties().getProperty("API_KEY");
  if (!apiKey || !e || !e.parameter || e.parameter.key !== apiKey) {
    return jsonResponse({ error: "unauthorized" });
  }

  try {
    var type  = (e.parameter && e.parameter.type)  || "maaltijden";
    var limit = parseInt((e.parameter && e.parameter.limit) || "14");
    var ss    = SpreadsheetApp.getActiveSpreadsheet();

    if (type === "maaltijden") {
      var sheet = ss.getSheetByName("Maaltijden") || ss.getActiveSheet();
      var allData = sheet.getDataRange().getValues();
      if (allData.length <= 1) {
        return jsonResponse([]);
      }
      var rows = allData.slice(1).slice(-limit);
      var result = rows.map(function(row) {
        var datumVal = row[0];
        var datumStr = datumVal instanceof Date
          ? Utilities.formatDate(datumVal, "Europe/Brussels", "yyyy-MM-dd")
          : (datumVal ? datumVal.toString() : "");
        return {
          datum:          datumStr,
          maaltijden:     row[1]  || "",
          calories:       row[2]  || 0,
          eiwitten:       row[3]  || 0,
          koolhydraten:   row[4]  || 0,
          vetten:         row[5]  || 0,
          vezels:         row[6]  || 0,
          score:          (row[7] instanceof Date) ? row[7].getDate() : (row[7] || ""),
          notities:       row[8]  || "",
          ontbijt_kcal:   row[9]  || 0,
          lunch_kcal:     row[10] || 0,
          avondeten_kcal: row[11] || 0,
          snacks_kcal:    row[12] || 0,
          sport_kcal:     row[13] || 0
        };
      });
      return jsonResponse(result);

    } else if (type === "sport") {
      var sheet = ss.getSheetByName("Sport");
      if (!sheet) return jsonResponse([]);
      var allData = sheet.getDataRange().getValues();
      if (allData.length <= 1) return jsonResponse([]);
      var rows = allData.slice(1).slice(-limit);
      var result = rows.map(function(row) {
        var datumVal = row[0];
        var datumStr = datumVal instanceof Date
          ? Utilities.formatDate(datumVal, "Europe/Brussels", "yyyy-MM-dd")
          : (datumVal ? datumVal.toString() : "");
        return {
          datum:      datumStr,
          naam:       row[1] || "",
          type:       row[2] || "",
          duur_min:   row[3] || 0,
          afstand_km: row[4] || 0,
          kcal:       row[5] || 0,
          gem_hs:     row[6] || 0,
          id:         String(row[7] || "")
        };
      });
      return jsonResponse(result);

    } else if (type === "wellness") {
      var sheet = ss.getSheetByName("Wellness");
      if (!sheet) return jsonResponse([]);
      var allData = sheet.getDataRange().getValues();
      if (allData.length <= 1) return jsonResponse([]);
      var rows = allData.slice(1).slice(-limit);
      var result = rows.map(function(row) {
        var datumVal = row[0];
        var datumStr = datumVal instanceof Date
          ? Utilities.formatDate(datumVal, "Europe/Brussels", "yyyy-MM-dd")
          : (datumVal ? datumVal.toString() : "");
        return {
          datum:      datumStr,
          hrv:        row[1] || 0,
          rhr:        row[2] || 0,
          slaap_u:    row[3] || 0,
          slaapscore: row[4] || 0,
          readiness:  row[5] || 0
        };
      });
      return jsonResponse(result);

    } else if (type === "gewicht") {
      var sheet = ss.getSheetByName("Gewicht");
      if (!sheet) return jsonResponse([]);
      var allData = sheet.getDataRange().getValues();
      if (allData.length <= 1) return jsonResponse([]);
      var rows = allData.slice(1).slice(-limit);
      var result = rows.map(function(row) {
        var datumVal = row[0];
        var datumStr = datumVal instanceof Date
          ? Utilities.formatDate(datumVal, "Europe/Brussels", "yyyy-MM-dd")
          : (datumVal ? datumVal.toString() : "");
        return { datum: datumStr, gewicht: row[1] || 0 };
      });
      return jsonResponse(result);
    }

    return jsonResponse({ status: "onbekend type" });

  } catch (err) {
    return jsonResponse({ status: "fout", bericht: err.toString() });
  }
}


function jsonResponse(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}


function testMaaltijd() {
  doPost({ postData: { contents: JSON.stringify({
    datum: "2026-06-01", maaltijden: "havermout\nbroodje kaas\npasta bolognese",
    calories: 1850, eiwitten: 95, koolhydraten: 220, vetten: 65, vezels: 28,
    score: "8/10", notities: "Goed uitgebalanceerde dag!",
    ontbijt_kcal: 380, lunch_kcal: 520, avondeten_kcal: 850, snacks_kcal: 100
  })}});
}

function testGewicht() {
  doPost({ postData: { contents: JSON.stringify({
    type: "gewicht", datum: "2026-06-01", gewicht: 72.5
  })}});
}

function testWellness() {
  doPost({ postData: { contents: JSON.stringify({
    type: "wellness",
    records: [
      { datum: "2026-06-11", hrv: 62, rhr: 48, slaap_u: 7.3, slaapscore: 81, readiness: 75 },
      { datum: "2026-06-12", hrv: 58, rhr: 50, slaap_u: 6.8, slaapscore: 72, readiness: null }
    ]
  })}});
}

function testSport() {
  doPost({ postData: { contents: JSON.stringify({
    type: "sport",
    activiteiten: [
      { id: "i1234567", datum: "2026-06-11", naam: "Avondrit", type: "Ride",
        duur_min: 92, afstand_km: 45.2, kcal: 612, gem_hs: 148 },
      { id: "i1234568", datum: "2026-06-11", naam: "Looprondje", type: "Run",
        duur_min: 31, afstand_km: 6.1, kcal: 285, gem_hs: 156 }
    ]
  })}});
}
