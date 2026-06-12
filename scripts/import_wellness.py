"""
Eenmalige import van historische wellness- (en optioneel sport-)data uit
intervals.icu naar Google Sheets — backfill vanaf de start van het eten-tracken.

Gebruik:
  python scripts/import_wellness.py                            # 2026-06-01 t.e.m. vandaag, incl. sport
  python scripts/import_wellness.py 2026-06-01 2026-06-30      # expliciete periode
  python scripts/import_wellness.py 2026-06-01 --zonder-sport  # alleen wellness

Vereiste env-variabelen: INTERVALS_API_KEY en APPS_SCRIPT_URL.
Veilig om meermaals te draaien: de Wellness-tab upsert op datum en de
Sport-tab dedupet op Intervals ID (beide in Apps Script).
"""

import os
import sys
import datetime

import requests
import pytz

from intervals import wellness_tussen, activiteiten_tussen

BRUSSELS     = pytz.timezone("Europe/Brussels")
START_DEFAULT = "2026-06-01"   # start van het eten-tracken
BATCH_GROOTTE = 50             # Apps Script-runs ruim onder de tijdslimiet houden


def post_naar_sheets(url: str, payload: dict) -> bool:
    resp = requests.post(url, json=payload, timeout=60, allow_redirects=False)
    if resp.status_code in (301, 302, 303, 307, 308):
        resp = requests.get(resp.headers.get("Location", ""), timeout=60)
    return resp.ok


def geldige_datum(s: str) -> str:
    try:
        return datetime.date.fromisoformat(s).isoformat()
    except ValueError:
        sys.exit(f"Ongeldige datum: {s!r} — gebruik YYYY-MM-DD")


def in_batches(items: list, grootte: int = BATCH_GROOTTE):
    for i in range(0, len(items), grootte):
        yield items[i:i + grootte]


def main() -> None:
    if not os.environ.get("INTERVALS_API_KEY"):
        sys.exit("INTERVALS_API_KEY ontbreekt — niets te importeren.")
    url = os.environ.get("APPS_SCRIPT_URL")
    if not url:
        sys.exit("APPS_SCRIPT_URL ontbreekt — kan niet naar Sheets schrijven.")

    args      = [a for a in sys.argv[1:] if a and not a.startswith("--")]
    ook_sport = "--zonder-sport" not in sys.argv

    vandaag = datetime.datetime.now(BRUSSELS).strftime("%Y-%m-%d")
    start   = geldige_datum(args[0]) if len(args) >= 1 else START_DEFAULT
    eind    = geldige_datum(args[1]) if len(args) >= 2 else vandaag
    if start > eind:
        sys.exit(f"Startdatum {start} ligt na einddatum {eind}.")

    print(f"Import {start} t.e.m. {eind} ({'wellness + sport' if ook_sport else 'alleen wellness'})")
    fouten = 0

    # ── wellness (upsert op datum) ────────────────────────────────────────────
    records = wellness_tussen(start, eind)
    records = [
        r for r in records
        if start <= r["datum"] <= eind
        and any(r.get(k) for k in ("hrv", "rhr", "slaap_u", "slaapscore", "readiness"))
    ]
    if not records:
        print("Wellness: geen records met metingen gevonden in deze periode.")
    for batch in in_batches(records):
        if post_naar_sheets(url, {"type": "wellness", "records": batch}):
            print(f"Wellness: {len(batch)} dag(en) verwerkt "
                  f"({batch[0]['datum']} → {batch[-1]['datum']})")
        else:
            fouten += 1
            print(f"Wellness: batch vanaf {batch[0]['datum']} MISLUKT")

    # ── sport (dedupe op Intervals ID) ────────────────────────────────────────
    if ook_sport:
        acts = [a for a in activiteiten_tussen(start, eind) if start <= a["datum"] <= eind]
        if not acts:
            print("Sport: geen activiteiten gevonden in deze periode.")
        for batch in in_batches(acts):
            if post_naar_sheets(url, {"type": "sport", "activiteiten": batch}):
                print(f"Sport: {len(batch)} activiteit(en) verwerkt "
                      f"({batch[0]['datum']} → {batch[-1]['datum']})")
            else:
                fouten += 1
                print(f"Sport: batch vanaf {batch[0]['datum']} MISLUKT")

    if fouten:
        sys.exit(f"Klaar met {fouten} mislukte batch(es) — run gerust opnieuw (upsert/dedupe vangt dubbels op).")
    print("✅ Import voltooid.")


if __name__ == "__main__":
    main()
