import os
import re
import json
import datetime
import requests
import pytz

from intervals import wellness_tussen, herstel_alert, upload_gewicht

BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = int(os.environ["CHAT_ID"])
APPS_SCRIPT_URL = os.environ["APPS_SCRIPT_URL"]
APPS_SCRIPT_KEY = os.environ.get("APPS_SCRIPT_KEY", "")

BRUSSELS = pytz.timezone("Europe/Brussels")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def today_str():
    return datetime.datetime.now(BRUSSELS).strftime("%Y-%m-%d")

def send_message(text):
    requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"
    }, timeout=10)

def get_updates():
    resp = requests.get(f"{BASE_URL}/getUpdates?limit=50&timeout=0", timeout=15)
    return resp.json().get("result", [])

def extract_weight(text):
    """Zoekt een getal tussen 30 en 200 in de tekst (gewicht in kg).
    Het bericht moet uitsluitend een getal zijn (optioneel gevolgd door kg/kilo),
    zodat voedselberichten zoals '200 gram rijsttaart' niet worden herkend als gewicht."""
    text = text.strip()
    match = re.fullmatch(r'(\d+[.,]\d+|\d+)\s*(?:kg|kilo)?', text, re.IGNORECASE)
    if match:
        try:
            weight = float(match.group(1).replace(',', '.'))
            if 30 <= weight <= 200:
                return weight
        except ValueError:
            pass
    return None

def calculate_streak(data_type: str) -> int:
    """Berekent de huidige aaneengesloten streak van gelogde dagen."""
    try:
        resp = requests.get(
            APPS_SCRIPT_URL,
            params={"type": data_type, "limit": 60, "key": APPS_SCRIPT_KEY},
            timeout=15,
            allow_redirects=False,
        )
        if resp.status_code in (301, 302, 303, 307, 308):
            resp = requests.get(resp.headers.get("Location", ""), timeout=15)
        rows = resp.json()
        if not isinstance(rows, list):
            return 0
    except Exception:
        return 0
    logged_dates = {r.get("datum", "") for r in rows if isinstance(r, dict)}
    streak = 0
    check_date = datetime.datetime.now(BRUSSELS).date()
    while check_date.strftime("%Y-%m-%d") in logged_dates:
        streak += 1
        check_date -= datetime.timedelta(days=1)
    return streak

def streak_tekst(streak: int) -> str:
    if streak < 2:
        return ""
    if streak >= 30:
        emoji = "🔥🔥🔥"
    elif streak >= 14:
        emoji = "🔥🔥"
    elif streak >= 7:
        emoji = "🔥"
    else:
        emoji = "⚡"
    return f"{emoji} *{streak} dagen op rij gewicht gelogd!*"

def save_weight(datum, gewicht):
    payload = {"type": "gewicht", "datum": datum, "gewicht": gewicht}
    resp = requests.post(APPS_SCRIPT_URL, json=payload, timeout=15, allow_redirects=False)
    if resp.status_code in (301, 302, 303, 307, 308):
        resp = requests.get(resp.headers.get("Location", ""), timeout=15)
    return resp.ok

def main():
    today = today_str()

    updates = get_updates()
    print(f"Aantal updates: {len(updates)}")

    start_of_day = datetime.datetime.now(BRUSSELS).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()

    gewicht = None

    for update in reversed(updates):
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue
        sender = msg.get("from", {})
        if sender.get("id") != CHAT_ID or sender.get("is_bot", False):
            continue
        if msg.get("date", 0) < start_of_day:
            continue

        weight = extract_weight(msg.get("text", ""))
        if weight is not None:
            gewicht = weight
            break

    if gewicht is None:
        send_message(
            "⚖️ Nog geen gewicht gevonden voor vandaag.\n"
            "Stuur je gewicht als je het weet, bv: `72.5`"
        )
        return

    if save_weight(today, gewicht):
        streak = calculate_streak("gewicht")
        msg = f"⚖️ Gewicht opgeslagen: *{gewicht} kg* ✅"
        # Fase 3: ook naar intervals.icu (W/kg en eFTP kloppen daar dan altijd)
        try:
            ucfg = load_upload_config()
            if ucfg.get("gewicht", True) and upload_gewicht(
                today, gewicht, bool(ucfg.get("gewicht_locked", False))
            ):
                msg += "\n📤 Ook bijgewerkt in intervals.icu"
        except Exception as e:
            print(f"intervals-upload genegeerd: {e}")
        tekst = streak_tekst(streak)
        if tekst:
            msg += f"\n{tekst}"
        send_message(msg)
    else:
        send_message(f"⚖️ Gewicht ontvangen ({gewicht} kg) maar opslaan mislukte.")

def load_wellness_config() -> dict:
    try:
        with open("data/config/config.json", encoding="utf-8") as f:
            return json.load(f).get("wellness", {})
    except Exception:
        return {}

def load_upload_config() -> dict:
    try:
        with open("data/config/config.json", encoding="utf-8") as f:
            return json.load(f).get("intervals_upload", {})
    except Exception:
        return {}

def check_herstel_alert(today: str) -> None:
    """Overtraining/ziekte-signaal (15:00-run): HRV meerdere dagen onder de
    7d-baseline én verhoogde rusthartslag → proactief bericht.
    Vuurt alleen op de eerste dag dat de conditie waar wordt en faalt stil —
    de gewichtscheck mag hier nooit door breken."""
    try:
        cfg   = load_wellness_config()
        dagen = int(cfg.get("hrv_alert_dagen", 3))
        delta = float(cfg.get("rhr_alert_boven_baseline", 3))

        start = (datetime.date.fromisoformat(today)
                 - datetime.timedelta(days=dagen + 13)).isoformat()
        records = wellness_tussen(start, today)
        if not records:
            return

        alert = herstel_alert(records, today, dagen, delta)
        if not alert:
            return

        gisteren = (datetime.date.fromisoformat(today) - datetime.timedelta(days=1)).isoformat()
        if herstel_alert(records, gisteren, dagen, delta):
            print("Herstel-alert: conditie gold gisteren ook al — geen herhaalbericht")
            return

        send_message(
            f"🟠 *Herstel hapert*\n\n"
            f"Je HRV zit al *{alert['dagen']} dagen* onder je baseline "
            f"({alert['hrv_nu']} vs. {alert['hrv_baseline']}) en je rusthartslag is verhoogd "
            f"({alert['rhr_nu']} vs. {alert['rhr_baseline']}).\n\n"
            f"Mogelijk broeit er iets (vermoeidheid of ziekte): overweeg een rustdag, "
            f"focus op slaap en eet voldoende eiwit. 💤"
        )
        print("Herstel-alert verstuurd")
    except Exception as e:
        print(f"Herstel-alert check mislukt (genegeerd): {e}")

if __name__ == "__main__":
    main()
    check_herstel_alert(today_str())
