// Functionele test van apps_script.js met gestubde Google-services (Node).
const fs = require("fs");

// ── stubs ─────────────────────────────────────────────────────────────────────
class FakeSheet {
  constructor(name) { this.name = name; this.rows = []; }
  appendRow(r) { this.rows.push(r); }
  getLastRow() { return this.rows.length; }
  getRange(row, col, numRows, numCols) {
    const self = this;
    return { getValues: () => self.rows.slice(row - 1, row - 1 + numRows).map(r => r.slice(col - 1, col - 1 + numCols)) };
  }
  getDataRange() { const self = this; return { getValues: () => self.rows.map(r => r.slice()) }; }
}
const sheets = {};
global.SpreadsheetApp = {
  getActiveSpreadsheet: () => ({
    getSheetByName: n => sheets[n] || null,
    insertSheet: n => (sheets[n] = new FakeSheet(n)),
    getActiveSheet: () => sheets["Maaltijden"],
  }),
};
global.ContentService = {
  MimeType: { JSON: "json" },
  createTextOutput: t => ({ _t: t, setMimeType() { return this; }, text: t }),
};
global.PropertiesService = { getScriptProperties: () => ({ getProperty: () => "geheim" }) };
global.Utilities = { formatDate: (d) => d.toISOString().slice(0, 10) };
global.DocumentApp = { openById: () => { throw new Error("niet nodig in test"); } };

eval(fs.readFileSync(__dirname + "/../scripts/apps_script.js", "utf8"));

let fails = 0;
const check = (naam, cond, extra = "") => {
  console.log(`[${cond ? "OK " : "FAIL"}] ${naam}${cond ? "" : " — " + extra}`);
  if (!cond) fails++;
};
const post = obj => JSON.parse(doPost({ postData: { contents: JSON.stringify(obj) } })._t);

// 1. sport: nieuwe tab + 2 rijen
let r = post({ type: "sport", activiteiten: [
  { id: "i111", datum: "2026-06-11", naam: "Ochtendrit", type: "Ride", duur_min: 92, afstand_km: 45.2, kcal: 612, gem_hs: 148 },
  { id: "i222", datum: "2026-06-11", naam: "Run", type: "Run", duur_min: 31, afstand_km: 6.1, kcal: 285, gem_hs: 156 },
]});
check("doPost sport: status ok + 2 nieuw", r.status === "ok" && r.nieuw === 2, JSON.stringify(r));
check("doPost sport: header + 2 rijen", sheets["Sport"].rows.length === 3);
check("doPost sport: rij correct", JSON.stringify(sheets["Sport"].rows[1]) === JSON.stringify(["2026-06-11", "Ochtendrit", "Ride", 92, 45.2, 612, 148, "i111"]), JSON.stringify(sheets["Sport"].rows[1]));

// 2. dedupe: zelfde batch nogmaals + 1 nieuwe
r = post({ type: "sport", activiteiten: [
  { id: "i111", datum: "2026-06-11", naam: "Ochtendrit", type: "Ride", duur_min: 92, afstand_km: 45.2, kcal: 612, gem_hs: 148 },
  { id: "i333", datum: "2026-06-10", naam: "Kracht", type: "WeightTraining", duur_min: 60, afstand_km: 0, kcal: 0, gem_hs: 120 },
]});
check("doPost sport: dedupe — alleen i333 nieuw", r.nieuw === 1 && sheets["Sport"].rows.length === 4, JSON.stringify(r));

// 3. maaltijden met sport_kcal (kolom 14)
sheets["Maaltijden"] = new FakeSheet("Maaltijden");
sheets["Maaltijden"].appendRow(["Datum","Maaltijden","Calorieën","Eiwitten (g)","Koolhydraten (g)","Vetten (g)","Vezels (g)","Score","Notities","Ontbijt (kcal)","Lunch (kcal)","Avondeten (kcal)","Snacks (kcal)","Sport (kcal)"]);
post({ datum: "2026-06-11", maaltijden: "x", calories: 2800, eiwitten: 150, koolhydraten: 320,
       vetten: 85, vezels: 30, score: 8, notities: "ok", ontbijt_kcal: 500, lunch_kcal: 800,
       avondeten_kcal: 1200, snacks_kcal: 300, sport_kcal: 897 });
const mrow = sheets["Maaltijden"].rows[1];
check("doPost maaltijden: 14 kolommen, sport_kcal laatst", mrow.length === 14 && mrow[13] === 897, JSON.stringify(mrow));

// 4. oude payload zonder sport_kcal → lege kolom
post({ datum: "2026-06-12", maaltijden: "y", calories: 2000, eiwitten: 100, koolhydraten: 200,
       vetten: 60, vezels: 20, score: 7, notities: "", ontbijt_kcal: 400, lunch_kcal: 600,
       avondeten_kcal: 800, snacks_kcal: 200 });
check("doPost maaltijden: zonder sport_kcal → \"\"", sheets["Maaltijden"].rows[2][13] === "");

// 5. doGet sport
let g = JSON.parse(doGet({ parameter: { key: "geheim", type: "sport", limit: "10" } })._t);
check("doGet sport: 3 activiteiten terug", Array.isArray(g) && g.length === 3, JSON.stringify(g));
check("doGet sport: velden", g[0].id === "i111" && g[0].kcal === 612 && g[0].datum === "2026-06-11", JSON.stringify(g[0]));

// 6. doGet maaltijden bevat sport_kcal
g = JSON.parse(doGet({ parameter: { key: "geheim", type: "maaltijden", limit: "10" } })._t);
check("doGet maaltijden: sport_kcal aanwezig", g[0].sport_kcal === 897 && g[1].sport_kcal === 0, JSON.stringify(g.map(x => x.sport_kcal)));

// 7. doGet sport zonder Sport-tab (verse spreadsheet)
delete sheets["Sport"];
g = JSON.parse(doGet({ parameter: { key: "geheim", type: "sport" } })._t);
check("doGet sport: geen tab → []", Array.isArray(g) && g.length === 0);

// 8. key-check blijft werken
g = JSON.parse(doGet({ parameter: { key: "fout", type: "sport" } })._t);
check("doGet: foute key → unauthorized", g.error === "unauthorized");

// 9. testSport() draait zonder fouten en dedupet bij 2e run
testSport();
const n1 = sheets["Sport"].rows.length;
testSport();
check("testSport: 2e run voegt niets toe", sheets["Sport"].rows.length === n1 && n1 === 3, `${n1} → ${sheets["Sport"].rows.length}`);

console.log();
if (fails) { console.log(`❌ ${fails} test(s) gefaald`); process.exit(1); }
console.log("✅ Apps Script tests geslaagd");
