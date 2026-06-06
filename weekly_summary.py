import os
import re
import json
import datetime
import requests
import pytz
from groq import Groq

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = os.environ["CHAT_ID"]
APPS_SCRIPT_URL = os.environ["APPS_SCRIPT_URL"]
GROQ_API_KEY    = os.environ["GROQ_API_KEY"]

BRUSSELS    = pytz.timezone("Europe/Brussels")
BASE_URL    = f"https://api.telegram.org/bot{BOT_TOKEN}"
groq_client = Groq(api_key=GROQ_API_KEY)

# Dagelijkse macrodoelen
DOEL_KCAL  = 2750
DOEL_EIWIT = 150
DOEL_KOOLH = 320
DOEL_VET   = 85
DOEL_VEZEL = 30


# ── Telegram ──────────────────────────────────────────────────────────────────
def send_message(text: str) -> None:
    requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown",
    }, timeout=10)


# ── Data ophalen ──────────────────────────────────────────────────────────────
def fetch_data(data_type: str, limit: int) -> list:
    url = APPS_SCRIPT_URL
    params = {"type": data_type, "limit": limit}
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
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"[DEBUG] JSON parse mislukt: {e}")
        return []


# ── Hulpfuncties ──────────────────────────────────────────────────────────────
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


def trend_str(this_val: float, prev_val: float) -> str:
    if not prev_val:
        return ""
    diff = this_val - prev_val
    if diff == 0:
        return "↔ gelijk"
    arrow = "↑" if diff > 0 else "↓"
    return f"{arrow} {abs(int(diff))}"


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    now      = datetime.datetime.now(BRUSSELS)
    week_num = now.isocalendar()[1]

    maaltijden = fetch_data("maaltijden", 14)
    gewichten  = fetch_data("gewicht", 14)

    if not maaltijden:
        send_message("📊 Kon geen maaltijddata ophalen voor het wekelijks overzicht.")
        return

    # Splits in deze week (laatste 7 rijen) en vorige week
    this_week = maaltijden[-7:] if len(maaltijden) >= 7 else maaltijden
    prev_week = maaltijden[-14:-7] if len(maaltijden) >= 14 else []

    logged_days = len(this_week)

    # Gemiddelden deze week
    avg_cal   = week_avg(this_week, "calories")
    avg_eiwit = week_avg(this_week, "eiwitten")
    avg_koolh = week_avg(this_week, "koolhydraten")
    avg_vet   = week_avg(this_week, "vetten")
    avg_vezel = week_avg(this_week, "vezels")
    avg_score = score_avg(this_week)

    # Gemiddelden vorige week (voor vergelijking)
    prev_cal   = week_avg(prev_week, "calories")   if prev_week else 0
    prev_eiwit = week_avg(prev_week, "eiwitten")   if prev_week else 0
    prev_score = score_avg(prev_week)               if prev_week else 0.0

    # Per-maaltijd verdeling (gemiddeld per dag)
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

    # Vergelijkingsblok
    prev_blok = ""
    if prev_week:
        prev_blok = (
            f"\n📉 *Vs. vorige week:*\n"
            f"  Calorieën: {trend_str(avg_cal, prev_cal)} kcal\n"
            f"  Eiwitten:  {trend_str(avg_eiwit, prev_eiwit)} g\n"
            f"  Score:     {trend_str(avg_score, prev_score)}\n"
        )

    # Gewichtstrend
    gewicht_tekst = ""
    gew_vals = [safe_num(r.get("gewicht")) for r in gewichten if safe_num(r.get("gewicht")) > 0]
    if len(gew_vals) >= 2:
        diff = round(gew_vals[-1] - gew_vals[0], 1)
        sign = "+" if diff > 0 else ""
        gewicht_tekst = f"\n⚖️ Gewicht: {gew_vals[0]} kg → {gew_vals[-1]} kg ({sign}{diff} kg)\n"
    elif gew_vals:
        gewicht_tekst = f"\n⚖️ Huidig gewicht: {gew_vals[-1]} kg\n"

    # vs.-doel vergelijking
    def doel_diff(gemiddelde, doel):
        diff = gemiddelde - doel
        if abs(diff) <= doel * 0.05:
            return "✅ op doel"
        return f"{'↑' if diff > 0 else '↓'} {abs(int(diff))} {'te veel' if diff > 0 else 'te weinig'}"

    doel_blok = (
        f"\n🎯 *Vs. jouw doelen ({DOEL_KCAL} kcal):*\n"
        f"  🔥 Calorieën: {avg_cal} kcal — {doel_diff(avg_cal, DOEL_KCAL)}\n"
        f"  💪 Eiwitten:  {avg_eiwit}g — {doel_diff(avg_eiwit, DOEL_EIWIT)}\n"
        f"  🌾 Koolh:     {avg_koolh}g — {doel_diff(avg_koolh, DOEL_KOOLH)}\n"
        f"  🥑 Vetten:    {avg_vet}g — {doel_diff(avg_vet, DOEL_VET)}\n"
        f"  🥦 Vezels:    {avg_vezel}g — {doel_diff(avg_vezel, DOEL_VEZEL)}\n"
    )

    # AI-tip over de week
    recent_notes = [r.get("notities", "") for r in this_week if r.get("notities")]
    context_for_ai = (
        f"Doelen: {DOEL_KCAL} kcal, {DOEL_EIWIT}g eiwit, {DOEL_KOOLH}g koolh, {DOEL_VET}g vet, {DOEL_VEZEL}g vezels. "
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

    # Bericht samenstellen
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

    message += f"{doel_blok}{prev_blok}\n💬 _{ai_tip}_"

    send_message(message)


if __name__ == "__main__":
    main()
