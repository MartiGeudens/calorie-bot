# Calorie Tracker Bot

Persoonlijke Telegram-bot die maaltijden logt, macro's analyseert via AI en alles opslaat in Google Sheets — met Garmin-sportdata en herstelmetrieken via intervals.icu. Volledig cloudgebaseerd via GitHub Actions: geen lokale server, alles draait op gratis diensten.

## Architectuur

```
Telegram Bot                     Garmin → intervals.icu (sport, HRV, slaap)
    ↕                                ⇅ API-key (lezen én terugschrijven)
GitHub Actions  →  Groq AI (llama-3.3-70b-versatile)
    ↓
Google Sheets  ←→  Apps Script Web App (doPost/doGet met API-key)
    ↓
Google Doc (optionele AI-assistent sync)

GitHub Pages  →  Receptenboek + Statistieken-dashboard
cron-job.org  →  Tijdsbeheer workflows (exacte tijden)
```

## Features

Klik een feature open voor de uitleg. Het volledige naslagwerk — exacte regels, drempels en randgevallen — staat in [docs/features.md](docs/features.md).

<details>
<summary>🍽️ <b>Maaltijden loggen</b> — stuur gewoon berichten, AI analyseert om 23:58</summary>

Stuur maaltijden als gewone berichten doorheen de dag (`lunch: broodje kaas en tomaat`) of alles 's avonds in één keer. Elke avond om 23:58 analyseert de bot alles automatisch en stuurt een overzicht met totale calorieën, macro's per maaltijdmoment (ontbijt/lunch/avondeten/snacks), een score op 10 en een persoonlijke tip. Labels zijn optioneel maar verbeteren de uitsplitsing. Bij een score onder 5 volgt een extra concrete tip voor morgen.

</details>

<details>
<summary>⚖️ <b>Gewicht bijhouden</b> — ochtendvraag om 07:00, vangnet om 23:58</summary>

Dagelijkse ochtendvraag om 07:00. Antwoord met een getal (bv. `72.5`), wordt om 15:00 opgeslagen — en meteen geüpload naar intervals.icu, zodat W/kg en eFTP daar altijd kloppen. Stuur je het later? De dagverwerking om 23:58 vangt het alsnog op (met dubbele-rij-controle). De gewichtstrend in rapporten gebruikt een 7-daags voortschrijdend gemiddelde, zodat dagelijkse vocht-schommelingen eruit gefilterd worden.

</details>

<details>
<summary>🔔 <b>Slimme avondherinnering</b> — weet wat je al logde (21:00)</summary>

Om 21:00 checkt de bot wat je al logde: nog niets → gewone herinnering; wel al berichten → welke maaltijdmomenten herkend zijn, geschatte kcal tot nu toe en je resterende budget (inclusief sport-verhoogd dagdoel). Staat er morgen een zware training in je intervals.icu-kalender, dan krijg je het advies om vanavond extra koolhydraten te eten. Faalt het slimme pad, dan valt de bot altijd terug op de generieke herinnering.

</details>

<details>
<summary>💡 <b>/tips</b> — live caloriebudget op aanvraag</summary>

Geeft op aanvraag een overzicht van je dag tot nu toe: hoeveel al gegeten, hoeveel budget er nog over is (tegen het dynamische dagdoel), macro-voortgang en 2–3 concrete suggesties voor de rest van de dag — met kennis van je herstel van vannacht en een verhoogd eiwitdoel op zware trainingsdagen. Wordt elke 10 minuten gecheckt.

</details>

<details>
<summary>🚴 <b>Sport-integratie</b> — exacte Garmin-kcal verhogen je dagbudget</summary>

Sportactiviteiten worden automatisch uitgelezen via de gratis [intervals.icu](https://intervals.icu) API met **exacte kcal uit je Garmin-meting** — geen AI-schatting. Elke activiteit komt in de Sport-tab (dedupe op Intervals ID), en het dagbudget stijgt mee: *doel + sport_compensatie × verbrande kcal* (een rit van 600 kcal maakt van 2750 dus 3350). De 23:58-analyse, /tips en de slimme herinnering rekenen er allemaal mee; de TDEE-schatting blijft bewust ongemoeid (sport zit daar al impliciet in). Valt intervals.icu weg, dan werkt alles gewoon zonder sportregel. Setup: [docs/intervals.md](docs/intervals.md).

</details>

<details>
<summary>🫀 <b>Wellness & herstel</b> — HRV, slaap en rusthartslag sturen het advies</summary>

Dezelfde koppeling leest ook Garmins nachtdata. De AI-analyse en /tips krijgen je herstelstatus mee ("HRV 58 · 6.8u slaap"), op zware trainingsdagen (TSS ≥ drempel) stijgt het eiwitdoel automatisch (+20g), en hapert je herstel meerdere dagen (lage HRV + verhoogde rusthartslag) dan krijg je om 15:00 eenmalig een waarschuwing — die herhaalt zichzelf niet zolang de dip aanhoudt. Historiek backfillen kan met de handmatige *Wellness-import* workflow. Bewuste keuze: géén herstelcontext bij de ochtendvraag (onregelmatige opsta-tijden + de Garmin-sync is dan niet gegarandeerd al gebeurd).

</details>

<details>
<summary>📤 <b>Terugschrijven naar intervals.icu</b> — voeding naast je trainingsdata</summary>

De datastroom werkt ook omgekeerd: je ochtendgewicht gaat naar intervals.icu (W/kg en eFTP kloppen daar dus altijd), de dagelijkse kcal-inname, macro's (eiwit/koolhydraten/vet via de ingebouwde voedingsvelden) en voedingsscore komen in je wellness-record (plotbaar tegen HRV, slaap en trainingsload), het dagoverzicht verschijnt als 🍽️-notitie in je trainingskalender, en elke activiteit krijgt een fueling-regel ("Gevoed: 2800 kcal · 150g eiwit"). Her-runs verdubbelen niets: notities worden bijgewerkt en de fueling-regel vervangen. Elk onderdeel apart uitschakelbaar via `config.json` (blok `intervals_upload`). Setup van de custom velden: [docs/intervals.md](docs/intervals.md).

</details>

<details>
<summary>📊 <b>Wekelijks overzicht</b> — maandag 08:00, met TDEE en correlaties</summary>

Elke maandag: gemiddelden per macro, vergelijking met je doelen (tegen het gemiddelde dynamische dagdoel) en vorige week, sportblok, herstelblok (HRV/RHR/slaap-trend) en een gewichtstrend op het 7-daags gemiddelde. Plus een **TDEE-schatting** — je werkelijke dagelijkse verbruik, berekend uit intake en gewichtsverloop (verschijnt na ±2 weken data). Uniek: voeding↔herstel-correlaties zoals "nacht na alcohol: HRV −12 · slaapscore −15" — pas getoond vanaf ±3 weken data om schijnverbanden te vermijden.

</details>

<details>
<summary>📅 <b>Maandrapport</b> — 1e van de maand, 6 grafieken</summary>

Een foto met 6 grafieken: gewicht + trend, kcal/dag vs. (dynamisch) doel met sport-overlay, eiwit/dag, maaltijdverdeling per week, HRV + rusthartslag, en slaap (uren + score). Plus samenvatting met sport- en herstelstatistieken, beste week, TDEE en een AI-reflectie. Heeft een `test_mode` om direct een rapport over de lopende maand te genereren.

</details>

<details>
<summary>🍳 <b>Recepten</b> — exacte waarden i.p.v. schattingen</summary>

Voeg recepten toe via `/recept_ai` (AI berekent macro's) of `/recept` (eigen macro's opgeven). Recepten worden automatisch herkend in maaltijdlogs voor exacte berekeningen in plaats van AI-schattingen. Beschikbaar via het receptenboek op GitHub Pages, bookmarkbaar als app op je startscherm.

</details>

<details>
<summary>📈 <b>Statistieken-dashboard</b> — alles in grafieken op je telefoon</summary>

`stats.html` op je GitHub Pages site: grafieken (Chart.js) van gewicht, 🫀 herstel (HRV + slaapscore + RHR), calorieën — met 🚴-markers en een doellijn die meestijgt op sportdagen — eiwitten, maaltijdverdeling en dagscore, met periode-toggle (30/90/alles). Beveiligd met een API-key die alleen in localStorage van je toestel staat — je data blijft privé, ook in een publieke repo. Setup: [docs/dashboard.md](docs/dashboard.md).

</details>

## Dagelijkse flow

| Tijdstip | Actie |
|---|---|
| 07:00 | Gewichtsvraag |
| 15:00 | Gewicht opslaan (ook naar intervals.icu) + herstel-check (eenmalig signaal bij haperend herstel) |
| 21:00 | Slimme herinnering (+ carb-advies bij zware geplande training morgen) |
| 23:58 | AI-analyse en opslag: maaltijden, sport, wellness (+ gewicht-vangnet) → daarna kcal/score/eiwit, kalendernotitie en fueling-regel naar intervals.icu |
| Maandag 08:00 | Wekelijks rapport met TDEE, sport en herstel |
| 1e van de maand 08:30 | Maandrapport met 6 grafieken |
| Elke 10 min | /tips check |
| Elke 30 min | Recepten check |
| Handmatig | Wellness-import: historiek backfillen vanaf een startdatum |

## Configuratie

Alles wordt centraal beheerd in `data/config/config.json`. Pas aan en push — alle workflows pikken de nieuwe waarden automatisch op.

<details>
<summary><b>Bekijk het volledige config-voorbeeld</b></summary>

```json
{
  "doelen": {
    "kcal": 2750,
    "eiwitten": 150,
    "koolhydraten": 320,
    "vetten": 85,
    "vezels": 30,
    "richting": "aankomen",
    "sport_compensatie": 1.0
  },
  "wellness": {
    "tss_zware_dag": 100,
    "eiwit_extra_g": 20,
    "hrv_alert_dagen": 3,
    "rhr_alert_boven_baseline": 3
  },
  "intervals_upload": {
    "gewicht": true,
    "gewicht_locked": false,
    "kcal": true,
    "kcal_veld": "kcalConsumed",
    "custom_velden": {
      "Voedingsscore": "score",
      "protein": "eiwitten",
      "carbohydrates": "koolhydraten",
      "fatTotal": "vetten"
    },
    "kalendernotitie": true,
    "activiteit_beschrijving": true
  }
}
```

- `richting` is `aankomen`, `afvallen` of `onderhouden` — alle AI-feedback (scores, tips, reflecties) houdt er rekening mee.
- `sport_compensatie` bepaalt hoeveel van de verbrande sport-kcal bij het dagdoel komt: `1.0` = alles terug-eten (logisch bij aankomen), `0.5` = halve compensatie als buffer tegen overschatting (gangbaar bij afvallen), `0` = sport alleen loggen.
- Het `wellness`-blok stuurt de herstel-features: vanaf welke trainingsload een dag "zwaar" is (eiwitdoel +`eiwit_extra_g`) en hoe gevoelig het overtraining-signaal is.
- Het `intervals_upload`-blok schakelt elk terugschrijf-onderdeel apart aan/uit; zie [docs/features.md](docs/features.md) voor de volledige referentie.

</details>

## Setup

Maak je repo **publiek**: GitHub Actions-minuten zijn dan onbeperkt en GitHub Pages is gratis. (Je recepten staan dan publiek; je maaltijd- en gewichtsdata niet — die zitten in Google Sheets achter een API-key.)

Volg de stappen in volgorde:

1. **Fork deze repo** en pas `data/config/config.json` aan; zet `data/config/recepten.json` op `{}`; vervang de naam "Marti" in `scripts/remind.py` en `scripts/monthly_report.py`.
2. [Telegram bot](docs/telegram-bot.md) — bot aanmaken, `BOT_TOKEN` en `CHAT_ID` ophalen
3. [Groq AI](docs/groq-ai.md) — account en `GROQ_API_KEY`
4. [Google Sheets](docs/google-sheets.md) — spreadsheet, Apps Script, API-key, `APPS_SCRIPT_URL` en `APPS_SCRIPT_KEY`
5. **GitHub Pages**: Settings → Pages → Source: *GitHub Actions* (de `pages.yaml` workflow deployt bij elke push)
6. [cron-job.org](docs/cronjob.md) — GitHub PAT, job-URL's en tijdsinstellingen
7. [Dashboard](docs/dashboard.md) — eenmalig URL + key invullen
8. [intervals.icu](docs/intervals.md) *(optioneel)* — sport-, wellness- en terugschrijf-integratie met Garmin: account, Garmin-sync en `INTERVALS_API_KEY`
9. **Testen**: run elke workflow één keer handmatig via Actions → *Run workflow*. Het maandrapport heeft een `test_mode`-optie voor een direct rapport over de lopende maand.

De bot reageert uitsluitend op jouw `CHAT_ID` — anderen die je bot vinden kunnen er niets mee.

## Documentatie

| Doc | Inhoud |
|---|---|
| [docs/features.md](docs/features.md) | **Hoe alles werkt** — elke run, regel, drempel en het datamodel |
| [docs/telegram-bot.md](docs/telegram-bot.md) | Telegram-bot aanmaken |
| [docs/groq-ai.md](docs/groq-ai.md) | Groq AI-account en key |
| [docs/google-sheets.md](docs/google-sheets.md) | Spreadsheet, tabs en Apps Script |
| [docs/cronjob.md](docs/cronjob.md) | Exacte tijdsturing via cron-job.org |
| [docs/dashboard.md](docs/dashboard.md) | Statistieken-dashboard instellen |
| [docs/intervals.md](docs/intervals.md) | Garmin/intervals.icu: sport, wellness, terugschrijven, backfill |

## Tech stack

| Component | Dienst | Kosten |
|---|---|---|
| Bot | Telegram | gratis |
| Scheduling | cron-job.org | gratis |
| Verwerking | GitHub Actions | gratis (publieke repo) |
| AI | Groq API | gratis tier |
| Opslag | Google Sheets + Apps Script | gratis |
| Website + dashboard | GitHub Pages | gratis |
| Sport- & hersteldata | intervals.icu API (Garmin-sync) | gratis |

## Goed om te weten

- Macro's zijn AI-schattingen op basis van tekstbeschrijvingen (Belgische portiegroottes) — geen weegschaal-precisie, maar consistent genoeg voor trends. Recepten geven exacte waarden. Sport-kcal en wellness-data zijn wél exacte Garmin-metingen.
- Alle intervals.icu-integraties falen stil: geen key of een storing → de bot werkt gewoon zonder die verrijking, de maaltijdverwerking breekt nooit.
- In `tests/` staat een offline testsuite (geen netwerk of API-keys nodig): `python tests/test_sport_integratie.py` en `node tests/test_apps_script.js`.
- Telegram bewaart onbevestigde berichten maximaal 24 uur; de dagverwerking om 23:58 bevestigt ze. Daarom hoort die vóór middernacht te draaien — zo klopt ook de datum van de opgeslagen dag.
- Alle botteksten en AI-prompts zijn Nederlandstalig; pas de prompts in `scripts/` aan voor een andere taal of regio.
