import os
import re
import json
import datetime
import subprocess
import requests
import pytz
from groq import Groq

BOT_TOKEN    = os.environ["BOT_TOKEN"]
CHAT_ID      = int(os.environ["CHAT_ID"])
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

BRUSSELS              = pytz.timezone("Europe/Brussels")
BASE_URL              = f"https://api.telegram.org/bot{BOT_TOKEN}"
RECIPES_FILE          = "data/config/recepten.json"
LAST_TIPS_UPDATE_FILE = "data/state/last_tips_update.txt"

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

def get_updates_readonly() -> list:
    resp = requests.get(f"{BASE_URL}/getUpdates?limit=100&timeout=0", timeout=15)
    return resp.json().get("result", [])

def get_last_tips_id() -> int:
    try:
        with open(LAST_TIPS_UPDATE_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return 0

def save_last_tips_id(uid: int) -> None:
    with open(LAST_TIPS_UPDATE_FILE, "w") as f:
        f.write(str(uid))

def commit_tips_file() -> None:
    subprocess.run(["git", "config", "user.email", "action@github.com"])
    subprocess.run(["git", "config", "user.name", "Calorie Bot"])
    subprocess.run(["git", "add", LAST_TIPS_UPDATE_FILE])
    r = subprocess.run(["git", "diff", "--staged", "--quiet"])
    if r.returncode != 0:
        subprocess.run(["git", "commit", "-m", "Tips update bijgewerkt"])
        subprocess.run(["git", "push"])

def load_recipes() -> dict:
    try:
        with open(RECIPES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def get_recipe_context(food_text: str, recipes: dict) -> str:
    food_norm = re.sub(r'[-_]', ' ', food_text.lower())
    found = [
        (naam, d) for naam, d in recipes.items()
        if re.sub(r'[-_]', ' ', naam.lower()) in food_norm
    ]
    if not found:
        return ""
    lines = ["\n\nVoor de onderstaande herkende recepten gebruik je EXACT deze voedingswaarden:"]
    for naam, d in found:
        lines.append(
            f"- {naam} (per {d.get('portie', 'portie')}): "
            f"{d['calories']} kcal, {d['eiwitten']}g eiwit, "
            f"{d['koolhydraten']}g koolh, {d['vetten']}g vet"
        )
    return "\n".join(lines)

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
    now = datetime.datetime.now(BRUSSELS)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
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

def analyze_partial_day(food_text: str) -> dict:
    recipes = load_recipes()
    recipe_context = get_recipe_context(food_text, recipes)
    now = datetime.datetime.now(BRUSSELS)

    prompt = f"""Je bent een voedingsdeskundige. Analyseer de maaltijden van vandaag tot nu toe en geef concrete tips voor de rest van de dag.
Gebruik typische Belgische portiegroottes.
Huidig tijdstip: {now.strftime('%H:%M')}.

Dagelijkse doelen van deze persoon:
- Calorieën: {DOEL_KCAL} kcal
- Eiwitten: {DOEL_EIWIT}g
- Koolhydraten: {DOEL_KOOLH}g
- Vetten: {DOEL_VET}g
- Vezels: {DOEL_VEZEL}g
{recipe_context}

Maaltijden tot nu toe:
{food_text}

Antwoord UITSLUITEND met geldige JSON, geen uitleg of markdown:
{{"kcal_gegeten": 0, "eiwitten": 0, "koolhydraten": 0, "vetten": 0, "vezels": 0, "maaltijden_samenvatting": "", "aanbevelingen": []}}

- kcal_gegeten: totale calorieën gegeten tot nu toe (geheel getal)
- eiwitten / koolhydraten / vetten / vezels: gram gegeten tot nu toe (gehele getallen)
- maaltijden_samenvatting: één zin die samenvat wat al gegeten is
- aanbevelingen: lijst van 2-3 concrete, realistische maaltijd- of snack-suggesties voor de rest van de dag, rekening houdend met het resterend budget én de macro's die nog ontbreken (prioriteit: eiwit). Geef specifieke gerechten met geschatte kcal en eiwitten tussen haakjes. Elk item is een string."""

    for attempt in range(3):
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )
        raw = response.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        if data.get("kcal_gegeten", 0) > 0:
            return data
        print(f"Tips analyse poging {attempt + 1}: 0 kcal, opnieuw proberen...")
    return data

def main() -> None:
    last_tips_id = get_last_tips_id()
    updates = get_updates_readonly()

    tips_updates = [
        u for u in updates
        if u["update_id"] > last_tips_id
        and (msg := u.get("message") or u.get("edited_message"))
        and msg.get("from", {}).get("id") == CHAT_ID
        and not msg.get("from", {}).get("is_bot", False)
        and msg.get("text", "").strip().lower().startswith("/tips")
    ]

    if not tips_updates:
        print(f"Geen /tips commando's (laatste verwerkt: update_id {last_tips_id}).")
        return

    max_tips_id = max(u["update_id"] for u in tips_updates)
    food_messages = collect_today_food(updates)

    if not food_messages:
        send_message(
            "📊 *Calorie Tips*\n\n"
            "Je hebt nog niets gelogd voor vandaag\\.\n\n"
            "Stuur je maaltijden als gewone berichten en gebruik daarna /tips om je caloriëbudget te bekijken\\."
        )
        save_last_tips_id(max_tips_id)
        commit_tips_file()
        return

    send_message("⏳ Even berekenen…")

    food_text = "\n".join(food_messages)
    print(f"Maaltijdberichten voor tips ({len(food_messages)}):\n{food_text}")

    try:
        data = analyze_partial_day(food_text)
    except Exception as e:
        print(f"Tips analyse mislukt: {e}")
        send_message("❌ Kon tips niet berekenen. Probeer opnieuw.")
        save_last_tips_id(max_tips_id)
        commit_tips_file()
        return

    kcal      = data.get("kcal_gegeten", 0)
    eiwitten  = data.get("eiwitten", 0)
    koolh     = data.get("koolhydraten", 0)
    vetten    = data.get("vetten", 0)
    vezels    = data.get("vezels", 0)
    samen     = data.get("maaltijden_samenvatting", "")
    tips_list = data.get("aanbevelingen", [])

    rest_kcal  = DOEL_KCAL  - kcal
    rest_eiwit = DOEL_EIWIT - eiwitten
    rest_koolh = DOEL_KOOLH - koolh
    rest_vet   = DOEL_VET   - vetten
    rest_vezel = DOEL_VEZEL - vezels
    now = datetime.datetime.now(BRUSSELS)

    def macro_lijn(label, gegeten, doel, eenheid="g"):
        pct  = round(gegeten / doel * 100) if doel else 0
        rest = doel - gegeten
        teken = "✅" if rest >= 0 else "⚠️"
        return f"{teken} {label}: {gegeten}/{doel}{eenheid} ({pct}%)"

    if rest_kcal > 0:
        budget_lijn = f"✅ Nog *{rest_kcal} kcal* over van je {DOEL_KCAL} kcal doel"
    else:
        budget_lijn = f"⚠️ Je zit *{abs(rest_kcal)} kcal boven* je {DOEL_KCAL} kcal doel"
