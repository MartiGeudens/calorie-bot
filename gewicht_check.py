import os
import re
import datetime
import requests
import pytz

BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = int(os.environ["CHAT_ID"])
APPS_SCRIPT_URL = os.environ["APPS_SCRIPT_URL"]

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
    """Zoekt een getal tussen 30 en 200 in de tekst (gewicht in kg)."""
    text = text.strip()
    if len(text) > 50:
        return None
    match = re.search(r'\b(\d+[.,]\d+|\d+)\s*(?:kg|kilo)?\b', text, re.IGNORECASE)
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
            params={"type": data_type, "limit": 60},
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

    gewicht = None

    for update in reversed(updates):
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue
        sender = msg.get("from", {})
        if sender.get("id") != CHAT_ID or sender.get("is_bot", False):
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
        tekst = streak_tekst(streak)
        if tekst:
            msg += f"\n{tekst}"
        send_message(msg)
    else:
        send_message(f"⚖️ Gewicht ontvangen ({gewicht} kg) maar opslaan mislukte.")


if __name__ == "__main__":
    main()
