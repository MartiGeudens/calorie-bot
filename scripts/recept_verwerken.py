import os
import re
import json
import subprocess
import requests
from groq import Groq

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
RECIPES_FILE = "data/config/recepten.json"
LAST_UPDATE_FILE = "data/state/last_recept_update.txt"

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

def get_last_update_id():
 try:
 with open(LAST_UPDATE_FILE) as f:
 return int(f.read().strip())
 except Exception:
 return 0

def commit_files():
 subprocess.run(["git", "config", "user.email", "action@github.com"])
 subprocess.run(["git", "config", "user.name", "Calorie Bot"])
 subprocess.run(["git", "add", RECIPES_FILE, LAST_UPDATE_FILE])
 r = subprocess.run(["git", "diff", "--staged", "--quiet"])
 if r.returncode != 0:
 subprocess.run(["git", "commit", "-m", "Recepten bijgewerkt"])
 subprocess.run(["git", "push"])

def parse_recipe_message(text):
 """
 Ondersteunde formaten:
 /recept_ai naam: ingrediënten → AI berekent macro's
 /recept naam: ingrediënten | macro's → jij geeft macro's op

 Geeft terug: (mode, naam_hint, ingredienten_str, manual_macros_str of None)
 """
 if re.match(r'^/recept_ai\b', text, re.IGNORECASE):
 mode = 'ai'
 rest = re.sub(r'^/recept_ai\s*:?\s*', '', text, flags=re.IGNORECASE).strip()
 else:
 mode = 'manual'
 rest = re.sub(r'^(/recept|recept)\s*:?\s*', '', text, flags=re.IGNORECASE).strip()

 parts = rest.split('|', 1)
 ingredienten_deel = parts[0].strip()
 manual_macros_str = parts[1].strip() if len(parts) > 1 else None

 if ':' in ingredienten_deel:
 naam_hint, ingr_str = ingredienten_deel.split(':', 1)
 naam_hint = naam_hint.strip()
 ingr_str = ingr_str.strip()
 else:
 naam_hint = ""
 ingr_str = ingredienten_deel

 return mode, naam_hint, ingr_str, manual_macros_str

def parse_manual_macros(text):
 """Parseert '450 kcal, 25g eiwit, 55g koolh, 12g vet, 6g vezel'"""
 patterns = {
 'calories': r'(\d+)\s*(?:kcal|cal)',
 'eiwitten': r'(\d+)\s*g?\s*(?:eiwit|prot)',
 'koolhydraten': r'(\d+)\s*g?\s*(?:koolh|carb)',
 'vetten': r'(\d+)\s*g?\s*(?:vet|fat)',
 'vezels': r'(\d+)\s*g?\s*(?:vezel|fib)',
 }
 data = {}
 for key, pattern in patterns.items():
 m = re.search(pattern, text, re.IGNORECASE)
 if m:
 data[key] = int(m.group(1))
 return data

def process_recipe_command(text):
 mode, naam_hint, ingr_str, manual_macros_str = parse_recipe_message(text)

 if mode == 'manual' and manual_macros_str:
 manual = parse_manual_macros(manual_macros_str)

 prompt = f"""Structureer dit recept. Geef GEEN voedingswaarden — die worden manueel opgegeven.

Naam: {naam_hint}
Ingrediënten: {ingr_str}

Antwoord UITSLUITEND met geldige JSON:
{{"naam": "", "portie": "", "ingredienten": []}}

- naam: lowercase met underscores (bv "pasta_bolognese")
- portie: geschatte portiegrootte voor 1 persoon (bv "1 bord ~450g")
- ingredienten: gestructureerde lijst, elk item met hoeveelheid (bv ["200g spaghetti", "150g rundergehakt"])"""

 response = groq_client.chat.completions.create(
 model="llama-3.3-70b-versatile",
 messages=[{"role": "user", "content": prompt}],
 temperature=0.1,
 )
 raw = response.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
 struct = json.loads(raw)

 naam = struct.get("naam") or naam_hint.lower().replace(" ", "_")
 data = {
 "portie": struct.get("portie", "1 portie"),
 "ingredienten": struct.get("ingredienten", [i.strip() for i in ingr_str.split(',')]),
 "calories": manual.get("calories", 0),
 "eiwitten": manual.get("eiwitten", 0),
 "koolhydraten": manual.get("koolhydraten", 0),
 "vetten": manual.get("vetten", 0),
 "vezels": manual.get("vezels", 0),
 "macros_bron": "manueel",
 }
 return naam, data

 elif mode == 'manual' and not manual_macros_str:
 send_message(
 "*Macro's ontbreken bij /recept*\n\n"
 "Voeg ze toe na een `|`, bv:\n"
 "`/recept pasta bolognese: 200g spaghetti | 520 kcal, 28g eiwit, 65g koolh, 15g vet`\n\n"
 "Of gebruik `/recept_ai` om macro's automatisch te laten berekenen."
 )
 return None, None

 else:
 prompt = f"""Analyseer dit recept. Structureer de ingrediënten EN bereken voedingswaarden PER PORTIE.
Gebruik Belgische portiegroottes. Wees realistisch.

Naam: {naam_hint}
Ingrediënten: {ingr_str}

Antwoord UITSLUITEND met geldige JSON:
{{"naam": "", "portie": "", "ingredienten": [], "calories": 0, "eiwitten": 0, "koolhydraten": 0, "vetten": 0, "vezels": 0}}

- naam: lowercase met underscores (bv "pasta_bolognese")
- portie: geschatte portiegrootte voor 1 persoon (bv "1 bord ~450g")
- ingredienten: lijst met exacte hoeveelheden (bv ["200g spaghetti", "150g rundergehakt"])
- calories/eiwitten/koolhydraten/vetten/vezels: per portie, gehele getallen"""

 response = groq_client.chat.completions.create(
 model="llama-3.3-70b-versatile",
 messages=[{"role": "user", "content": prompt}],
 temperature=0.2,
 )
 raw = response.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
 data = json.loads(raw)
 naam = data.pop("naam") or naam_hint.lower().replace(" ", "_")
 data["macros_bron"] = "ai"
 return naam, data

def main():
 last_id = get_last_update_id()
 updates = get_updates()

 new_updates = [u for u in updates if u["update_id"] > last_id]

 recipe_entries = [
 (u["update_id"], msg.get("text", "").strip())
 for u in new_updates
 if (msg := u.get("message") or u.get("edited_message"))
 and msg.get("from", {}).get("id") == CHAT_ID
 and not msg.get("from", {}).get("is_bot", False)
 and re.match(r'^(/recept_ai|/recept|recept)\b', msg.get("text", ""), re.IGNORECASE)
 ]

 if not recipe_entries:
 print(f"Geen nieuwe recept-commando's (laatste verwerkt: update_id {last_id}).")
 return

 max_update_id = max(uid for uid, _ in recipe_entries)

 recipes = load_recipes()
 for _, cmd in recipe_entries:
 try:
 naam, data = process_recipe_command(cmd)
 if naam is None:
 continue
 recipes[naam] = data

 bron_label = "AI" if data.get("macros_bron") == "ai" else "Manueel"
 ingr_count = len(data.get("ingredienten", []))

 send_message(
 f"*Recept opgeslagen: {naam.replace('_', ' ')}*\n"
 f"_{data.get('portie', '1 portie')} · {ingr_count} ingrediënten_\n\n"
 f"{data['calories']} kcal · {data['eiwitten']}g eiwit · "
 f"{data['koolhydraten']}g koolh · {data['vetten']}g vet\n"
 f"_Macro's: {bron_label}_"
 )
 except Exception as e:
 print(f"Recept-fout: {e}")
 send_message(
 "Kon recept niet verwerken.\n\n"
 "*Formaat met AI-macro's:*\n"
 "`/recept naam: ingrediënten`\n\n"
 "*Formaat met eigen macro's:*\n"
 "`/recept naam: ingrediënten | 450 kcal, 25g eiwit, 55g koolh, 12g vet`"
 )

 try:
 with open(RECIPES_FILE, "w", encoding="utf-8") as f:
 json.dump(recipes, f, ensure_ascii=False, indent=2)
 with open(LAST_UPDATE_FILE, "w") as f:
 f.write(str(max_update_id))
 commit_files()
 except Exception as e:
 print(f"Opslaan mislukt: {e}")

if __name__ == "__main__":
 main()
