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
        data.snacks_kcal        !== undefined ? data.snacks_kcal    : ""
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
          snacks_kcal:    row[12] || 0
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
