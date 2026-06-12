# Calorie Tracker Bot

Persoonlijke Telegram-bot die maaltijden logt, macro's analyseert via AI en alles opslaat in Google Sheets. Volledig cloudgebaseerd via GitHub Actions — geen lokale server vereist, alles draait op gratis diensten.

## Architectuur

```
Telegram Bot                     Garmin → intervals.icu (sport-kcal)
    ↕                                ↓ API-key
GitHub Actions  →  Groq AI (llama-3.3-70b-versatile)
    ↓
Google Sheets  ←→  Apps Script Web App (doPost/doGet met API-key)
    ↓
Google Doc (optionele AI-assistent sync)

GitHub Pages  →  Receptenboek + Statistieken-dashboard
cron-job.org  →  Tijdsbeheer workflows (exacte tijden)
```

## Features

### Maaltijden loggen
Stuur maaltijden als gewone berichten doorheen de dag (`lunch: broodje kaas en tomaat`). Elke avond om 23:58 analyseert de bot alles automatisch en stuurt een overzicht met totale calorieën, macro's per maaltijdmoment (ontbijt/lunch/avondeten/snacks), een score op 10 en een persoonlijke tip. Labels zijn optioneel maar verbeteren de uitsplitsing.

### Gewicht bijhouden
Dagelijkse ochtendvraag om 07:00. Antwoord met een getal (bv. `72.5`), wordt om 15:00 opgeslagen. Stuur je het later? De dagverwerking om 23:58 vangt het alsnog op.

### Slimme avondherinnering
Om 21:00 checkt de bot wat je al logde: nog niets → gewone herinnering; wel al berichten → welke maaltijdmomenten herkend zijn, geschatte kcal tot nu toe en je resterende budget.

### /tips
Geeft op aanvraag een live overzicht van het caloriebudget: hoeveel al gegeten, hoeveel nog over, en concrete aanbevelingen voor de rest van de dag. Wordt elke 10 minuten gecheckt.

### Wekelijks overzicht
Elke maandag om 08:00: gemiddelden per macro, vergelijking met je doelen en vorige week, gewichtstrend op basis van een 7-daags voortschrijdend gemiddelde, en een **TDEE-schatting** — je werkelijke dagelijkse verbruik, berekend uit je intake en gewichtsverloop (verschijnt na ±2 weken data).

### Maandrapport
Op de 1e van de maand: een foto met 6 grafieken (gewicht + trend, kcal/dag vs. doel met sport-overlay, eiwit/dag, maaltijdverdeling per week, HRV + rusthartslag, slaap) plus samenvatting, sport- en herstelstatistieken, TDEE en AI-reflectie.

### Sport-integratie (Garmin → intervals.icu)
Sportactiviteiten worden automatisch uitgelezen via de gratis [intervals.icu](https://intervals.icu) API met **exacte kcal uit je Garmin-meting** — geen AI-schatting. Elke activiteit komt in de Sport-tab, en het dagbudget stijgt mee: *doel + sport_compensatie × verbrande kcal* (een rit van 600 kcal maakt van 2750 dus 3350). De 23:58-analyse, /tips en de slimme herinnering rekenen er allemaal mee; de TDEE-schatting blijft bewust ongemoeid (sport zit daar al impliciet in). Valt intervals.icu weg, dan werkt alles gewoon zonder sportregel. Setup: [docs/intervals.md](docs/intervals.md).

### Wellness & herstel (HRV, slaap, rusthartslag)
Dezelfde koppeling leest ook Garmins nachtdata. De AI-analyse en /tips krijgen je herstelstatus mee ("HRV 58 · 6.8u slaap"), op zware trainingsdagen (TSS ≥ drempel) stijgt het eiwitdoel automatisch (+20g), en hapert je herstel meerdere dagen (lage HRV + verhoogde rusthartslag) dan krijg je om 15:00 eenmalig een waarschuwing. Het weekrapport toont HRV/RHR/slaap-trends én unieke voeding↔herstel-correlaties ("nacht na alcohol: HRV −12") zodra er ±3 weken data is; het maandrapport en dashboard krijgen herstel- en slaapgrafieken. Staat er morgen een zware training in je intervals.icu-kalender, dan adviseert de avondherinnering extra koolhydraten. Drempels in `config.json` (blok `wellness`).

### Recepten
Voeg recepten toe via `/recept_ai` (AI berekent macro's) of `/recept` (eigen macro's opgeven). Recepten worden automatisch herkend in maaltijdlogs voor exacte berekeningen in plaats van AI-schattingen. Beschikbaar via het receptenboek op GitHub Pages.

### Statistieken-dashboard
`stats.html` op je GitHub Pages site: grafieken (Chart.js) van gewicht, calorieën, eiwitten, maaltijdverdeling en dagscore, met periode-toggle. Beveiligd met een API-key die alleen in localStorage van je toestel staat — je data blijft privé, ook in een publieke repo.

## Configuratie

Macrodoelen en doel-richting worden centraal beheerd in `data/config/config.json`. Pas aan en push — alle workflows pikken de nieuwe waarden automatisch op.

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
  }
}
```

`richting` is `aankomen`, `afvallen` of `onderhouden` — alle AI-feedback (scores, tips, reflecties) houdt er rekening mee.

`sport_compensatie` bepaalt hoeveel van de verbrande sport-kcal bij het dagdoel komt: `1.0` = alles terug-eten (logisch bij aankomen), `0.5` = halve compensatie als buffer tegen overschatting (gangbaar bij afvallen).

Het `wellness`-blok stuurt de herstel-features: vanaf welke trainingsload een dag "zwaar" is en het eiwitdoel met `eiwit_extra_g` stijgt, en hoe gevoelig het overtraining-signaal is (aantal nachten onder de HRV-baseline + vereiste RHR-verhoging).

## Dagelijkse flow

| Tijdstip | Actie |
|---|---|
| 07:00 | Gewichtsvraag |
| 15:00 | Gewicht opslaan + herstel-check (eenmalig signaal bij haperend herstel) |
| 21:00 | Slimme herinnering (+ carb-advies bij zware geplande training morgen) |
| 23:58 | AI-analyse en opslag: maaltijden, sport, wellness (+ gewicht-vangnet) |
| Maandag 08:00 | Wekelijks rapport met TDEE, sport en herstel |
| 1e van de maand 08:30 | Maandrapport met 6 grafieken |
| Elke 10 min | /tips check |
| Elke 30 min | Recepten check |
| Handmatig | Wellness-import: historiek backfillen vanaf een startdatum |

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
8. [intervals.icu](docs/intervals.md) *(optioneel)* — sport-integratie met Garmin: account, Garmin-sync en `INTERVALS_API_KEY`
9. **Testen**: run elke workflow één keer handmatig via Actions → *Run workflow*. Het maandrapport heeft een `test_mode`-optie voor een direct rapport over de lopende maand.

De bot reageert uitsluitend op jouw `CHAT_ID` — anderen die je bot vinden kunnen er niets mee.

## Tech stack

| Component | Dienst | Kosten |
|---|---|---|
| Bot | Telegram | gratis |
| Scheduling | cron-job.org | gratis |
| Verwerking | GitHub Actions | gratis (publieke repo) |
| AI | Groq API | gratis tier |
| Opslag | Google Sheets + Apps Script | gratis |
| Website + dashboard | GitHub Pages | gratis |
| Sport-data | intervals.icu API (Garmin-sync) | gratis |

## Goed om te weten

- Macro's zijn AI-schattingen op basis van tekstbeschrijvingen (Belgische portiegroottes) — geen weegschaal-precisie, maar consistent genoeg voor trends. Recepten geven exacte waarden. Sport-kcal en wellness-data zijn wél exacte Garmin-metingen.
- In `tests/` staat een offline testsuite (geen netwerk of API-keys nodig): `python tests/test_sport_integratie.py` en `node tests/test_apps_script.js`.
- Telegram bewaart onbevestigde berichten maximaal 24 uur; de dagverwerking om 23:58 bevestigt ze. Daarom hoort die vóór middernacht te draaien — zo klopt ook de datum van de opgeslagen dag.
- Alle botteksten en AI-prompts zijn Nederlandstalig; pas de prompts in `scripts/` aan voor een andere taal of regio.
