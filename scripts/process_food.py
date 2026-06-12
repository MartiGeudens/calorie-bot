import os
import re
import json
import datetime
import requests
import pytz
from groq import Groq

from intervals import (activiteiten_tussen, sport_kcal_totaal, sport_regel, dagdoel,
                       sport_load_totaal, wellness_tussen, wellness_regel,
                       upload_gewicht, upload_voeding, upload_kalendernotitie,
                       verrijk_activiteit)

BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = int(os.environ["CHAT_ID"])
GROQ_API_KEY    = os.environ["GROQ_API_KEY"]
APPS_SCRIPT_URL = os.environ["APPS_SCRIPT_URL"]
APPS_SCRIPT_KEY = os.environ.get("APPS_SCRIPT_KEY", "")

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

def load_upload_config() -> dict:
    try:
        with open("data/config/config.json", encoding="utf-8") as f:
            return json.load(f).get("intervals_upload", {})
    except Exception:
        return {}
RICHTING_TEKST = {
    "aankomen":    "aankomen — een calorie-surplus en voldoende eiwit zijn gewenst; te weinig eten is hier het probleem, niet te veel",
    "afvallen":    "afvallen — een calorie-tekort is gewenst",
    "onderhouden": "gewicht onderhouden — rond het caloriedoel eten is gewenst",
}.get(_cfg.get("richting", "onderhouden"), _cfg.get("richting", "onderhouden"))

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

def extract_weight(text: str):
    """Geeft het gewicht (30–200 kg) terug als het bericht uitsluitend een getal is, anders None."""
    if len(text) > 30:
        return None
    match = re.fullmatch(r'\s*(\d+[.,]\d+|\d+)\s*(kg|kilo)?\s*', text, re.IGNORECASE)
    if match:
        try:
            val = float(match.group(1).replace(',', '.'))
            if 30 <= val <= 200:
                return val
        except ValueError:
            pass
    return None

def is_weight_message(text: str) -> bool:
    """Kort bericht dat alleen een getal (30–200) bevat = gewichtsmeting, geen maaltijdlog."""
    return extract_weight(text) is not None

def find_today_weight(updates: list):
    """Zoekt het laatste gewichtsbericht van vandaag — vangnet voor metingen
    die na de 15:00-check gestuurd zijn (die zouden anders verloren gaan
    omdat clear_updates() ze om 23:58 definitief bevestigt)."""
    start_of_day = datetime.datetime.now(BRUSSELS).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    gewicht = None
    for update in updates:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue
        sender = msg.get("from", {})
        if sender.get("id") != CHAT_ID or sender.get("is_bot", False):
            continue
        if msg.get("date", 0) < start_of_day:
            continue
        w = extract_weight(msg.get("text", "").strip())
        if w is not None:
            gewicht = w  # laatste meting van de dag wint
    return gewicht

def weight_already_saved_today(today: str) -> bool:
    """Checkt of de 15:00-run het gewicht van vandaag al heeft opgeslagen (voorkomt dubbele rijen)."""
    try:
        resp = requests.get(
            APPS_SCRIPT_URL,
            params={"type": "gewicht", "limit": 3, "key": APPS_SCRIPT_KEY},
            timeout=15,
            allow_redirects=False,
        )
        if resp.status_code in (301, 302, 303, 307, 308):
            resp = requests.get(resp.headers.get("Location", ""), timeout=15)
        rows = resp.json()
        if not isinstance(rows, list):
            return False
        return any(str(r.get("datum", ""))[:10] == today for r in rows if isinstance(r, dict))
    except Exception:
        return False  # bij twijfel opslaan: een dubbele rij is beter dan een verloren meting

def save_weight(datum: str, gewicht: float) -> bool:
    payload = {"type": "gewicht", "datum": datum, "gewicht": gewicht}
    resp = requests.post(APPS_SCRIPT_URL, json=payload, timeout=15, allow_redirects=False)
    if resp.status_code in (301, 302, 303, 307, 308):
        resp = requests.get(resp.headers.get("Location", ""), timeout=15)
    return resp.ok

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

def analyze_food(food_text: str, sport_kcal: int = 0, sport_omschrijving: str = "",
                 herstel: str = "", dag_tss: int = 0, eiwit_doel: int = None) -> dict:
    eiwit_doel = eiwit_doel or DOEL_EIWIT
    recipes = load_recipes()
    recipe_context = get_recipe_context(food_text, recipes)

    sport_context = ""
    if sport_kcal > 0:
        dag_doel = dagdoel(DOEL_KCAL, SPORT_COMPENSATIE, sport_kcal)
        sport_context = (
            f"\n\nSport vandaag (exact gemeten via Garmin): {sport_omschrijving} — {sport_kcal} kcal verbrand. "
            f"Het caloriedoel van vandaag is daarom {dag_doel} kcal "
            f"({DOEL_KCAL} + {dag_doel - DOEL_KCAL} sportcompensatie). "
            f"Gebruik {dag_doel} kcal als calorie-referentie voor de score en de notitie."
        )
        if dag_tss >= TSS_ZWAAR:
            sport_context += (
                f" Het was een zware trainingsdag (trainingsload {dag_tss}); "
                f"het eiwitdoel van vandaag is daarom {eiwit_doel}g in plaats van {DOEL_EIWIT}g."
            )

    herstel_context = ""
    if herstel:
        herstel_context = (
            f"\n\nHerstelstatus vannacht (Garmin-meting): {herstel}. "
            f"Weeg dit mee in je notitie: bij slechte slaap of lage HRV zijn vroeger eten, "
            f"minder alcohol en voldoende koolhydraten en eiwit extra belangrijk."
        )

    prompt = f"""Je bent een voedingsdeskundige. Analyseer de onderstaande maaltijdbeschrijving.
Gebruik typische Belgische portiegroottes. Wees realistisch, niet optimistisch.

Dagelijkse doelen van deze persoon:
- Calorieën: {DOEL_KCAL} kcal
- Eiwitten: {eiwit_doel}g
- Koolhydraten: {DOEL_KOOLH}g
- Vetten: {DOEL_VET}g
- Vezels: {DOEL_VEZEL}g
- Richting: {RICHTING_TEKST}

Gebruik deze doelen én de richting als referentie voor de score (1–10) en de notitie. Een score van 10 = doelen perfect behaald.{sport_context}{herstel_context}{recipe_context}

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
    return f"{emoji} *{streak} dagen op rij maaltijden gelogd!*"

def stuur_score_alert(food_text: str, score: int, sport_context: str = "") -> None:
    """Stuurt een extra gerichte tip als de dagelijkse score onder 5 valt."""
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": (
                f"Maaltijden van vandaag (score {score}/10):\n{food_text}\n\n"
                f"Doel-richting: {RICHTING_TEKST}.{sport_context}\n"
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

def fetch_sport_today(today: str):
    """Haalt activiteiten van vandaag + gisteren op (gisteren = vangnet voor late syncs)
    en logt ze allemaal in de Sport-tab (dedupe op Intervals ID gebeurt in Apps Script).
    Geeft (activiteiten_vandaag, sport_kcal_vandaag) terug. Faalt stil."""
    gisteren = (
        datetime.datetime.strptime(today, "%Y-%m-%d") - datetime.timedelta(days=1)
    ).strftime("%Y-%m-%d")

    alle_acts = activiteiten_tussen(gisteren, today)
    if alle_acts:
        try:
            if save_to_sheets({"type": "sport", "activiteiten": alle_acts}):
                print(f"Sport: {len(alle_acts)} activiteit(en) naar de Sport-tab gestuurd")
            else:
                print("Sport: opslaan in Sport-tab mislukt")
        except Exception as e:
            print(f"Sport: opslaan in Sport-tab mislukt: {e}")

    vandaag_acts = [a for a in alle_acts if a["datum"] == today]
    return vandaag_acts, sport_kcal_totaal(vandaag_acts)

def fetch_wellness_today(today: str):
    """Haalt wellness van de laatste 2 dagen op, bewaart die in de Wellness-tab
    (upsert in Apps Script) en geeft het record van vandaag terug. Faalt stil."""
    gisteren = (
        datetime.datetime.strptime(today, "%Y-%m-%d") - datetime.timedelta(days=1)
    ).strftime("%Y-%m-%d")

    records = wellness_tussen(gisteren, today)
    recent = [r for r in records if r["datum"] in (gisteren, today)
              and any(r.get(k) for k in ("hrv", "rhr", "slaap_u", "slaapscore", "readiness"))]
    if recent:
        try:
            if save_to_sheets({"type": "wellness", "records": recent}):
                print(f"Wellness: {len(recent)} dag(en) naar de Wellness-tab gestuurd")
            else:
                print("Wellness: opslaan in Wellness-tab mislukt")
        except Exception as e:
            print(f"Wellness: opslaan mislukt: {e}")

    return next((r for r in records if r["datum"] == today), None)

def push_naar_intervals(today: str, data: dict, sport_acts: list) -> None:
    """Fase 3: voedingsdata terugschrijven naar intervals.icu — kcal-inname,
    voedingsscore en eiwit in het wellness-record, het dagoverzicht als
    kalendernotitie en een fueling-regel bij elke activiteit van vandaag.
    Faalt stil: de Telegram-flow is dan al volledig afgerond."""
    cfg = load_upload_config()
    try:
        velden = {}
        if cfg.get("kcal", True):
            velden[cfg.get("kcal_veld", "kcalConsumed")] = int(data["calories"])
        bronnen = {
            "score":        data.get("score"),
            "eiwitten":     data.get("eiwitten"),
            "koolhydraten": data.get("koolhydraten"),
            "vetten":       data.get("vetten"),
        }
        for veld, bron in (cfg.get("custom_velden") or {}).items():
            if bronnen.get(bron) is not None:
                velden[veld] = bronnen[bron]
        if velden and upload_voeding(today, velden):
            print(f"intervals.icu: voeding geüpload ({', '.join(velden)})")

        if cfg.get("kalendernotitie", True):
            naam = f"🍽️ Voeding: {data['calories']} kcal · score {data['score']}/10"
            beschrijving = (
                f"Calorieën: {data['calories']} kcal\n"
                f"Eiwitten: {data['eiwitten']} g · Koolhydraten: {data['koolhydraten']} g · "
                f"Vetten: {data['vetten']} g · Vezels: {data['vezels']} g\n"
                f"Score: {data['score']}/10\n"
                f"{data.get('notitie', '')}"
            ).strip()
            if upload_kalendernotitie(today, naam, beschrijving):
                print("intervals.icu: kalendernotitie bijgewerkt")

        if cfg.get("activiteit_beschrijving", True) and sport_acts:
            regel = (
                f"Gevoed: {data['calories']} kcal · {data['eiwitten']}g eiwit "
                f"(score {data['score']}/10)"
            )
            for act in sport_acts:
                if verrijk_activiteit(act, regel):
                    print(f"intervals.icu: activiteit {act.get('id')} verrijkt")
    except Exception as e:
        print(f"intervals.icu push genegeerd: {e}")

def main() -> None:
    today   = datetime.datetime.now(BRUSSELS).strftime("%Y-%m-%d")
    updates = get_updates()

    food_messages = collect_food_messages(updates)
    late_weight   = find_today_weight(updates)
    clear_updates(updates)

    # Sport en wellness altijd ophalen en loggen, óók als er geen maaltijden zijn
    sport_acts, sport_kcal = fetch_sport_today(today)
    dag_doel = dagdoel(DOEL_KCAL, SPORT_COMPENSATIE, sport_kcal)
    sport_samenvatting = sport_regel(sport_acts)
    dag_tss = sport_load_totaal(sport_acts)
    eiwit_doel_vandaag = DOEL_EIWIT + EIWIT_EXTRA_G if dag_tss >= TSS_ZWAAR else DOEL_EIWIT

    w_vandaag = fetch_wellness_today(today)
    herstel = wellness_regel(w_vandaag)
    if herstel:
        print(f"Wellness vandaag: {herstel}")

    weight_note = ""
    if late_weight is not None and not weight_already_saved_today(today):
        if save_weight(today, late_weight):
            weight_note = f"⚖️ Gewicht alsnog opgeslagen: *{late_weight} kg*"
            print(f"Gewicht-vangnet: {late_weight} kg opgeslagen voor {today}")
            try:
                ucfg = load_upload_config()
                if ucfg.get("gewicht", True) and upload_gewicht(
                    today, late_weight, bool(ucfg.get("gewicht_locked", False))
                ):
                    print("intervals.icu: gewicht geüpload (vangnet)")
            except Exception as e:
                print(f"intervals-upload genegeerd: {e}")
        else:
            weight_note = f"⚠️ Gewicht gevonden ({late_weight} kg) maar opslaan mislukte."

    if not food_messages:
        msg = "😔 Geen maaltijden gevonden voor vandaag. Vergeet morgen niet te loggen!"
        if sport_kcal > 0:
            msg += (
                f"\n\n🚴 Wel gesport: *{sport_kcal} kcal* verbrand ({sport_samenvatting}) "
                f"— opgeslagen in de Sport-tab."
            )
        if weight_note:
            msg += f"\n\n{weight_note}"
        send_message(msg)
        return

    food_text = "\n".join(food_messages)
    print(f"Maaltijdberichten gevonden: {len(food_messages)}\n{food_text}")
    if sport_kcal > 0:
        print(f"Sport vandaag: {sport_kcal} kcal ({sport_samenvatting}) → dagdoel {dag_doel} kcal")

    send_message("⏳ Even analyseren…")

    try:
        data = analyze_food(food_text, sport_kcal, sport_samenvatting,
                            herstel, dag_tss, eiwit_doel_vandaag)
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

    sport_blok = ""
    if sport_kcal > 0:
        sport_blok = (
            f"🚴 Sport: *{sport_kcal} kcal* verbrand — _{sport_samenvatting}_\n"
            f"🎯 Dagdoel: {DOEL_KCAL} + {dag_doel - DOEL_KCAL} = *{dag_doel} kcal*\n"
        )
        if dag_tss >= TSS_ZWAAR:
            sport_blok += f"💪 Zware trainingsdag (load {dag_tss}) → eiwitdoel *{eiwit_doel_vandaag}g*\n"

    send_message(
        f"📊 *Voedingsoverzicht — {today}*\n\n"
        f"{meal_lines}"
        f"{sport_blok}\n"
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
        sport_alert_context = (
            f"\nVandaag {sport_kcal} kcal gesport — dagbudget was {dag_doel} kcal."
            if sport_kcal > 0 else ""
        )
        if herstel:
            sport_alert_context += f"\nHerstelstatus vannacht: {herstel}."
        stuur_score_alert(food_text, data['score'], sport_alert_context)

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
        "sport_kcal":     sport_kcal,
    }):
        msg = "✅ Opgeslagen in je Google Spreadsheet!"
        tekst = streak_tekst(streak)
        if tekst:
            msg += f"\n{tekst}"
        if weight_note:
            msg += f"\n{weight_note}"
        send_message(msg)
        push_naar_intervals(today, data, sport_acts)
    else:
        msg = "⚠️ Analyse gelukt, maar opslaan in spreadsheet mislukte."
        if weight_note:
            msg += f"\n{weight_note}"
        send_message(msg)

if __name__ == "__main__":
    main()
