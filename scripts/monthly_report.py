"""
Maandrapport: grafieken (matplotlib) + samenvatting via Telegram sendPhoto.
Draait op de 1e van de maand (cron-job.org) en rapporteert over de vorige maand.
TEST_MODE=1 → rapporteert over de huidige maand tot vandaag (om te testen).
"""

import os
import io
import json
import datetime
import requests
import pytz

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from intervals import wellness_tussen, alcohol_contrast

BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = os.environ["CHAT_ID"]
APPS_SCRIPT_URL = os.environ["APPS_SCRIPT_URL"]
GROQ_API_KEY    = os.environ.get("GROQ_API_KEY", "")
APPS_SCRIPT_KEY = os.environ.get("APPS_SCRIPT_KEY", "")
TEST_MODE       = os.environ.get("TEST_MODE", "").lower() in ("1", "true")

BRUSSELS = pytz.timezone("Europe/Brussels")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni",
           "juli", "augustus", "september", "oktober", "november", "december"]

def load_doelen() -> dict:
    with open("data/config/config.json", encoding="utf-8") as f:
        return json.load(f)["doelen"]

_doelen    = load_doelen()
DOEL_KCAL  = _doelen["kcal"]
DOEL_EIWIT = _doelen["eiwitten"]
SPORT_COMPENSATIE = float(_doelen.get("sport_compensatie", 1.0))
RICHTING_TEKST = {
    "aankomen":    "aankomen — een calorie-surplus en voldoende eiwit zijn gewenst; gewichtsverlies is hier juist ongewenst",
    "afvallen":    "afvallen — een calorie-tekort is gewenst",
    "onderhouden": "gewicht onderhouden — rond het caloriedoel eten is gewenst",
}.get(_doelen.get("richting", "onderhouden"), _doelen.get("richting", "onderhouden"))

def send_message(text: str) -> None:
    requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown",
    }, timeout=10)

def send_photo(png_bytes: bytes, caption: str) -> bool:
    resp = requests.post(
        f"{BASE_URL}/sendPhoto",
        data={"chat_id": CHAT_ID, "caption": caption[:1024], "parse_mode": "Markdown"},
        files={"photo": ("maandrapport.png", png_bytes, "image/png")},
        timeout=30,
    )
    if not resp.ok:
        print(f"sendPhoto fout: {resp.status_code} — {resp.text}")
    return resp.ok

UNAUTHORIZED = False  # wordt True als doGet de key weigert

def fetch_data(data_type: str, limit: int) -> list:
    global UNAUTHORIZED
    try:
        resp = requests.get(
            APPS_SCRIPT_URL,
            params={"type": data_type, "limit": limit, "key": APPS_SCRIPT_KEY},
            timeout=15,
            allow_redirects=False,
        )
        if resp.status_code in (301, 302, 303, 307, 308):
            resp = requests.get(resp.headers.get("Location", ""), timeout=15)
        rows = resp.json()
        if isinstance(rows, dict) and rows.get("error") == "unauthorized":
            UNAUTHORIZED = True
            print(f"doGet weigerde de key (unauthorized) voor type={data_type}")
        return rows if isinstance(rows, list) else []
    except Exception as e:
        print(f"Data ophalen mislukt ({data_type}): {e}")
        return []

def safe_num(val, default: float = 0.0) -> float:
    try:
        return float(val) if val else default
    except (TypeError, ValueError):
        return default

def parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None

def moving_avg(wbd: dict, end: datetime.date, window: int = 7):
    vals = [
        wbd[end - datetime.timedelta(days=i)]
        for i in range(window)
        if (end - datetime.timedelta(days=i)) in wbd
    ]
    return round(sum(vals) / len(vals), 2) if len(vals) >= 3 else None

def ma_ankers(wbd: dict, eerste: datetime.date, laatste: datetime.date):
    """Eerste en laatste datum in de periode met een geldig 7d-gemiddelde.
    Adaptief: zo werkt de trend ook als de weeghistoriek pas midden in de maand begint."""
    anker_a = anker_b = None
    d = eerste
    while d <= laatste:
        if moving_avg(wbd, d) is not None:
            if anker_a is None:
                anker_a = d
            anker_b = d
        d += datetime.timedelta(days=1)
    return anker_a, anker_b

def maand_bereik(today: datetime.date):
    """(eerste_dag, laatste_dag, label) van de rapportmaand."""
    if TEST_MODE:
        eerste = today.replace(day=1)
        return eerste, today, f"{MAANDEN[eerste.month - 1]} {eerste.year} (test, t.e.m. vandaag)"
    eerste_van_deze = today.replace(day=1)
    laatste = eerste_van_deze - datetime.timedelta(days=1)
    eerste  = laatste.replace(day=1)
    return eerste, laatste, f"{MAANDEN[eerste.month - 1]} {eerste.year}"

# ── Grafieken ─────────────────────────────────────────────────────────────────
def maak_grafiek(rows: list, wbd: dict, eerste: datetime.date, laatste: datetime.date,
                 titel: str, sport_by_day: dict = None, wellness: list = None) -> bytes:
    sport_by_day = sport_by_day or {}
    wellness = wellness or []
    fig, axes = plt.subplots(3, 2, figsize=(11, 12.5))
    fig.suptitle(f"Maandrapport — {titel}", fontsize=14, fontweight="bold")

    dagen   = [r["datum"].day for r in rows]
    kcals   = [r["kcal"] for r in rows]
    eiwits  = [r["eiwit"] for r in rows]

    # 1. Gewicht + 7d gemiddelde
    ax = axes[0][0]
    alle_dagen = [eerste + datetime.timedelta(days=i) for i in range((laatste - eerste).days + 1)]
    raw_x = [d.day for d in alle_dagen if d in wbd]
    raw_y = [wbd[d] for d in alle_dagen if d in wbd]
    ma_pts = [(d.day, moving_avg(wbd, d)) for d in alle_dagen]
    ma_pts = [(x, y) for x, y in ma_pts if y is not None]
    if raw_x:
        ax.plot(raw_x, raw_y, "o", color="#5b7fa6", markersize=4, alpha=0.6, label="meting")
    if ma_pts:
        ax.plot([p[0] for p in ma_pts], [p[1] for p in ma_pts], "-", color="#111", linewidth=2, label="7d gem.")
    if raw_x or ma_pts:
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "geen wegingen", ha="center", va="center", transform=ax.transAxes, color="#888")
    ax.set_title("Gewicht (kg)", fontsize=10)

    # 2. Calorieën per dag vs. doel (dynamisch doel op sportdagen)
    ax = axes[0][1]
    kleuren = [
        "#c95f5f" if r["kcal"] > DOEL_KCAL + SPORT_COMPENSATIE * sport_by_day.get(r["datum"], 0)
        else "#4c9a6e"
        for r in rows
    ]
    ax.bar(dagen, kcals, color=kleuren)
    sport_dgn = sorted(d for d, k in sport_by_day.items() if eerste <= d <= laatste and k > 0)
    if sport_dgn:
        ax.bar([d.day for d in sport_dgn], [sport_by_day[d] for d in sport_dgn],
               width=0.45, color="#7e6bb5", alpha=0.85, label="sport (verbrand)")
    ax.axhline(DOEL_KCAL, color="#111", linestyle="--", linewidth=1.5, label=f"doel {DOEL_KCAL}")
    ax.legend(fontsize=8)
    ax.set_title("Calorieën per dag", fontsize=10)

    # 3. Eiwitten per dag vs. doel
    ax = axes[1][0]
    ax.bar(dagen, eiwits, color="#5b7fa6")
    ax.axhline(DOEL_EIWIT, color="#111", linestyle="--", linewidth=1.5, label=f"doel {DOEL_EIWIT}g")
    ax.legend(fontsize=8)
    ax.set_title("Eiwitten per dag (g)", fontsize=10)

    # 4. Gestapeld weekgemiddelde per maaltijd
    ax = axes[1][1]
    weken: dict = {}
    for r in rows:
        weken.setdefault(f"W{r['datum'].isocalendar()[1]}", []).append(r)
    week_labels = list(weken.keys())
    onderdelen = [("ontbijt", "#c9a227", "Ontbijt"), ("lunch", "#5b7fa6", "Lunch"),
                  ("avond", "#4c9a6e", "Avondeten"), ("snacks", "#c95f5f", "Snacks")]
    bottom = [0] * len(week_labels)
    for key, kleur, label in onderdelen:
        waarden = [round(sum(r[key] for r in weken[w]) / len(weken[w])) for w in week_labels]
        ax.bar(week_labels, waarden, bottom=bottom, color=kleur, label=label)
        bottom = [b + w for b, w in zip(bottom, waarden)]
    ax.legend(fontsize=7)
    ax.set_title("Gem. kcal per maaltijd, per week", fontsize=10)

    # 5. Herstel: HRV + rusthartslag
    ax = axes[2][0]
    w_pts = [(parse_date(w.get("datum", "")), w) for w in wellness]
    w_pts = [(d, w) for d, w in w_pts if d and eerste <= d <= laatste]
    hrv_pts = [(d.day, w["hrv"]) for d, w in w_pts if w.get("hrv")]
    rhr_pts = [(d.day, w["rhr"]) for d, w in w_pts if w.get("rhr")]
    if hrv_pts:
        ax.plot([x for x, _ in hrv_pts], [y for _, y in hrv_pts], "-o",
                color="#4c9a6e", markersize=3, linewidth=1.5, label="HRV")
        ax.legend(loc="upper left", fontsize=8)
    if rhr_pts:
        ax_r = ax.twinx()
        ax_r.plot([x for x, _ in rhr_pts], [y for _, y in rhr_pts], "-o",
                  color="#c95f5f", markersize=3, linewidth=1.5, label="RHR")
        ax_r.tick_params(labelsize=8)
        ax_r.legend(loc="upper right", fontsize=8)
    if not hrv_pts and not rhr_pts:
        ax.text(0.5, 0.5, "geen wellness-data", ha="center", va="center",
                transform=ax.transAxes, color="#888")
    ax.set_title("Herstel: HRV & rusthartslag", fontsize=10)

    # 6. Slaap: uren + score
    ax = axes[2][1]
    slaap_pts = [(d.day, w["slaap_u"]) for d, w in w_pts if w.get("slaap_u")]
    score_pts = [(d.day, w["slaapscore"]) for d, w in w_pts if w.get("slaapscore")]
    if slaap_pts:
        ax.bar([x for x, _ in slaap_pts], [y for _, y in slaap_pts],
               color="#5b7fa6", alpha=0.7, label="uren")
        ax.legend(loc="upper left", fontsize=8)
    if score_pts:
        ax_s = ax.twinx()
        ax_s.plot([x for x, _ in score_pts], [y for _, y in score_pts], "-",
                  color="#c9a227", linewidth=1.5, label="score")
        ax_s.set_ylim(0, 100)
        ax_s.tick_params(labelsize=8)
        ax_s.legend(loc="upper right", fontsize=8)
    if not slaap_pts and not score_pts:
        ax.text(0.5, 0.5, "geen slaapdata", ha="center", va="center",
                transform=ax.transAxes, color="#888")
    ax.set_title("Slaap (u) & slaapscore", fontsize=10)

    for rij in axes:
        for ax in rij:
            ax.grid(alpha=0.25)
            ax.tick_params(labelsize=8)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()

# ── Samenvatting ──────────────────────────────────────────────────────────────
def tdee_schatting(rows: list, wbd: dict, eerste: datetime.date, laatste: datetime.date) -> str:
    anker_a, anker_b = ma_ankers(wbd, eerste, laatste)
    if not anker_a or not anker_b:
        return "🔬 TDEE: te weinig wegingen deze maand"

    span = (anker_b - anker_a).days
    if span < 10:
        return "🔬 TDEE: gewichtshistoriek nog te kort (min. 10 dagen)"

    kcals = [r["kcal"] for r in rows if anker_a <= r["datum"] <= anker_b]
    min_logged = max(7, round(span * 0.6))
    if len(kcals) < min_logged:
        return f"🔬 TDEE: te weinig gelogde dagen in de meetperiode ({len(kcals)}/{min_logged})"

    ma_a = moving_avg(wbd, anker_a)
    ma_b = moving_avg(wbd, anker_b)
    tdee = sum(kcals) / len(kcals) - ((ma_b - ma_a) * 7700 / span)
    tdee_r = round(tdee / 50) * 50
    if not 1500 <= tdee_r <= 4500:
        return "🔬 TDEE: onbetrouwbaar deze maand"
    return f"🔬 Geschatte TDEE: ~{tdee_r} kcal/dag ({anker_a.strftime('%d/%m')}–{anker_b.strftime('%d/%m')})"

def groq_reflectie(context: str) -> str:
    if not GROQ_API_KEY:
        return ""
    try:
        from groq import Groq
        resp = Groq(api_key=GROQ_API_KEY).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": (
                f"Maandoverzicht voeding van Marti: {context}\n"
                f"Doel-richting: {RICHTING_TEKST}.\n"
                "Geef één korte reflectie (max 2 zinnen, Nederlands, casual) over deze maand "
                "met het belangrijkste aandachtspunt, rekening houdend met de doel-richting. "
                "Spreek Marti rechtstreeks aan met 'je'. Geen aanhef."
            )}],
            temperature=0.6,
            max_tokens=100,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq-reflectie mislukt: {e}")
        return ""

def main() -> None:
    today = datetime.datetime.now(BRUSSELS).date()
    eerste, laatste, titel = maand_bereik(today)

    maaltijden_raw = fetch_data("maaltijden", 70)
    gewichten_raw  = fetch_data("gewicht", 70)
    sport_raw      = fetch_data("sport", 200)
    wellness       = wellness_tussen(eerste.isoformat(), laatste.isoformat())

    if not maaltijden_raw:
        if UNAUTHORIZED:
            send_message(
                "⚠️ Maandrapport: doGet weigerde de API-key.\n\n"
                "Check of deze 3 exact dezelfde waarde hebben:\n"
                "1. GitHub secret `APPS_SCRIPT_KEY`\n"
                "2. Apps Script property `API_KEY`\n"
                "3. En of er een *nieuwe versie* gedeployed is"
            )
        else:
            send_message("⚠️ Maandrapport: kon geen data ophalen via doGet.")
        return

    rows = []
    for r in maaltijden_raw:
        if not isinstance(r, dict):
            continue
        d = parse_date(r.get("datum", ""))
        if not d or not (eerste <= d <= laatste):
            continue
        kcal = safe_num(r.get("calories"))
        if kcal <= 0:
            continue
        rows.append({
            "datum": d, "kcal": kcal,
            "eiwit":  safe_num(r.get("eiwitten")),
            "score":  safe_num(r.get("score")),
            "ontbijt": safe_num(r.get("ontbijt_kcal")),
            "lunch":   safe_num(r.get("lunch_kcal")),
            "avond":   safe_num(r.get("avondeten_kcal")),
            "snacks":  safe_num(r.get("snacks_kcal")),
        })
    rows.sort(key=lambda r: r["datum"])

    # wegingen: ook vóór de maand (nodig voor het 7d-gemiddelde aan de maandstart)
    wbd = {}
    for r in gewichten_raw:
        if not isinstance(r, dict):
            continue
        d = parse_date(r.get("datum", ""))
        g = safe_num(r.get("gewicht"))
        if d and g > 0:
            wbd[d] = g

    # sport: kcal per dag + statistieken voor deze maand
    sport_by_day: dict = {}
    sport_acts = 0
    for r in sport_raw:
        if not isinstance(r, dict):
            continue
        d = parse_date(r.get("datum", ""))
        k = safe_num(r.get("kcal"))
        if d and eerste <= d <= laatste:
            sport_by_day[d] = sport_by_day.get(d, 0) + k
            sport_acts += 1

    if len(rows) < 5:
        send_message(
            f"📅 *Maandrapport {titel}*\n\n"
            f"Te weinig gelogde dagen ({len(rows)}) om een rapport te maken. "
            f"Volgende maand beter!"
        )
        return

    # ── statistieken
    dagen_in_maand = (laatste - eerste).days + 1
    avg_kcal  = round(sum(r["kcal"] for r in rows) / len(rows))
    avg_eiwit = round(sum(r["eiwit"] for r in rows) / len(rows))
    scores    = [r["score"] for r in rows if r["score"] > 0]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    anker_a, anker_b = ma_ankers(wbd, eerste, laatste)
    if anker_a and anker_b and (anker_b - anker_a).days >= 7:
        ma_a = moving_avg(wbd, anker_a)
        ma_b = moving_avg(wbd, anker_b)
        diff = round(ma_b - ma_a, 1)
        gewicht_lijn = f"⚖️ {round(ma_a, 1)} → {round(ma_b, 1)} kg ({'+' if diff > 0 else ''}{diff} kg, 7d gem.)"
    elif wbd:
        gewicht_lijn = f"⚖️ Laatste gewicht: {wbd[max(wbd)]} kg (historiek nog te kort voor trend)"
    else:
        gewicht_lijn = "⚖️ Geen wegingen deze maand"

    # beste week op score
    weken: dict = {}
    for r in rows:
        if r["score"] > 0:
            weken.setdefault(r["datum"].isocalendar()[1], []).append(r["score"])
    beste_lijn = ""
    if weken:
        beste_week, beste_scores = max(weken.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
        beste_lijn = f"🏆 Beste week: W{beste_week} (score {round(sum(beste_scores) / len(beste_scores), 1)})\n"

    tdee_lijn = tdee_schatting(rows, wbd, eerste, laatste)

    sport_lijn = ""
    sport_ai   = ""
    if sport_by_day:
        sport_tot = int(sum(sport_by_day.values()))
        sport_lijn = (
            f"🚴 {sport_acts} activiteit{'en' if sport_acts != 1 else ''} op "
            f"{len(sport_by_day)} dag{'en' if len(sport_by_day) != 1 else ''} — "
            f"{sport_tot} kcal verbrand\n"
        )
        sport_ai = f", sport: {sport_tot} kcal verbrand op {len(sport_by_day)} dagen"

    wellness_lijn = ""
    wellness_ai   = ""
    if wellness:
        def w_avg(key):
            vals = [r[key] for r in wellness if isinstance(r, dict) and r.get(key)]
            return round(sum(vals) / len(vals), 1) if vals else None
        hrv_m, rhr_m  = w_avg("hrv"), w_avg("rhr")
        slaap_m, sc_m = w_avg("slaap_u"), w_avg("slaapscore")
        delen = []
        if hrv_m:
            delen.append(f"HRV {round(hrv_m)}")
        if rhr_m:
            delen.append(f"RHR {round(rhr_m)}")
        if slaap_m:
            sl = f"slaap {slaap_m}u"
            if sc_m:
                sl += f" (score {round(sc_m)})"
            delen.append(sl)
        if delen:
            wellness_lijn = "🫀 Gem. " + " · ".join(delen) + "\n"
            wellness_ai   = ", herstel: " + " · ".join(delen)
        contrast = alcohol_contrast(maaltijden_raw, wellness)
        if contrast:
            extra = f"🍺 Nacht na alcohol (n={contrast['n_alcohol']}): HRV {contrast['d_hrv']:+.0f}"
            if contrast.get("d_slaapscore") is not None:
                extra += f" · slaapscore {contrast['d_slaapscore']:+.0f}"
            wellness_lijn += extra + "\n"

    reflectie = groq_reflectie(
        f"{titel}: {len(rows)}/{dagen_in_maand} dagen gelogd, gem. {avg_kcal} kcal "
        f"(doel {DOEL_KCAL}), gem. {avg_eiwit}g eiwit (doel {DOEL_EIWIT}g), "
        f"score {avg_score}/10, gewicht: {gewicht_lijn}{sport_ai}{wellness_ai}"
    )

    caption = (
        f"📅 *Maandrapport — {titel}*\n\n"
        f"🗓️ {len(rows)}/{dagen_in_maand} dagen gelogd\n"
        f"🔥 Gem. {avg_kcal} kcal/dag (doel {DOEL_KCAL})\n"
        f"💪 Gem. {avg_eiwit}g eiwit/dag (doel {DOEL_EIWIT}g)\n"
        f"⭐ Gem. score: {avg_score}/10\n"
        f"{sport_lijn}"
        f"{wellness_lijn}"
        f"{gewicht_lijn}\n"
        f"{beste_lijn}"
        f"{tdee_lijn}"
    )
    if reflectie:
        caption += f"\n\n💬 _{reflectie[:280]}_"

    png = maak_grafiek(rows, wbd, eerste, laatste, titel, sport_by_day, wellness)

    if not send_photo(png, caption):
        # vangnet: stuur minstens de tekst
        send_message(caption)

if __name__ == "__main__":
    main()
