import os
import re
import json
import datetime
import requests
import pytz

from intervals import (activiteiten_van, sport_kcal_totaal, sport_regel, dagdoel,
                       geplande_workouts)

BOT_TOKEN    = os.environ["BOT_TOKEN"]
CHAT_ID      = int(os.environ["CHAT_ID"])
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

BRUSSELS = pytz.timezone("Europe/Brussels")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

GENERIEKE_HERINNERING = (
    "*Calorie Tracker* — Goedenavond Marti!\n\n"
    "Wat heb je vandaag gegeten?\n\n"
    "Je kan maaltijden doorheen de dag insturen of alles nu in één keer beschrijven. "
    "Alles wat je vandaag gestuurd hebt wordt meegenomen! \n\n"
    "_Ontbijt: havermout met banaan_\n"
    "_Lunch: broodje kaas en tomaat_\n"
    "_Avondeten: pasta bolognese_\n"
    "_Snack: appel en handvol noten_\n\n"
    "Ik analyseer alles automatisch om middernacht! "
)

def load_doelen() -> dict:
    with open("data/config/config.json", encoding="utf-8") as f:
        return json.load(f)["doelen"]

def send_message(text: str) -> bool:
    resp = requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown",
    }, timeout=10)
    return resp.ok

def get_updates_readonly() -> list:
    """Leest updates ZONDER offset te bevestigen — de verwerking om 23:58 blijft onaangetast."""
    resp = requests.get(f"{BASE_URL}/getUpdates?limit=100&timeout=0", timeout=15)
    return resp.json().get("result", [])

def is_weight_message(text: str) -> bool:
    if len(text) > 30:
        return False
    match = re.fullmatch(r'\s*(\d+[.,]\d+|\d+)\s*(kg|kilo)?\s*', text, re.IGNORECASE)
    if match:
        try:
            val = float(match.group(1).replace(',', '.'))
            return 30 <= val <= 200
        except ValueError:
            pass
    return False

def collect_today_food(updates: list) -> list:
    start_of_day = datetime.datetime.now(BRUSSELS).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    food_messages = []
    for update in updates:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue
        sender = msg.get("from", {})
        if sender.get("id") != CHAT_ID or sender.get("is_bot", False):
            continue
        text = msg.get("text", "").strip()
        if not text:
            continue
        if msg.get("date", 0) < start_of_day:
            continue
        if text.startswith('/'):
            continue
        if re.match(r'^recept\b', text, re.IGNORECASE):
            continue
        if is_weight_message(text):
            continue
        food_messages.append(text)
    return food_messages

PERIODE_LABELS = {
    "ontbijt":       "ontbijt",
    "lunch":         "lunch",
    "middageten":    "lunch",
    "middagmaal":    "lunch",
    "avondeten":     "avondeten",
    "avondmaal":     "avondeten",
    "diner":         "avondeten",
    "snack":         "snacks",
    "snacks":        "snacks",
    "tussendoortje": "snacks",
}

def detect_periods(food_messages: list) -> dict:
    """Detecteert welke maaltijdmomenten al gelabeld gelogd zijn (bv. 'lunch: ...')."""
    periods = {"ontbijt": False, "lunch": False, "avondeten": False, "snacks": False}
    for msg in food_messages:
        for line in msg.splitlines():
            m = re.match(r'\s*([a-zA-Z]+)\s*:', line)
            if m:
                label = PERIODE_LABELS.get(m.group(1).lower())
                if label:
                    periods[label] = True
    return periods

def estimate_kcal(food_text: str):
    """Snelle Groq-schatting van de tot nu toe gegeten calorieën. None bij falen."""
    if not GROQ_API_KEY:
        return None
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY)
    prompt = (
        "Je bent een voedingsdeskundige. Schat het totale aantal calorieën van deze maaltijden, "
        "op basis van typische Belgische portiegroottes. Wees realistisch.\n\n"
        f"Maaltijden:\n{food_text}\n\n"
        'Antwoord UITSLUITEND met geldige JSON, geen uitleg: {"kcal_gegeten": 0}'
    )
    for _ in range(2):
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=60,
            )
            raw = response.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
            kcal = int(json.loads(raw).get("kcal_gegeten", 0))
            if kcal > 0:
                return kcal
        except Exception as e:
            print(f"Kcal-schatting mislukt: {e}")
    return None

def fetch_sport_today():
    """(activiteiten, kcal) van vandaag — faalt stil via intervals.py."""
    today = datetime.datetime.now(BRUSSELS).strftime("%Y-%m-%d")
    acts = activiteiten_van(today)
    return acts, sport_kcal_totaal(acts)

def load_tss_zwaar() -> float:
    try:
        with open("data/config/config.json", encoding="utf-8") as f:
            return float(json.load(f).get("wellness", {}).get("tss_zware_dag", 100))
    except Exception:
        return 100.0

def morgen_training_regel() -> str:
    """Carb-advies als er morgen een zware workout in de intervals.icu-kalender staat.
    Lege string zonder kalendergebruik — dan blijft de herinnering zoals ze was."""
    morgen = (datetime.datetime.now(BRUSSELS) + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    workouts = geplande_workouts(morgen)
    tss_zwaar = load_tss_zwaar()
    zwaar = [w for w in workouts if w["load"] >= tss_zwaar or w["duur_min"] >= 90]
    if not zwaar:
        return ""
    w = max(zwaar, key=lambda x: (x["load"], x["duur_min"]))
    delen = []
    if w["duur_min"]:
        delen.append(f"~{w['duur_min']} min")
    if w["load"]:
        delen.append(f"load {w['load']}")
    detail = f" ({', '.join(delen)})" if delen else ""
    return (
        f"\n\n📅 Morgen gepland: *{w['naam']}*{detail} — "
        f"extra koolhydraten vanavond is slim!"
    )

def build_smart_message(food_messages: list, sport_acts: list, sport_kcal: int) -> str:
    doelen    = load_doelen()
    doel_kcal = doelen["kcal"]
    dag_doel  = dagdoel(doel_kcal, float(doelen.get("sport_compensatie", 1.0)), sport_kcal)
    periods   = detect_periods(food_messages)
    kcal      = estimate_kcal("\n".join(food_messages))

    n = len(food_messages)
    lines = [
        "*Calorie Tracker* — Goedenavond Marti!",
        "",
        f"Je hebt vandaag al *{n} bericht{'en' if n != 1 else ''}* gelogd ✅",
    ]

    if any(periods.values()):
        emoji_map = [("ontbijt", "🌅"), ("lunch", "☀️"), ("avondeten", "🌙"), ("snacks", "🍎")]
        status = " · ".join(f"{e} {'✅' if periods[k] else '➖'}" for k, e in emoji_map)
        lines.append(status)

    if sport_kcal > 0:
        lines.append(
            f"\n🚴 Gesport: *{sport_kcal} kcal* verbrand ({sport_regel(sport_acts)}) "
            f"— je doel vandaag is daardoor *{dag_doel} kcal*."
        )

    if kcal is not None:
        rest = dag_doel - kcal
        if rest > 0:
            lines.append(f"\nTot nu toe ~*{kcal} kcal* — nog ~{rest} kcal ruimte tot je doel van {dag_doel}.")
        else:
            lines.append(f"\nTot nu toe ~*{kcal} kcal* — je zit ~{abs(rest)} kcal boven je doel van {dag_doel}.")

    lines.append("\nNog iets gegeten dat er niet bij staat? Stuur het nog door — om middernacht analyseer ik alles!")
    return "\n".join(lines) + morgen_training_regel()

def main() -> None:
    # De herinnering mag NOOIT stilletjes uitvallen: bij elke fout in het
    # slimme pad valt het script terug op de generieke herinnering.
    try:
        updates       = get_updates_readonly()
        food_messages = collect_today_food(updates)
        sport_acts, sport_kcal = fetch_sport_today()
        if food_messages:
            message = build_smart_message(food_messages, sport_acts, sport_kcal)
        else:
            message = GENERIEKE_HERINNERING
            if sport_kcal > 0:
                message += (
                    f"\n\n🚴 Al wel gezien: *{sport_kcal} kcal* gesport vandaag "
                    f"({sport_regel(sport_acts)}) — eet voldoende terug!"
                )
            message += morgen_training_regel()
    except Exception as e:
        print(f"Slimme herinnering mislukt, val terug op generieke tekst: {e}")
        message = GENERIEKE_HERINNERING

    if send_message(message):
        print("Herinnering verstuurd!")
    else:
        # Markdown-parsefout of iets anders: probeer de veilige generieke tekst
        if message != GENERIEKE_HERINNERING and send_message(GENERIEKE_HERINNERING):
            print("Slimme herinnering faalde, generieke verstuurd.")
        else:
            print("Fout: herinnering kon niet verstuurd worden")
            exit(1)

if __name__ == "__main__":
    main()
