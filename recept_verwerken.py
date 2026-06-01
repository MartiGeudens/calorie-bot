import os
import re
import json
import subprocess
import requests
from groq import Groq

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN    = os.environ["BOT_TOKEN"]
CHAT_ID      = int(os.environ["CHAT_ID"])
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

BASE_URL     = f"https://api.telegram.org/bot{BOT_TOKEN}"
RECIPES_FILE = "recepten.json"

groq_client = Groq(api_key=GROQ_API_KEY)


def send_message(text):
    requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"
    }, timeout=10)


def get_updates():
    resp = requests.get(f"{BASE_URL}/getUpdates?limit=50&timeout=0", timeout=15)
    return resp.json().get("result", [])


def load_recipes():
    try:
        with open(RECIPES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def commit_recipes():
    subprocess.run(["git", "config", "user.email", "action@github.com"])
    subprocess.run(["git", "config", "user.name", "Calorie Bot"])
    subprocess.run(["git", "add", RECIPES_FILE])
    result = subprocess.run(["git", "diff", "--staged", "--quiet"])
    if result.returncode != 0:
        subprocess.run(["git", "commit", "-m", "Recepten bijgewerkt"])
        subprocess.run(["git", "push"])


def process_recipe_command(text):
    rest = re.sub(r'^recept\s*:?\s*', '', text, flags=re.IGNORECASE).strip()

    prompt = f"""Analyseer dit recept en geef de voedingswaarden PER PORTIE.

Recept: {rest}

Antwoord UITSLUITEND met geldige JSON:
{{"naam": "", "calories": 0, "eiwitten": 0, "koolhydraten": 0, "vetten": 0, "vezels": 0, "portie": ""}}

- naam: korte naam in lowercase, spaties als underscores (bv "pasta_bolognese")
- portie: beschrijving van 1 portie (bv "1 bord ~450g")
- calories/eiwitten/koolhydraten/vetten/vezels: per portie, gehele getallen"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    raw = response.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)
    naam = data.pop("naam", rest[:40].lower().replace(" ", "_"))
    return naam, data


def main():
    updates = get_updates()

    # Zoek RECEPT-berichten — laat de wachtrij intact voor de maaltijden-workflow
    recipe_commands = [
        msg.get("text", "").strip()
        for update in updates
        if (msg := update.get("message") or update.get("edited_message"))
        and msg.get("from", {}).get("id") == CHAT_ID
        and not msg.get("from", {}).get("is_bot", False)
        and re.match(r'^recept\b', msg.get("text", ""), re.IGNORECASE)
    ]

    if not recipe_commands:
        send_message(
            "ℹ️ Geen recepten gevonden in je berichten.\n\n"
            "Stuur eerst een bericht naar de bot in dit formaat:\n"
            "`RECEPT naam: ingrediënten`\n\n"
            "Bv: `RECEPT pasta bolognese: 200g spaghetti, 150g gehakt, tomatensaus`"
        )
        return

    recipes = load_recipes()
    for cmd in recipe_commands:
        try:
            naam, data = process_recipe_command(cmd)
            recipes[naam] = data
            send_message(
                f"✅ *Recept opgeslagen: {naam}*\n"
                f"_{data.get('portie', '1 portie')}: {data['calories']} kcal, "
                f"{data['eiwitten']}g eiwit, {data['koolhydraten']}g koolh_"
            )
        except Exception as e:
            print(f"Recept-fout: {e}")
            send_message("❌ Kon recept niet verwerken. Probeer: `RECEPT naam: ingrediënten`")

    try:
        with open(RECIPES_FILE, "w", encoding="utf-8") as f:
            json.dump(recipes, f, ensure_ascii=False, indent=2)
        commit_recipes()
    except Exception as e:
        print(f"Opslaan mislukt: {e}")


if __name__ == "__main__":
    main()
