"""
intervals.icu helper — haalt sportactiviteiten op met exacte kcal-data (Garmin-meting).

Auth: HTTP Basic met username "API_KEY" en de key als wachtwoord (secret INTERVALS_API_KEY).
Atleet-ID "0" in het pad = de eigenaar van de API-key.

Ontwerpprincipe: sport mag NOOIT de hoofdflow blokkeren.
Geen key, API onbereikbaar of onverwacht antwoord → lege lijst, nooit een exception.
"""

import os
import re
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
            # Trainingsload (TSS) — voor het dynamische eiwitdoel op zware dagen
            "load":       int(round(_num(a.get("icu_training_load")))),
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


def sport_load_totaal(activiteiten: list) -> int:
    """Som van de trainingsload (TSS) over alle activiteiten."""
    return int(sum(_num(a.get("load")) for a in activiteiten))


def _opt(val):
    """Numerieke waarde of None (0/ontbrekend = geen meting)."""
    n = _num(val)
    return n if n > 0 else None


def wellness_tussen(oudste: str, nieuwste: str) -> list:
    """Wellness-records (Garmin via intervals.icu) in [oudste, nieuwste].

    Per dag: datum, hrv, rhr, slaap_u, slaapscore, readiness — None waar geen meting is.
    Lege lijst zonder key of bij elke fout (faalt stil)."""
    api_key = os.environ.get("INTERVALS_API_KEY", "")
    if not api_key:
        print("intervals.icu: geen INTERVALS_API_KEY ingesteld — wellness overgeslagen")
        return []

    try:
        resp = requests.get(
            f"{API_BASE}/athlete/0/wellness",
            params={"oldest": oudste, "newest": nieuwste},
            auth=("API_KEY", api_key),
            timeout=15,
        )
        if not resp.ok:
            print(f"intervals.icu wellness: HTTP {resp.status_code} — overgeslagen")
            return []
        raw = resp.json()
    except Exception as e:
        print(f"intervals.icu wellness onbereikbaar: {e} — overgeslagen")
        return []

    if not isinstance(raw, list):
        print("intervals.icu wellness: onverwacht antwoord — overgeslagen")
        return []

    records = []
    for w in raw:
        if not isinstance(w, dict):
            continue
        slaap_sec = _opt(w.get("sleepSecs"))
        records.append({
            "datum":      str(w.get("id", ""))[:10],
            "hrv":        _opt(w.get("hrv")),
            "rhr":        _opt(w.get("restingHR")),
            "slaap_u":    round(slaap_sec / 3600, 1) if slaap_sec else None,
            "slaapscore": _opt(w.get("sleepScore")),
            "readiness":  _opt(w.get("readiness")),
        })
    records.sort(key=lambda r: r["datum"])
    return records


def wellness_van(datum: str):
    """Wellness-record van één dag, of None."""
    for r in wellness_tussen(datum, datum):
        if r["datum"] == datum:
            return r
    return None


def wellness_regel(w) -> str:
    """Korte herstel-samenvatting voor in AI-prompts, bv. 'HRV 62 · RHR 48 · 7.3u slaap (score 81)'."""
    if not w:
        return ""
    delen = []
    if w.get("hrv"):
        delen.append(f"HRV {round(w['hrv'])}")
    if w.get("rhr"):
        delen.append(f"RHR {round(w['rhr'])}")
    if w.get("slaap_u"):
        slaap = f"{w['slaap_u']}u slaap"
        if w.get("slaapscore"):
            slaap += f" (score {round(w['slaapscore'])})"
        delen.append(slaap)
    return " · ".join(delen)


def hrv_baseline(records: list, eind_datum: str, venster: int = 7, min_dagen: int = 4):
    """Gemiddelde HRV over de `venster` dagen vóór (exclusief) eind_datum.
    None bij minder dan min_dagen metingen."""
    import datetime as _dt
    try:
        eind = _dt.date.fromisoformat(eind_datum)
    except ValueError:
        return None
    span = {( eind - _dt.timedelta(days=i)).isoformat() for i in range(1, venster + 1)}
    vals = [r["hrv"] for r in records if r["datum"] in span and r.get("hrv")]
    return round(sum(vals) / len(vals), 1) if len(vals) >= min_dagen else None


def herstel_alert(records: list, vandaag: str, hrv_dagen: int = 3, rhr_delta: float = 3.0):
    """Overtraining/ziekte-signaal: HRV `hrv_dagen` opeenvolgende dagen onder de
    7d-baseline én gemiddelde RHR in die dagen minstens `rhr_delta` boven de baseline.

    Geeft een dict met context terug als de alert vuurt, anders None.
    Stateless en conservatief: te weinig data → None."""
    import datetime as _dt
    try:
        eind = _dt.date.fromisoformat(vandaag)
    except ValueError:
        return None

    per_datum = {r["datum"]: r for r in records}
    recent = [per_datum.get((eind - _dt.timedelta(days=i)).isoformat()) for i in range(hrv_dagen)]
    if any(r is None or not r.get("hrv") for r in recent):
        return None  # geen volledige HRV-reeks → geen oordeel

    # baseline: de 7 dagen vóór het recente venster
    base_eind = (eind - _dt.timedelta(days=hrv_dagen - 1)).isoformat()
    hrv_base = hrv_baseline(records, base_eind)
    if hrv_base is None:
        return None

    if not all(r["hrv"] < hrv_base for r in recent):
        return None

    # RHR-conditie: gemiddelde van het recente venster vs. dezelfde baseline-periode
    base_span = {(eind - _dt.timedelta(days=i)).isoformat() for i in range(hrv_dagen, hrv_dagen + 7)}
    rhr_base_vals = [r["rhr"] for r in records if r["datum"] in base_span and r.get("rhr")]
    rhr_recent_vals = [r["rhr"] for r in recent if r.get("rhr")]
    if len(rhr_base_vals) < 4 or not rhr_recent_vals:
        return None
    rhr_base = sum(rhr_base_vals) / len(rhr_base_vals)
    rhr_nu = sum(rhr_recent_vals) / len(rhr_recent_vals)
    if rhr_nu < rhr_base + rhr_delta:
        return None

    return {
        "hrv_nu": round(sum(r["hrv"] for r in recent) / len(recent), 1),
        "hrv_baseline": hrv_base,
        "rhr_nu": round(rhr_nu, 1),
        "rhr_baseline": round(rhr_base, 1),
        "dagen": hrv_dagen,
    }


def geplande_workouts(datum: str) -> list:
    """Geplande workouts (category WORKOUT) uit de intervals.icu-kalender voor één dag.
    Per workout: naam, type, duur_min, load. Lege lijst zonder key/kalender of bij fouten."""
    api_key = os.environ.get("INTERVALS_API_KEY", "")
    if not api_key:
        return []
    try:
        resp = requests.get(
            f"{API_BASE}/athlete/0/events",
            params={"oldest": datum, "newest": datum},
            auth=("API_KEY", api_key),
            timeout=15,
        )
        if not resp.ok:
            print(f"intervals.icu events: HTTP {resp.status_code} — overgeslagen")
            return []
        raw = resp.json()
    except Exception as e:
        print(f"intervals.icu events onbereikbaar: {e} — overgeslagen")
        return []
    if not isinstance(raw, list):
        return []

    workouts = []
    for ev in raw:
        if not isinstance(ev, dict) or ev.get("category") != "WORKOUT":
            continue
        workouts.append({
            "naam":     ev.get("name") or ev.get("type") or "Workout",
            "type":     ev.get("type") or "",
            "duur_min": int(round(_num(ev.get("moving_time")) / 60)),
            "load":     int(round(_num(ev.get("icu_training_load")))),
        })
    return workouts


# Voeding ↔ herstel-correlaties ────────────────────────────────────────────────
ALCOHOL_RE = re.compile(
    r"\b(bier(tje)?s?|pint(je)?s?|pils|wijn(tje)?s?|alcohol|cocktails?|gin|tonic|"
    r"whisky|whiskey|wodka|vodka|rum|likeur(tje)?s?|cava|prosecco|champagne|duvels?|"
    r"tripels?|trappisten?|westmalle|chouffe|aperol|spritz|sangria|mojito|jenever|"
    r"porto|martini)\b"
)


def alcohol_contrast(maaltijd_rows: list, wellness_records: list,
                     min_alcohol: int = 3, min_wellness: int = 21):
    """Vergelijkt herstel in de nacht ná dagen met alcohol vs. andere dagen.

    Conservatief: pas een resultaat vanaf `min_wellness` HRV-nachten en
    `min_alcohol` dagen in beide groepen — anders schijnverbanden.
    Geeft {"n_alcohol", "d_hrv", "d_slaapscore"} of None."""
    hrv_nachten = [r for r in wellness_records if isinstance(r, dict) and r.get("hrv")]
    if len(hrv_nachten) < min_wellness:
        return None

    import datetime as _dt
    w_by_date = {r["datum"]: r for r in wellness_records if isinstance(r, dict) and r.get("datum")}

    alc, rest = [], []
    for row in maaltijd_rows:
        if not isinstance(row, dict):
            continue
        datum = str(row.get("datum", ""))[:10]
        tekst = str(row.get("maaltijden", "")).lower()
        if not datum or not tekst:
            continue
        try:
            volgende = (_dt.date.fromisoformat(datum) + _dt.timedelta(days=1)).isoformat()
        except ValueError:
            continue
        w = w_by_date.get(volgende)
        if not w or not w.get("hrv"):
            continue  # geen nachtdata na deze dag
        (alc if ALCOHOL_RE.search(tekst) else rest).append(w)

    if len(alc) < min_alcohol or len(rest) < min_alcohol:
        return None

    def _gem(rs, key):
        vals = [r[key] for r in rs if r.get(key)]
        return sum(vals) / len(vals) if vals else None

    d_hrv = _gem(alc, "hrv") - _gem(rest, "hrv")
    s_alc, s_rest = _gem(alc, "slaapscore"), _gem(rest, "slaapscore")
    d_slaap = (s_alc - s_rest) if (s_alc is not None and s_rest is not None) else None
    return {
        "n_alcohol": len(alc),
        "d_hrv": round(d_hrv, 1),
        "d_slaapscore": round(d_slaap, 1) if d_slaap is not None else None,
    }
