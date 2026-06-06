import os
import re
import json
import datetime
import requests
import pytz
from groq import Groq

BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = int(os.environ["CHAT_ID"])
GROQ_API_KEY    = os.environ["GROQ_API_KEY"]
APPS_SCRIPT_URL = os.environ["APPS_SCRIPT_URL"]

BRUSSELS          = pytz.timezone("Europe/Brussels")
BASE_URL          = f"https://api.telegram.org/bot{BOT_TOKEN}"
RECIPES_FILE      = "data/config/recepten.json"
LAST_UPDATE_FILE  = "data/state/last_food_update.txt"

def load_config() -> dict:
    with open("data/config/config.json", encoding="utf-8") as f:
        return json.load(f)["doelen"]

_cfg       = load_config()
DOEL_KCAL  = _cfg["kcal"]
DOEL_EIWIT = _cfg["eiwitten"]
DOEL_KOOLH = _cfg["koolhydraten"]
DOEL_VET   = _cfg["vetten"]
DOEL_VEZEL = _cfg["vezels"]

groq_client = Groq(api_key=GROQ_API_KEY)

def send_message(text: str) -> None:
    requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown",
    }, timeout=10)

def get_last_update_id() -> int:
    try:
        with open(LAST_UPDATE_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return 0

def save_last_update_id(update_id: int) -> None:
    with open(LAST_UPDATE_FILE, "w") as f:
        f.write(str(update_id))

def get_updates() -> list:
    """Haalt alle updates op sinds de laatste verwerkte update_id."""
    last_id = get_last_update_id()
    all_updates = []
    offset = last_id + 1 if last_id > 0 else None

    while True:
        url = f"{BASE_URL}/getUpdates?limit=100&timeout=0"
        if offset:
            url += f"&offset={offset}"
        resp = requests.get(url, timeout=15)
        batch = resp.json().get("result", [])
        if not batch:
            break
        all_updates.extend(batch)
        if len(batch) < 100:
            break
        offset = batch[-1]["update_id"] + 1

    return all_updates

def clear_updates(updates: list) -> None:
    if not updates:
        return
    last_id = max(u["update_id"] for u in updates)
    requests.get(f"{BASE_URL}/getUpdates?offset={last_id + 1}&timeout=0", timeout=15)
    save_last_update_id(last_id)

def load_recipes() -> dict:
    try:
        with open(RECIPES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def normalize(text: str) -> str:
    """Normaliseert tekst voor receptherkenning: lowercase, koppeltekens en underscores → spaties."""
    return re.sub(r'[-_]', ' ', text.lower())

def get_recipe_context(food_text: str, recipes: dict) -> str:
    food_norm = normalize(food_text)
    found = [
        (naam, d) for naam, d in recipes.items()
        if normalize(naam) in food_norm
    ]
    if not found:
        print("Receptherkenning: geen overeenkomsten gevonden.")
        return ""
    print(f"Recepten herkend: {', '.join(naam for naam, _ in found)}")
    lines = [
        "\n\nVoor de onderstaande herkende recepten gebruik je EXACT deze voedingswaarden.",
        "Schat alle overige maaltijden zelf in op basis van typische Belgische portiegroottes:"
    ]
    for naam, d in found:
        lines.append(
            f"- {naam} (per {d.get('portie', 'portie')}): "
            f"{d['calories']} kcal, {d['eiwitten']}g eiwit, "
            f"{d['koolhydraten']}g koolh, {d['vetten']}g vet, {d['vezels']}g vezels"
        )
    return "\n".join(lines)

def is_weight_message(text: str) -> bool:
    """Kort bericht dat alleen een getal (30–200) bevat = gewichtsmeting, geen maaltijdlog."""
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

def collect_food_messages(updates: list) -> list:
    """Verzamelt alle maaltijdberichten van de afgelopen 24 uur, in chronologische volgorde."""
    cutoff_ts = datetime.datetime.now(BRUSSELS).timestamp() - 86400
    food_messages = []

    for update in updates:  # chronologische volgorde bewaren
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue
        sender = msg.get("from", {})
        if sender.get("id") != CHAT_ID or sender.get("is_bot", False):
            continue
        text = msg.get("text", "").strip()
        if not text:
            continue
        if msg.get("date", 0) < cutoff_ts:
            continue
        if text.startswith('/'):
            continue
        if re.match(r'^recept\b', text, re.IGNORECASE):
            continue
        if is_weight_message(text):
            continue
        food_messages.append(text)

    return food_messages

def analyze_food(food_text: str) -> dict:
    recipes = load_recipes()
    recipe_context = get_recipe_context(food_text, recipes)

    prompt = f"""Je bent een voedingsdeskundige. Analyseer de onderstaande maaltijdbeschrijving.
Gebruik typische Belgische portiegroottes. Wees realistisch, niet optimistisch.

Dagelijkse doelen van deze persoon:
- Calorieën: {DOEL_KCAL} kcal
- Eiwitten: {DOEL_EIWIT}g
- Koolhydraten: {DOEL_KOOLH}g
- Vetten: {DOEL_VET}g
- Vezels: {DOEL_VEZEL}g

Gebruik deze doelen als referentie voor de score (1–10) en de notitie. Een score van 10 = doelen perfect behaald.{recipe_context}

Maaltijden van vandaag (meerdere berichten, chronologisch):
{food_text}

Regels:
1. Categoriseer elke maaltijd in ontbijt, lunch, avondeten of snacks op basis van het label in de tekst (bv. "ontbijt:", "lunch:", "snack:", "avondeten:"). Zonder label: schat op basis van voedseltype.
2. Elke maaltijd hoort bij exact één periode. Verdeel de calorieën correct: ontbijt.kcal + lunch.kcal + avondeten.kcal + snacks.kcal moet gelijk zijn aan het totale calories-getal.
3. Als een periode niet gegeten werd: 0 kcal en lege omschrijving.

Antwoord UITSLUITEND met geldige JSON, geen uitleg of markdown:
{{"ontbijt": {{"kcal": 0, "omschrijving": ""}}, "lunch": {{"kcal": 0, "omschrijving": ""}}, "avondeten": {{"kcal": 0, "omschrijving": ""}}, "snacks": {{"kcal": 0, "omschrijving": ""}}, "calories": 0, "eiwitten": 0, "koolhydraten": 0, "vetten": 0, "vezels": 0, "score": 0, "notitie": ""}}

- ontbijt/lunch/avondeten/snacks.kcal: calorieën voor die periode (geheel getal, 0 indien niet gegeten)
- ontbijt/lunch/avondeten/snacks.omschrijving: korte beschrijving (leeg indien niet gegeten)
- calories: totale kcal voor de dag (geheel getal)
- eiwitten / koolhydraten / vetten / vezels: gram (gehele getallen)
- score: 1–10 voor hoe gezond en gevarieerd de dag was
- notitie: één zin met een observatie of tip"""

    for attempt in range(3):
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        if data.get("calories", 0) > 0:
            return data
        print(f"Analyse poging {attempt + 1}: AI gaf 0 kcal terug, opnieuw proberen...")
    return data  # geef laatste resultaat terug na 3 mislukte pogingen

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
    return f"{emoji} *{streak} dagen op rij maaltijden gelogd!*"

def stuur_score_alert(food_text: str, score: int) -> None:
    """Stuurt een extra gerichte tip als de dagelijkse score onder 5 valt."""
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": (
                f"Maaltijden van vandaag (score {score}/10):\n{food_text}\n\n"
                "Geef één concrete, budgetvriendelijke tip om de voedingskwaliteit morgen te verbeteren. "
                "Max 2 zinnen, Nederlands, direct en praktisch. Geen aanhef."
            )}],
            temperature=0.5,
            max_tokens=120,
        )
        tip = resp.choices[0].message.content.strip()
        send_message(f"💡 *Tip voor morgen:*\n_{tip}_")
    except Exception as e:
        print(f"Score alert mislukt: {e}")

def save_to_sheets(payload: dict) -> bool:
    resp = requests.post(APPS_SCRIPT_URL, json=payload, timeout=15, allow_redirects=False)
    if resp.status_code in (301, 302, 303, 307, 308):
        resp = requests.get(resp.headers.get("Location", ""), timeout=15)
    return resp.ok

def main() -> None:
    today   = datetime.datetime.now(BRUSSELS).strftime("%Y-%m-%d")
    updates = get_updates()

    food_messages = collect_food_messages(updates)
    clear_updates(updates)

    if not food_messages:
        send_message("😔 Geen maaltijden gevonden voor vandaag. Vergeet morgen niet te loggen!")
        return

    food_text = "\n".join(food_messages)
    print(f"Maaltijdberichten gevonden: {len(food_messages)}\n{food_text}")

    send_message("⏳ Even analyseren…")

    try:
        data = analyze_food(food_text)
    except Exception as e:
        print(f"Analyse-fout: {e}")
        send_message("❌ Analyse mislukt. Probeer morgen opnieuw of beschrijf je maaltijden wat duidelijker.")
        return

    meal_lines = ""
    for key, label, emoji in [
        ("ontbijt",   "Ontbijt",   "🌅"),
        ("lunch",     "Lunch",     "☀️"),
        ("avondeten", "Avondeten", "🌙"),
        ("snacks",    "Snacks",    "🍎"),
    ]:
        meal = data.get(key, {})
        kcal = meal.get("kcal", 0)
        omschr = meal.get("omschrijving", "")
        if kcal and kcal > 0:
            line = f"{emoji} {label}: {kcal} kcal"
            if omschr:
                line += f" — _{omschr}_"
            meal_lines += line + "\n"

    send_message(
        f"📊 *Voedingsoverzicht — {today}*\n\n"
        f"{meal_lines}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔥 Totaal: *{data['calories']} kcal*\n"
        f"💪 Eiwitten: {data['eiwitten']} g\n"
        f"🌾 Koolhydraten: {data['koolhydraten']} g\n"
        f"🥑 Vetten: {data['vetten']} g\n"
        f"🥦 Vezels: {data['vezels']} g\n\n"
        f"⭐ Score: {data['score']}/10\n"
        f"💬 _{data['notitie']}_"
    )

    ontbijt = data.get("ontbijt", {})
    lunch   = data.get("lunch", {})
    avond   = data.get("avondeten", {})
    snacks  = data.get("snacks", {})

    if data['score'] < 5:
        stuur_score_alert(food_text, data['score'])

    streak = calculate_streak("maaltijden")

    if save_to_sheets({
        "datum":          today,
        "maaltijden":     food_text,
        "calories":       data["calories"],
        "eiwitten":       data["eiwitten"],
        "koolhydraten":   data["koolhydraten"],
        "vetten":         data["vetten"],
        "vezels":         data["vezels"],
        "score":          data["score"],
        "notities":       data["notitie"],
        "ontbijt_kcal":   ontbijt.get("kcal", 0),
        "lunch_kcal":     lunch.get("kcal", 0),
        "avondeten_kcal": avond.get("kcal", 0),
        "snacks_kcal":    snacks.get("kcal", 0),
    }):
        msg = "✅ Opgeslagen in je Google Spreadsheet!"
        tekst = streak_tekst(streak)
        if tekst:
            msg += f"\n{tekst}"
        send_message(msg)
    else:
        send_message("⚠️ Analyse gelukt, maar opslaan in spreadsheet mislukte.")

if __name__ == "__main__":
    main()
