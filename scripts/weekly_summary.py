import os
import re
import json
import datetime
import requests
import pytz
from groq import Groq

BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = os.environ["CHAT_ID"]
APPS_SCRIPT_URL = os.environ["APPS_SCRIPT_URL"]
GROQ_API_KEY    = os.environ["GROQ_API_KEY"]
APPS_SCRIPT_KEY = os.environ.get("APPS_SCRIPT_KEY", "")

BRUSSELS    = pytz.timezone("Europe/Brussels")
BASE_URL    = f"https://api.telegram.org/bot{BOT_TOKEN}"
groq_client = Groq(api_key=GROQ_API_KEY)

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
RICHTING_TEKST = {
    "aankomen":    "aankomen — een calorie-surplus en voldoende eiwit zijn gewenst; te weinig eten is hier het probleem, niet te veel",
    "afvallen":    "afvallen — een calorie-tekort is gewenst",
    "onderhouden": "gewicht onderhouden — rond het caloriedoel eten is gewenst",
}.get(_cfg.get("richting", "onderhouden"), _cfg.get("richting", "onderhouden"))

def send_message(text: str) -> None:
    requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown",
    }, timeout=10)

UNAUTHORIZED = False  # wordt True als doGet de key weigert

def fetch_data(data_type: str, limit: int) -> list:
    global UNAUTHORIZED
    url = APPS_SCRIPT_URL
    params = {"type": data_type, "limit": limit, "key": APPS_SCRIPT_KEY}
    print(f"[DEBUG] GET {url} params={params}")

    resp = requests.get(url, params=params, timeout=15, allow_redirects=False)
    print(f"[DEBUG] Status: {resp.status_code}")
    print(f"[DEBUG] Headers: {dict(resp.headers)}")
    print(f"[DEBUG] Body (500 tekens): {resp.text[:500]}")

    if resp.status_code in (301, 302, 303, 307, 308):
        redirect_url = resp.headers.get("Location", "")
        print(f"[DEBUG] Redirect naar: {redirect_url}")
        resp = requests.get(redirect_url, timeout=15)
        print(f"[DEBUG] Status na redirect: {resp.status_code}")
        print(f"[DEBUG] Body na redirect (500 tekens): {resp.text[:500]}")

    try:
        result = resp.json()
        print(f"[DEBUG] JSON geparsed, type={type(result).__name__}, lengte={len(result) if isinstance(result, list) else 'n.v.t.'}")
        if isinstance(result, dict) and result.get("error") == "unauthorized":
            UNAUTHORIZED = True
            print("[DEBUG] doGet weigerde de key (unauthorized)")
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"[DEBUG] JSON parse mislukt: {e}")
        return []

def safe_num(val, default: float = 0.0) -> float:
    try:
        return float(val) if val else default
    except (TypeError, ValueError):
        return default

def parse_score(val) -> float | None:
    if not val:
        return None
    m = re.match(r'(\d+(?:\.\d+)?)', str(val))
    return float(m.group(1)) if m else None

def week_avg(rows: list, key: str) -> int:
    vals = [safe_num(r.get(key)) for r in rows if safe_num(r.get(key)) > 0]
    return round(sum(vals) / len(vals)) if vals else 0

def score_avg(rows: list) -> float:
    vals = [parse_score(r.get("score")) for r in rows]
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else 0.0

def parse_date(s) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None

def weights_by_date(gewichten: list) -> dict:
    """{date: kg} voor alle geldige wegingen."""
    out = {}
    for r in gewichten:
        if not isinstance(r, dict):
            continue
        d = parse_date(r.get("datum", ""))
        w = safe_num(r.get("gewicht"))
        if d and w > 0:
            out[d] = w
    return out

def moving_avg(wbd: dict, end: datetime.date, window: int = 7):
    """7-daags voortschrijdend gemiddelde t.e.m. `end`. Minstens 3 wegingen nodig, anders None."""
    vals = [
        wbd[end - datetime.timedelta(days=i)]
        for i in range(window)
        if (end - datetime.timedelta(days=i)) in wbd
    ]
    return round(sum(vals) / len(vals), 2) if len(vals) >= 3 else None

def tdee_blok(maaltijden: list, wbd: dict, today: datetime.date) -> str:
    """Schat de werkelijke TDEE: gem. intake − (Δkg_gesmoothed × 7700 / dagen).
    Adaptief: pakt het vroegst beschikbare gesmoothde startpunt tussen 14 en 10
    dagen terug, zodat de schatting ook werkt als de gewichtshistoriek nog jong is."""
    ma_end = moving_avg(wbd, today)

    # vroegst mogelijke anker met een geldig 7d-gemiddelde (langste span eerst)
    span = ma_start = None
    for terug in range(14, 9, -1):
        m = moving_avg(wbd, today - datetime.timedelta(days=terug))
        if m is not None:
            span, ma_start = terug, m
            break

    if ma_end is None or span is None:
        # vertel concreet wanneer de eerste schatting mogelijk wordt
        if wbd:
            d, eerste_ma = min(wbd), None
            while d <= today:
                if moving_avg(wbd, d) is not None:
                    eerste_ma = d
                    break
                d += datetime.timedelta(days=1)
            if eerste_ma:
                vanaf = eerste_ma + datetime.timedelta(days=10)
                return (
                    f"\n🔬 *TDEE-schatting:* gewichtshistoriek nog te kort — "
                    f"eerste schatting mogelijk rond {vanaf.strftime('%d/%m')}\n"
                )
        return "\n🔬 *TDEE-schatting:* nog te weinig wegingen (min. 3 per week)\n"

    start_d = today - datetime.timedelta(days=span)
    kcals = []
    for r in maaltijden:
        if not isinstance(r, dict):
            continue
        d = parse_date(r.get("datum", ""))
        c = safe_num(r.get("calories"))
        if d and c > 0 and start_d < d <= today:
            kcals.append(c)

    min_logged = max(7, round(span * 0.7))
    if len(kcals) < min_logged:
        return (
            f"\n🔬 *TDEE-schatting:* te weinig gelogde dagen in de meetperiode "
            f"({len(kcals)}/{min_logged})\n"
        )

    avg_intake = sum(kcals) / len(kcals)
    delta_kg   = ma_end - ma_start
    tdee       = avg_intake - (delta_kg * 7700 / span)
    tdee_r     = round(tdee / 50) * 50

    if not 1500 <= tdee_r <= 4500:
        return "\n🔬 *TDEE-schatting:* onbetrouwbaar deze periode — check je logs en wegingen\n"

    proj = (DOEL_KCAL - tdee) * 7 / 7700  # kg/week bij doelintake
    sign = "+" if proj > 0 else ""
    return (
        f"\n🔬 *Geschatte TDEE:* ~{tdee_r} kcal/dag (o.b.v. {span} dagen)\n"
        f"  Aan je doel van {DOEL_KCAL} kcal ≈ {sign}{round(proj, 2)} kg/week\n"
    )

def trend_str(this_val: float, prev_val: float) -> str:
    if not prev_val:
        return ""
    diff = this_val - prev_val
    if diff == 0:
        return "↔ gelijk"
    arrow = "↑" if diff > 0 else "↓"
    return f"{arrow} {abs(int(diff))}"

def main() -> None:
    now      = datetime.datetime.now(BRUSSELS)
    week_num = now.isocalendar()[1]

    maaltijden = fetch_data("maaltijden", 25)
    gewichten  = fetch_data("gewicht", 25)
    sport_rows = fetch_data("sport", 100)  # 1 rij per activiteit

    if not maaltijden:
        if UNAUTHORIZED:
            send_message(
                "⚠️ doGet weigerde de API-key.\n\n"
                "Check of deze 3 exact dezelfde waarde hebben:\n"
                "1. GitHub secret `APPS_SCRIPT_KEY`\n"
                "2. Apps Script property `API_KEY`\n"
                "3. En of er een *nieuwe versie* gedeployed is"
            )
        else:
            send_message("📊 Kon geen maaltijddata ophalen voor het wekelijks overzicht.")
        return

    this_week = maaltijden[-7:] if len(maaltijden) >= 7 else maaltijden
    prev_week = maaltijden[-14:-7] if len(maaltijden) >= 14 else []

    logged_days = len(this_week)

    # ── Sport deze week (afgelopen 7 dagen t.e.m. gisteren; run = maandagochtend)
    week_start = now.date() - datetime.timedelta(days=7)
    sport_by_date: dict = {}
    sport_week = []
    for r in sport_rows:
        if not isinstance(r, dict):
            continue
        d = parse_date(r.get("datum", ""))
        k = safe_num(r.get("kcal"))
        if not d:
            continue
        sport_by_date[d] = sport_by_date.get(d, 0) + k
        if week_start <= d < now.date():
            sport_week.append((d, k))

    # Gemiddeld dynamisch dagdoel over de gelogde dagen (doel + compensatie × sport)
    dyn_doelen = []
    for r in this_week:
        d = parse_date(r.get("datum", "")) if isinstance(r, dict) else None
        sport_kcal_dag = sport_by_date.get(d, 0) if d else 0
        dyn_doelen.append(DOEL_KCAL + SPORT_COMPENSATIE * sport_kcal_dag)
    gem_dag_doel = round(sum(dyn_doelen) / len(dyn_doelen)) if dyn_doelen else DOEL_KCAL

    avg_cal   = week_avg(this_week, "calories")
    avg_eiwit = week_avg(this_week, "eiwitten")
    avg_koolh = week_avg(this_week, "koolhydraten")
    avg_vet   = week_avg(this_week, "vetten")
    avg_vezel = week_avg(this_week, "vezels")
    avg_score = score_avg(this_week)

    prev_cal   = week_avg(prev_week, "calories")   if prev_week else 0
    prev_eiwit = week_avg(prev_week, "eiwitten")   if prev_week else 0
    prev_score = score_avg(prev_week)               if prev_week else 0.0

    meal_lines = ""
    for key, label, emoji in [
        ("ontbijt_kcal",   "Ontbijt",   "🌅"),
        ("lunch_kcal",     "Lunch",     "☀️"),
        ("avondeten_kcal", "Avondeten", "🌙"),
        ("snacks_kcal",    "Snacks",    "🍎"),
    ]:
        avg_meal = week_avg(this_week, key)
        if avg_meal > 0:
            meal_lines += f"  {emoji} {label}: ~{avg_meal} kcal/dag\n"

    prev_blok = ""
    if prev_week:
        prev_blok = (
            f"\n📉 *Vs. vorige week:*\n"
            f"  Calorieën: {trend_str(avg_cal, prev_cal)} kcal\n"
            f"  Eiwitten:  {trend_str(avg_eiwit, prev_eiwit)} g\n"
            f"  Score:     {trend_str(avg_score, prev_score)}\n"
        )

    # Gewichtstrend op basis van 7-daags voortschrijdend gemiddelde (dagelijkse
    # schommelingen door vocht/maaginhoud filteren eruit)
    wbd     = weights_by_date(gewichten)
    today_d = now.date()
    ma_now  = moving_avg(wbd, today_d)
    ma_prev = moving_avg(wbd, today_d - datetime.timedelta(days=7))

    gewicht_tekst = ""
    if ma_now is not None and ma_prev is not None:
        diff = round(ma_now - ma_prev, 1)
        sign = "+" if diff > 0 else ""
        gewicht_tekst = (
            f"\n⚖️ Gewicht (7-daags gem.): {round(ma_prev, 1)} kg → "
            f"{round(ma_now, 1)} kg ({sign}{diff} kg)\n"
        )
    elif wbd:
        laatste_datum = max(wbd)
        gewicht_tekst = f"\n⚖️ Huidig gewicht: {wbd[laatste_datum]} kg\n"

    def doel_diff(gemiddelde, doel):
        diff = gemiddelde - doel
        if abs(diff) <= doel * 0.05:
            return "✅ op doel"
        return f"{'↑' if diff > 0 else '↓'} {abs(int(diff))} {'te veel' if diff > 0 else 'te weinig'}"

    sport_blok = ""
    if sport_week:
        sport_dagen = len({d for d, _ in sport_week})
        sport_tot   = int(sum(k for _, k in sport_week))
        sport_blok = (
            f"\n🚴 *Sport deze week:*\n"
            f"  {len(sport_week)} activiteit{'en' if len(sport_week) != 1 else ''} "
            f"op {sport_dagen} dag{'en' if sport_dagen != 1 else ''} — "
            f"{sport_tot} kcal verbrand\n"
        )

    doel_lijn_kcal = f"{DOEL_KCAL} kcal"
    if gem_dag_doel != DOEL_KCAL:
        doel_lijn_kcal = f"gem. {gem_dag_doel} kcal incl. sport"

    doel_blok = (
        f"\n🎯 *Vs. jouw doelen ({doel_lijn_kcal}):*\n"
        f"  🔥 Calorieën: {avg_cal} kcal — {doel_diff(avg_cal, gem_dag_doel)}\n"
        f"  💪 Eiwitten:  {avg_eiwit}g — {doel_diff(avg_eiwit, DOEL_EIWIT)}\n"
        f"  🌾 Koolh:     {avg_koolh}g — {doel_diff(avg_koolh, DOEL_KOOLH)}\n"
        f"  🥑 Vetten:    {avg_vet}g — {doel_diff(avg_vet, DOEL_VET)}\n"
        f"  🥦 Vezels:    {avg_vezel}g — {doel_diff(avg_vezel, DOEL_VEZEL)}\n"
    )

    recent_notes = [r.get("notities", "") for r in this_week if r.get("notities")]
    sport_ai = ""
    if sport_week:
        sport_ai = (
            f"Sport deze week: {int(sum(k for _, k in sport_week))} kcal verbrand op "
            f"{len({d for d, _ in sport_week})} dagen; gem. dagdoel incl. sportcompensatie: {gem_dag_doel} kcal. "
        )
    context_for_ai = (
        f"Doelen: {DOEL_KCAL} kcal, {DOEL_EIWIT}g eiwit, {DOEL_KOOLH}g koolh, {DOEL_VET}g vet, {DOEL_VEZEL}g vezels. "
        f"Doel-richting: {RICHTING_TEKST}. "
        f"{sport_ai}"
        f"Gemiddeld deze week: {avg_cal} kcal, {avg_eiwit}g eiwit, score {avg_score}/10. "
        f"Notities: {'; '.join(recent_notes[-3:]) if recent_notes else 'geen'}."
    )
    try:
        ai_resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": (
                f"Geef één korte motiverende tip (max 2 zinnen) over deze voedingsweek met focus op het belangrijkste verbeterpunt t.o.v. de doelen: {context_for_ai} "
                "Schrijf in het Nederlands, casual en persoonlijk. Geen aanhef."
            )}],
            temperature=0.7,
            max_tokens=100,
        )
        ai_tip = ai_resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"AI-tip mislukt: {e}")
        ai_tip = "Blijf zo doorgaan!"

    message = (
        f"📊 *Wekelijks Overzicht — Week {week_num}*\n\n"
        f"🗓️ {logged_days}/7 dagen gelogd\n\n"
        f"📈 *Gemiddelden deze week:*\n"
        f"🔥 Calorieën: *{avg_cal} kcal/dag*\n"
        f"💪 Eiwitten: {avg_eiwit} g/dag\n"
        f"🌾 Koolhydraten: {avg_koolh} g/dag\n"
        f"🥑 Vetten: {avg_vet} g/dag\n"
        f"🥦 Vezels: {avg_vezel} g/dag\n"
        f"⭐ Score: {avg_score}/10\n"
        f"{gewicht_tekst}"
    )

    if meal_lines:
        message += f"\n🍽️ *Verdeling per maaltijd:*\n{meal_lines}"

    message += f"{sport_blok}{doel_blok}{tdee_blok(maaltijden, wbd, today_d)}{prev_blok}\n💬 _{ai_tip}_"

    send_message(message)

if __name__ == "__main__":
    main()
