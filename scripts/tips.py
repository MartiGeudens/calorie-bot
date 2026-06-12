import os
import re
import json
import datetime
import subprocess
import requests
import pytz
from groq import Groq

from intervals import (activiteiten_van, sport_kcal_totaal, sport_regel, dagdoel,
                       sport_load_totaal, wellness_van, wellness_regel)

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
SPORT_COMPENSATIE = float(_cfg.get("sport_compensatie", 1.0))

def load_wellness_config() -> dict:
    try:
        with open("data/config/config.json", encoding="utf-8") as f:
            return json.load(f).get("wellness", {})
    except Exception:
        return {}

_wcfg         = load_wellness_config()
TSS_ZWAAR     = float(_wcfg.get("tss_zware_dag", 100))
EIWIT_EXTRA_G = int(_wcfg.get("eiwit_extra_g", 20))
RICHTING_TEKST = {
    "aankomen":    "aankomen — een calorie-surplus en voldoende eiwit zijn gewenst; het resterende budget mag zeker opgegeten worden",
    "afvallen":    "afvallen — een calorie-tekort is gewenst",
    "onderhouden": "gewicht onderhouden — rond het caloriedoel eten is gewenst",
}.get(_cfg.get("richting", "onderhouden"), _cfg.get("richting", "onderhouden"))

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

def analyze_partial_day(food_text: str, sport_kcal: int = 0, sport_omschrijving: str = "",
                        herstel: str = "", dag_tss: int = 0, eiwit_doel: int = None) -> dict:
    eiwit_doel = eiwit_doel or DOEL_EIWIT
    recipes = load_recipes()
    recipe_context = get_recipe_context(food_text, recipes)
    now = datetime.datetime.now(BRUSSELS)

    sport_context = ""
    if sport_kcal > 0:
        dag_doel = dagdoel(DOEL_KCAL, SPORT_COMPENSATIE, sport_kcal)
        sport_context = (
            f"\nSport vandaag (exact gemeten via Garmin): {sport_omschrijving} — {sport_kcal} kcal verbrand. "
            f"Het caloriedoel van vandaag is daarom {dag_doel} kcal in plaats van {DOEL_KCAL} kcal; "
            f"gebruik {dag_doel} kcal als budget voor je aanbevelingen."
        )
        if dag_tss >= TSS_ZWAAR:
            sport_context += (
                f" Het is een zware trainingsdag (trainingsload {dag_tss}); "
                f"het eiwitdoel is daarom {eiwit_doel}g — geef eiwitrijke suggesties extra prioriteit."
            )

    herstel_context = ""
    if herstel:
        herstel_context = (
            f"\nHerstelstatus vannacht (Garmin): {herstel}. "
            f"Bij slechte slaap of lage HRV: adviseer vroeger eten, weinig/geen alcohol "
            f"en voldoende koolhydraten en eiwit."
        )

    prompt = f"""Je bent een voedingsdeskundige. Analyseer de maaltijden van vandaag tot nu toe en geef concrete tips voor de rest van de dag.
Gebruik typische Belgische portiegroottes.
Huidig tijdstip: {now.strftime('%H:%M')}.

Dagelijkse doelen van deze persoon:
- Calorieën: {DOEL_KCAL} kcal
- Eiwitten: {eiwit_doel}g
- Koolhydraten: {DOEL_KOOLH}g
- Vetten: {DOEL_VET}g
- Vezels: {DOEL_VEZEL}g
- Richting: {RICHTING_TEKST}
{sport_context}{herstel_context}{recipe_context}

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

    today      = datetime.datetime.now(BRUSSELS).strftime("%Y-%m-%d")
    sport_acts = activiteiten_van(today)
    sport_kcal = sport_kcal_totaal(sport_acts)
    dag_doel   = dagdoel(DOEL_KCAL, SPORT_COMPENSATIE, sport_kcal)
    dag_tss    = sport_load_totaal(sport_acts)
    eiwit_doel_vandaag = DOEL_EIWIT + EIWIT_EXTRA_G if dag_tss >= TSS_ZWAAR else DOEL_EIWIT
    herstel    = wellness_regel(wellness_van(today))

    if not food_messages:
        msg = (
            "📊 *Calorie Tips*\n\n"
            "Je hebt nog niets gelogd voor vandaag.\n\n"
            "Stuur je maaltijden als gewone berichten en gebruik daarna /tips om je caloriëbudget te bekijken."
        )
        if sport_kcal > 0:
            msg += (
                f"\n\n🚴 Al wel gesport: *{sport_kcal} kcal* verbrand ({sport_regel(sport_acts)}) "
                f"— je dagbudget is daardoor *{dag_doel} kcal*."
            )
        send_message(msg)
        save_last_tips_id(max_tips_id)
        commit_tips_file()
        return

    send_message("⏳ Even berekenen…")

    food_text = "\n".join(food_messages)
    print(f"Maaltijdberichten voor tips ({len(food_messages)}):\n{food_text}")
    if sport_kcal > 0:
        print(f"Sport vandaag: {sport_kcal} kcal → dagbudget {dag_doel} kcal")

    try:
        data = analyze_partial_day(food_text, sport_kcal, sport_regel(sport_acts),
                                   herstel, dag_tss, eiwit_doel_vandaag)
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

    rest_kcal  = dag_doel   - kcal
    rest_eiwit = eiwit_doel_vandaag - eiwitten
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
        budget_lijn = f"✅ Nog *{rest_kcal} kcal* over van je {dag_doel} kcal doel"
    else:
        budget_lijn = f"⚠️ Je zit *{abs(rest_kcal)} kcal boven* je {dag_doel} kcal doel"

    sport_lijn = ""
    if sport_kcal > 0:
        sport_lijn = (
            f"🚴 {sport_regel(sport_acts)} — *{sport_kcal} kcal* verbrand "
            f"(doel: {DOEL_KCAL} + {dag_doel - DOEL_KCAL})\n"
        )
        if dag_tss >= TSS_ZWAAR:
            sport_lijn += f"💪 Zware trainingsdag (load {dag_tss}) → eiwitdoel *{eiwit_doel_vandaag}g*\n"

    tips_tekst = "\n".join(f"• {t}" for t in tips_list) if tips_list else "Geen specifieke aanbevelingen."

    message = (
        f"*Calorie Tips — {now.strftime('%H:%M')}*\n\n"
        f"_{samen}_\n\n"
        f"{sport_lijn}"
        f"{budget_lijn}\n\n"
        f"*Macro's tot nu toe:*\n"
        f"{macro_lijn('Eiwitten', eiwitten, eiwit_doel_vandaag)}\n"
        f"{macro_lijn('Koolh.', koolh, DOEL_KOOLH)}\n"
        f"{macro_lijn('Vetten', vetten, DOEL_VET)}\n"
        f"{macro_lijn('Vezels', vezels, DOEL_VEZEL)}\n\n"
        f"*Suggesties voor de rest van de dag:*\n"
        f"{tips_tekst}"
    )

    send_message(message)
    save_last_tips_id(max_tips_id)
    commit_tips_file()


if __name__ == "__main__":
    main()
