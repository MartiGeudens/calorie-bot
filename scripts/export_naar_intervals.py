"""
Eenmalige export van de Google Sheets-historiek naar intervals.icu.

Neemt alle bestaande rijen uit de tabbladen Gewicht en Maaltijden en schrijft
per dag één wellness-record: gewicht, kcal-inname, eiwit/koolhydraten/vet
(ingebouwde velden) en voedingsscore — alles in batches via wellness-bulk.
Respecteert de toggles en veldnamen uit config.json → intervals_upload.

Gebruik:
  python scripts/export_naar_intervals.py                           # 2026-06-01 t.e.m. vandaag
  python scripts/export_naar_intervals.py 2026-06-01 2026-06-30     # expliciete periode
  python scripts/export_naar_intervals.py --met-notities            # ook 🍽️-kalendernotities per dag

Vereiste env-variabelen: INTERVALS_API_KEY, APPS_SCRIPT_URL en APPS_SCRIPT_KEY.
Veilig om meermaals te draaien: wellness-records worden per datum overschreven
met dezelfde waarden en kalendernotities worden ge-upsert.
"""

import os
import sys
import json
import datetime

import requests
import pytz

from intervals import API_BASE, upload_kalendernotitie

BRUSSELS      = pytz.timezone("Europe/Brussels")
START_DEFAULT = "2026-06-01"   # start van het eten-tracken
BATCH_GROOTTE = 50


def load_upload_config() -> dict:
    try:
        with open("data/config/config.json", encoding="utf-8") as f:
            return json.load(f).get("intervals_upload", {})
    except Exception:
        return {}


def geldige_datum(s: str) -> str:
    try:
        return datetime.date.fromisoformat(s).isoformat()
    except ValueError:
        sys.exit(f"Ongeldige datum: {s!r} — gebruik YYYY-MM-DD")


def _num(val):
    """Getal of None — accepteert ook strings zoals '8/10' of '72,5'."""
    if val is None:
        return None
    s = str(val).strip().replace(",", ".")
    for einde in ("/",):
        if einde in s:
            s = s.split(einde)[0]
    try:
        n = float(s)
        return n if n > 0 else None
    except ValueError:
        return None


def fetch_sheet(url: str, key: str, data_type: str) -> list:
    try:
        resp = requests.get(
            url,
            params={"type": data_type, "limit": 1000, "key": key},
            timeout=30,
            allow_redirects=False,
        )
        if resp.status_code in (301, 302, 303, 307, 308):
            resp = requests.get(resp.headers.get("Location", ""), timeout=30)
        rows = resp.json()
        if isinstance(rows, dict) and rows.get("error") == "unauthorized":
            sys.exit("doGet weigerde de APPS_SCRIPT_KEY — check secret en Apps Script property.")
        return rows if isinstance(rows, list) else []
    except SystemExit:
        raise
    except Exception as e:
        sys.exit(f"Sheets-data ophalen mislukt ({data_type}): {e}")


def bouw_records(gewichten: list, maaltijden: list, start: str, eind: str, cfg: dict) -> list:
    """Eén wellness-record per datum met alles wat de config toelaat."""
    per_datum: dict = {}

    def record(datum):
        return per_datum.setdefault(datum, {"id": datum})

    if cfg.get("gewicht", True):
        locked = bool(cfg.get("gewicht_locked", False))
        for r in gewichten:
            if not isinstance(r, dict):
                continue
            datum = str(r.get("datum", ""))[:10]
            kg = _num(r.get("gewicht"))
            if not (start <= datum <= eind) or not kg:
                continue
            rec = record(datum)  # laatste rij per datum wint (zelfde volgorde als de sheet)
            rec["weight"] = round(kg, 2)
            if locked:
                rec["locked"] = True

    kcal_veld = cfg.get("kcal_veld", "kcalConsumed")
    mapping = cfg.get("custom_velden") or {}
    for r in maaltijden:
        if not isinstance(r, dict):
            continue
        datum = str(r.get("datum", ""))[:10]
        if not (start <= datum <= eind):
            continue
        bronnen = {
            "score":        _num(r.get("score")),
            "eiwitten":     _num(r.get("eiwitten")),
            "koolhydraten": _num(r.get("koolhydraten")),
            "vetten":       _num(r.get("vetten")),
        }
        kcal = _num(r.get("calories"))
        velden = {}
        if cfg.get("kcal", True) and kcal:
            velden[kcal_veld] = int(kcal)
        for veld, bron in mapping.items():
            if bronnen.get(bron) is not None:
                velden[veld] = bronnen[bron]
        if velden:
            record(datum).update(velden)

    return sorted(
        (rec for rec in per_datum.values() if len(rec) > 1),
        key=lambda rec: rec["id"],
    )


def push_bulk(records: list, auth) -> int:
    """PUT wellness-bulk in batches. Geeft het aantal mislukte batches terug."""
    fouten = 0
    for i in range(0, len(records), BATCH_GROOTTE):
        batch = records[i:i + BATCH_GROOTTE]
        try:
            resp = requests.put(
                f"{API_BASE}/athlete/0/wellness-bulk",
                json=batch, auth=auth, timeout=60,
            )
            if resp.ok:
                print(f"Wellness-bulk: {len(batch)} dag(en) verwerkt "
                      f"({batch[0]['id']} → {batch[-1]['id']})")
            else:
                fouten += 1
                print(f"Wellness-bulk MISLUKT (HTTP {resp.status_code}) vanaf {batch[0]['id']} — "
                      f"check veldnamen in config.intervals_upload")
        except Exception as e:
            fouten += 1
            print(f"Wellness-bulk MISLUKT vanaf {batch[0]['id']}: {e}")
    return fouten


def notitie_van_rij(r: dict) -> tuple:
    """(naam, beschrijving) voor de kalendernotitie van één maaltijdrij."""
    kcal  = int(_num(r.get("calories")) or 0)
    score = _num(r.get("score"))
    naam  = f"🍽️ Voeding: {kcal} kcal"
    if score:
        naam += f" · score {int(score)}/10"
    beschrijving = (
        f"Calorieën: {kcal} kcal\n"
        f"Eiwitten: {int(_num(r.get('eiwitten')) or 0)} g · "
        f"Koolhydraten: {int(_num(r.get('koolhydraten')) or 0)} g · "
        f"Vetten: {int(_num(r.get('vetten')) or 0)} g\n"
        f"{str(r.get('notities', '')).strip()}"
    ).strip()
    return naam, beschrijving


def main() -> None:
    api_key = os.environ.get("INTERVALS_API_KEY")
    if not api_key:
        sys.exit("INTERVALS_API_KEY ontbreekt.")
    url = os.environ.get("APPS_SCRIPT_URL")
    key = os.environ.get("APPS_SCRIPT_KEY", "")
    if not url:
        sys.exit("APPS_SCRIPT_URL ontbreekt.")

    args         = [a for a in sys.argv[1:] if a and not a.startswith("--")]
    met_notities = "--met-notities" in sys.argv

    vandaag = datetime.datetime.now(BRUSSELS).strftime("%Y-%m-%d")
    start   = geldige_datum(args[0]) if len(args) >= 1 else START_DEFAULT
    eind    = geldige_datum(args[1]) if len(args) >= 2 else vandaag
    if start > eind:
        sys.exit(f"Startdatum {start} ligt na einddatum {eind}.")

    cfg = load_upload_config()
    print(f"Export {start} t.e.m. {eind}"
          f"{' (incl. kalendernotities)' if met_notities else ''}")

    gewichten  = fetch_sheet(url, key, "gewicht")
    maaltijden = fetch_sheet(url, key, "maaltijden")
    print(f"Sheets: {len(gewichten)} wegingen, {len(maaltijden)} maaltijddagen opgehaald")

    records = bouw_records(gewichten, maaltijden, start, eind, cfg)
    if not records:
        sys.exit("Geen data in deze periode — niets te exporteren.")
    print(f"{len(records)} dag(en) met data om te exporteren")

    fouten = push_bulk(records, ("API_KEY", api_key))

    if met_notities:
        n = 0
        for r in maaltijden:
            if not isinstance(r, dict):
                continue
            datum = str(r.get("datum", ""))[:10]
            if not (start <= datum <= eind) or not _num(r.get("calories")):
                continue
            naam, beschrijving = notitie_van_rij(r)
            if upload_kalendernotitie(datum, naam, beschrijving):
                n += 1
            else:
                fouten += 1
        print(f"Kalendernotities: {n} dag(en) gezet/bijgewerkt")

    if fouten:
        sys.exit(f"Klaar met {fouten} fout(en) — run gerust opnieuw, alles wordt overschreven/ge-upsert.")
    print("✅ Export voltooid — check de wellness-pagina en /fitness in intervals.icu.")


if __name__ == "__main__":
    main()
