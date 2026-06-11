# Calorie Tracker Bot

Persoonlijke Telegram-bot die maaltijden logt, macro's analyseert via AI en alles opslaat in Google Sheets. Volledig cloudgebaseerd via GitHub Actions — geen lokale server vereist, alles draait op gratis diensten.

## Architectuur

```
Telegram Bot
    ↕
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
Dagelijkse ochtendvraag om 09:00. Antwoord met een getal (bv. `72.5`), wordt om 15:00 opgeslagen. Stuur je het later? De dagverwerking om 23:58 vangt het alsnog op.

### Slimme avondherinnering
Om 21:00 checkt de bot wat je al logde: nog niets → gewone herinnering; wel al berichten → welke maaltijdmomenten herkend zijn, geschatte kcal tot nu toe en je resterende budget.

### /tips
Geeft op aanvraag een live overzicht van het caloriebudget: hoeveel al gegeten, hoeveel nog over, en concrete aanbevelingen voor de rest van de dag. Wordt elke 10 minuten gecheckt.

### Wekelijks overzicht
Elke maandag om 08:00: gemiddelden per macro, vergelijking met je doelen en vorige week, gewichtstrend op basis van een 7-daags voortschrijdend gemiddelde, en een **TDEE-schatting** — je werkelijke dagelijkse verbruik, berekend uit je intake en gewichtsverloop (verschijnt na ±2 weken data).

### Maandrapport
Op de 1e van de maand: een foto met 4 grafieken (gewicht + trend, kcal/dag vs. doel, eiwit/dag, maaltijdverdeling per week) plus samenvatting, TDEE en AI-reflectie.

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
    "richting": "aankomen"
  }
}
```

`richting` is `aankomen`, `afvallen` of `onderhouden` — alle AI-feedback (scores, tips, reflecties) houdt er rekening mee.

## Dagelijkse flow

| Tijdstip | Actie |
|---|---|
| 09:00 | Gewichtsvraag |
| 15:00 | Gewicht opslaan |
| 21:00 | Slimme herinnering |
| 23:58 | AI-analyse en opslag (+ gewicht-vangnet) |
| Maandag 08:00 | Wekelijks rapport met TDEE |
| 1e van de maand 08:30 | Maandrapport met grafieken |
| Elke 10 min | /tips check |
| Elke 30 min | Recepten check |

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
8. **Testen**: run elke workflow één keer handmatig via Actions → *Run workflow*. Het maandrapport heeft een `test_mode`-optie voor een direct rapport over de lopende maand.

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

## Goed om te weten

- Macro's zijn AI-schattingen op basis van tekstbeschrijvingen (Belgische portiegroottes) — geen weegschaal-precisie, maar consistent genoeg voor trends. Recepten geven exacte waarden.
- Telegram bewaart onbevestigde berichten maximaal 24 uur; de dagverwerking om 23:58 bevestigt ze. Daarom hoort die vóór middernacht te draaien — zo klopt ook de datum van de opgeslagen dag.
- Alle botteksten en AI-prompts zijn Nederlandstalig; pas de prompts in `scripts/` aan voor een andere taal of regio.
