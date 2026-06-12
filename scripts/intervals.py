"""
intervals.icu helper — haalt sportactiviteiten op met exacte kcal-data (Garmin-meting).

Auth: HTTP Basic met username "API_KEY" en de key als wachtwoord (secret INTERVALS_API_KEY).
Atleet-ID "0" in het pad = de eigenaar van de API-key.

Ontwerpprincipe: sport mag NOOIT de hoofdflow blokkeren.
Geen key, API onbereikbaar of onverwacht antwoord → lege lijst, nooit een exception.
"""

import os
import requests

API_BASE = "https://intervals.icu/api/v1"


def _num(val, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def activiteiten_tussen(oudste: str, nieuwste: str) -> list:
    """Activiteiten in de periode [oudste, nieuwste] (YYYY-MM-DD, lokale datums).

    Geeft platte dicts terug: id, datum, naam, type, duur_min, afstand_km, kcal, gem_hs.
    Lege lijst zonder INTERVALS_API_KEY of bij elke fout (faalt stil)."""
    api_key = os.environ.get("INTERVALS_API_KEY", "")
    if not api_key:
        print("intervals.icu: geen INTERVALS_API_KEY ingesteld — sport overgeslagen")
        return []

    try:
        resp = requests.get(
            f"{API_BASE}/athlete/0/activities",
            params={"oldest": oudste, "newest": nieuwste},
            auth=("API_KEY", api_key),
            timeout=15,
        )
        if not resp.ok:
            print(f"intervals.icu: HTTP {resp.status_code} — sport overgeslagen")
            return []
        raw = resp.json()
    except Exception as e:
        print(f"intervals.icu onbereikbaar: {e} — sport overgeslagen")
        return []

    if not isinstance(raw, list):
        print("intervals.icu: onverwacht antwoord — sport overgeslagen")
        return []

    activiteiten = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        duur_sec = _num(a.get("moving_time")) or _num(a.get("elapsed_time"))
        activiteiten.append({
            "id":         str(a.get("id", "")),
            "datum":      str(a.get("start_date_local", ""))[:10] or oudste,
            "naam":       a.get("name") or a.get("type") or "Activiteit",
            "type":       a.get("type") or "",
            "duur_min":   int(round(duur_sec / 60)),
            "afstand_km": round(_num(a.get("distance")) / 1000, 1),
            # Activiteit zonder calories (bv. manueel toegevoegd) → kcal 0:
            # wel gelogd in de Sport-tab, telt niet mee voor het budget.
            "kcal":       int(round(_num(a.get("calories")))),
            "gem_hs":     int(round(_num(a.get("average_heartrate")))),
        })
    return activiteiten


def activiteiten_van(datum: str) -> list:
    """Alle activiteiten van één dag (YYYY-MM-DD)."""
    return [a for a in activiteiten_tussen(datum, datum) if a["datum"] == datum]


def sport_kcal_totaal(activiteiten: list) -> int:
    """Som van de verbrande kcal over alle activiteiten."""
    return int(sum(_num(a.get("kcal")) for a in activiteiten))


def sport_regel(activiteiten: list) -> str:
    """Korte samenvatting voor in berichten, bv. 'Ride 92 min · 45.2 km'."""
    delen = []
    for a in activiteiten:
        stuk = a.get("type") or a.get("naam") or "Activiteit"
        if a.get("duur_min"):
            stuk += f" {a['duur_min']} min"
        if a.get("afstand_km"):
            stuk += f" · {a['afstand_km']} km"
        delen.append(stuk)
    return " + ".join(delen)


def dagdoel(doel_kcal: int, compensatie: float, sport_kcal: int) -> int:
    """Dynamisch dagbudget: doel + compensatie × verbrande sport-kcal."""
    return int(round(doel_kcal + compensatie * sport_kcal))
