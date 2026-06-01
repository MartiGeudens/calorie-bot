import os
import re
import json
import datetime
import requests
import pytz
from groq import Groq

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = int(os.environ["CHAT_ID"])
GROQ_API_KEY    = os.environ["GROQ_API_KEY"]
APPS_SCRIPT_URL = os.environ["APPS_SCRIPT_URL"]

BRUSSELS     = pytz.timezone("Europe/Brussels")
BASE_URL     = f"https://api.telegram.org/bot{BOT_TOKEN}"
RECIPES_FILE = "recepten.json"

groq_client = Groq(api_key=GROQ_API_KEY)


# ── Telegram ──────────────────────────────────────────────────────────────────
def send_message(text: str) -> None:
    requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown",
    }, timeout=10)


def get_updates() -> list:
    resp = requests.get(f"{BASE_URL}/getUpdates?limit=50&timeout=0", timeout=15)
    return resp.json().get("result", [])


def clear_updates(updates: list) -> None:
    if not updates:
        return
    last_id = max(u["update_id"] for u in updates)
    requests.get(f"{BASE_URL}/getUpdates?offset={last_id + 1}&timeout=0", timeout=15)


# ── Recepten ──────────────────────────────────────────────────────────────────
def load_recipes() -> dict:
    try:
        with open(RECIPES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}



def get_recipe_context(food_text: str, recipes: dict) -> str:
    food_lower = food_text.lower()
    found = [
        (naam, d) for naam, d in recipes.items()
        if naam in food_lower or naam.replace("_", " ") in food_lower
    ]
    if not found:
        print("Receptherkenning: geen overeenkomsten gevonden.")
        return ""
    print(f"Recepten herkend: {', '.join(naam for naam, _ in found)}")
    lines = ["\n\nGebruik deze EXACTE voedingswaarden (niet zelf schatten):"]
    for naam, d in found:
        lines.append(
            f"- {naam} (per {d.get('portie', 'portie')}): "
            f"{d['calories']} kcal, {d['eiwitten']}g eiwit, "
            f"{d['koolhydraten']}g koolh, {d['vetten']}g vet, {d['vezels']}g vezels"
        )
    return "\n".join(lines)



# ── Voedingsanalyse ───────────────────────────────────────────────────────────
def analyze_food(food_text: str) -> dict:
    recipes = load_recipes()
    recipe_context = get_recipe_context(food_text, recipes)

    prompt = f"""Je bent een voedingsdeskundige. Analyseer de onderstaande maaltijdbeschrijving.
Gebruik typische Belgische portiegroottes. Wees realistisch, niet optimistisch.{recipe_context}

Maaltijden: {food_text}

Antwoord UITSLUITEND met geldige JSON, geen uitleg of markdown:
{{"calories": 0, "eiwitten": 0, "koolhydraten": 0, "vetten": 0, "vezels": 0, "score": 0, "notitie": ""}}

- calories: totale kcal (geheel getal)
- eiwitten / koolhydraten / vetten / vezels: gram (gehele getallen)
- score: 1–10 voor hoe gezond en gevarieerd de dag was
- notitie: één zin met een observatie of tip"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    raw = response.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ── Opslaan in Google Sheets ──────────────────────────────────────────────────
def save_to_sheets(payload: dict) -> bool:
    resp = requests.post(APPS_SCRIPT_URL, json=payload, timeout=15, allow_redirects=False)
    if resp.status_code in (301, 302, 303, 307, 308):
        resp = requests.get(resp.headers.get("Location", ""), timeout=15)
    return resp.ok


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    today   = datetime.datetime.now(BRUSSELS).strftime("%Y-%m-%d")
    updates = get_updates()

    food_text = None

    for update in reversed(updates):
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue
        sender = msg.get("from", {})
        if sender.get("id") != CHAT_ID or sender.get("is_bot", False):
            continue
        text = msg.get("text", "").strip()
        if not text:
            continue

        # RECEPT-berichten worden apart verwerkt via de recept-workflow
        if re.match(r'^(/recept|recept)\b', text, re.IGNORECASE):
            continue

        if food_text is None:
            food_text = text

    clear_updates(updates)

    if not food_text:
        send_message("😔 Geen maaltijden gevonden voor vandaag. Vergeet morgen niet te loggen!")
        return

    send_message("⏳ Even analyseren…")

    try:
        data = analyze_food(food_text)
    except Exception as e:
        print(f"Analyse-fout: {e}")
        send_message("❌ Analyse mislukt. Probeer morgen opnieuw of beschrijf je maaltijden wat duidelijker.")
        return

    send_message(
        f"📊 *Voedingsoverzicht — {today}*\n\n"
        f"🔥 Calorieën: *{data['calories']} kcal*\n"
        f"💪 Eiwitten: {data['eiwitten']} g\n"
        f"🌾 Koolhydraten: {data['koolhydraten']} g\n"
        f"🥑 Vetten: {data['vetten']} g\n"
        f"🥦 Vezels: {data['vezels']} g\n\n"
        f"⭐ Score: {data['score']}/10\n"
        f"💬 _{data['notitie']}_"
    )

    if save_to_sheets({
        "datum": today, "maaltijden": food_text,
        "calories": data["calories"], "eiwitten": data["eiwitten"],
        "koolhydraten": data["koolhydraten"], "vetten": data["vetten"],
        "vezels": data["vezels"], "score": f"{data['score']}/10",
        "notities": data["notitie"],
    }):
        send_message("✅ Opgeslagen in je Google Spreadsheet!")
    else:
        send_message("⚠️ Analyse gelukt, maar opslaan in spreadsheet mislukte.")


if __name__ == "__main__":
    main()
