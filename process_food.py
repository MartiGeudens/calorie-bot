import os
import json
import datetime
import requests
import pytz
import google.generativeai as genai

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = int(os.environ["CHAT_ID"])
GEMINI_API_KEY  = os.environ["GEMINI_API_KEY"]
APPS_SCRIPT_URL = os.environ["APPS_SCRIPT_URL"]

BRUSSELS = pytz.timezone("Europe/Brussels")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")


# ── Hulpfuncties ──────────────────────────────────────────────────────────────
def send_message(text: str) -> None:
    requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }, timeout=10)


def get_updates() -> list:
    resp = requests.get(f"{BASE_URL}/getUpdates?limit=50&timeout=0", timeout=15)
    return resp.json().get("result", [])


def clear_updates(updates: list) -> None:
    """Markeer alle updates als verwerkt zodat ze morgen niet opnieuw opduiken."""
    if not updates:
        return
    last_id = max(u["update_id"] for u in updates)
    requests.get(f"{BASE_URL}/getUpdates?offset={last_id + 1}&timeout=0", timeout=15)


def analyze_food(food_text: str) -> dict:
    prompt = f"""Je bent een voedingsdeskundige. Analyseer de onderstaande maaltijdbeschrijving.
Gebruik typische Belgische portiegroottes. Wees realistisch, niet optimistisch.

Maaltijden: {food_text}

Antwoord UITSLUITEND met geldige JSON, geen uitleg of markdown:
{{"calories": 0, "eiwitten": 0, "koolhydraten": 0, "vetten": 0, "vezels": 0, "score": 0, "notitie": ""}}

- calories: totale kcal (geheel getal)
- eiwitten / koolhydraten / vetten / vezels: gram (gehele getallen)
- score: 1–10 voor hoe gezond en gevarieerd de dag was
- notitie: één zin met een observatie of tip"""

    response = model.generate_content(prompt)
    raw = response.text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ── Hoofdlogica ───────────────────────────────────────────────────────────────
def main() -> None:
    today = datetime.datetime.now(BRUSSELS).strftime("%Y-%m-%d")
    updates = get_updates()

    # Zoek het meest recente bericht van de gebruiker (niet van de bot)
    food_text = None
    for update in reversed(updates):
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue
        sender = msg.get("from", {})
        if sender.get("id") == CHAT_ID and not sender.get("is_bot", False):
            text = msg.get("text", "").strip()
            if text:
                food_text = text
                break

    # Altijd de wachtrij leegmaken
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

    # Resultaat naar Telegram
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

    # Opslaan in Google Spreadsheet
    resp = requests.post(
        APPS_SCRIPT_URL,
        json={
            "datum":         today,
            "maaltijden":    food_text,
            "calories":      data["calories"],
            "eiwitten":      data["eiwitten"],
            "koolhydraten":  data["koolhydraten"],
            "vetten":        data["vetten"],
            "vezels":        data["vezels"],
            "score":         f"{data['score']}/10",
            "notities":      data["notitie"],
        },
        timeout=15,
        allow_redirects=True,
    )

    if resp.ok:
        send_message("✅ Opgeslagen in je Google Spreadsheet!")
    else:
        print(f"Spreadsheet-fout: {resp.status_code} — {resp.text}")
        send_message("⚠️ Analyse gelukt, maar opslaan in spreadsheet mislukte.")


if __name__ == "__main__":
    main()
