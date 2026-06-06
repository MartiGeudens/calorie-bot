# Calorie Tracker Bot

Persoonlijke Telegram-bot die maaltijden logt, macro's analyseert via AI en alles opslaat in Google Sheets. Volledig cloudgebaseerd via GitHub Actions — geen lokale server vereist.

## Architectuur

```
Telegram Bot
    ↕
GitHub Actions  →  Groq AI (llama-3.3-70b-versatile)
    ↓
Google Sheets  →  Google Doc (Claude Project sync)

GitHub Pages  →  Receptenboek
cron-job.org  →  Tijdsbeheer workflows
```

## Features

### Maaltijden loggen
Stuur maaltijden als gewone berichten doorheen de dag. Elke nacht om 00:00 analyseert de bot alles automatisch en stuurt een overzicht met totale calorieën, macro's per maaltijdmoment, een score op 10 en een persoonlijke tip.

### Gewicht bijhouden
Dagelijkse ochtendvraag om 09:00. Antwoord met een getal (bv. `72.5`), wordt om 15:00 opgeslagen.

### /tips
Geeft op aanvraag een live overzicht van het caloriëbudget: hoeveel al gegeten, hoeveel nog over, en concrete aanbevelingen voor de rest van de dag. Wordt elke 10 minuten gecheckt.

### Wekelijks overzicht
Elke maandag om 08:00: gemiddelden per macro, vergelijking met de persoonlijke doelen, gewichtstrend en een AI-tip gericht op het belangrijkste verbeterpunt van de week.

### Recepten
Voeg recepten toe via `/recept_ai` (AI berekent macro's) of `/recept` (eigen macro's opgeven). Recepten worden automatisch herkend in maaltijdlogs voor exacte berekeningen in plaats van AI-schattingen. Beschikbaar via het receptenboek op GitHub Pages.

## Configuratie

Macrodoelen worden centraal beheerd in `config.json`. Pas dit bestand aan en push — alle workflows pikken de nieuwe waarden automatisch op.

```json
{
  "doelen": {
    "kcal": 2750,
    "eiwitten": 150,
    "koolhydraten": 320,
    "vetten": 85,
    "vezels": 30
  }
}
```

## Dagelijkse flow

| Tijdstip | Actie |
|---|---|
| 07:00 | Gewichtsvraag |
| 15:00 | Gewicht opslaan |
| 21:00 | Herinnering maaltijden |
| 00:00 | AI-analyse en opslag |
| Maandag 08:00 | Wekelijks rapport |
| Elke 10 min | /tips check |
| Elke 30 min | Recepten check |

## Tech stack

| Component | Dienst |
|---|---|
| Bot | Telegram |
| Scheduling | cron-job.org |
| Verwerking | GitHub Actions |
| AI | Groq API |
| Opslag | Google Sheets |
| Website | GitHub Pages |
