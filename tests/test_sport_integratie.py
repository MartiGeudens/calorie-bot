# -*- coding: utf-8 -*-
"""Mock-tests voor de sport-integratie. Geen netwerk, geen echte API's."""
import json
import os
import sys
import types
import datetime
import unittest.mock as mock

os.environ.update({
    "BOT_TOKEN": "x", "CHAT_ID": "123", "GROQ_API_KEY": "x",
    "APPS_SCRIPT_URL": "https://example.invalid/exec", "APPS_SCRIPT_KEY": "k",
})
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_REPO)  # scripts lezen data/config/* relatief aan de repo-root
sys.path.insert(0, os.path.join(_REPO, "scripts"))

FOUTEN = []
def check(naam, cond, extra=""):
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {naam}{(' — ' + extra) if extra and not cond else ''}")
    if not cond:
        FOUTEN.append(naam)

# ── stub groq vóór imports (geen echte client nodig) ─────────────────────────
groq_stub = types.ModuleType("groq")
class _FakeGroq:
    def __init__(self, api_key=None):
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))
    @staticmethod
    def _create(**kwargs):
        raise RuntimeError("groq mag niet echt aangeroepen worden in tests")
groq_stub.Groq = _FakeGroq
sys.modules["groq"] = groq_stub

# ── 1. intervals.py ───────────────────────────────────────────────────────────
import intervals

VOORBEELD_API = [
    {"id": "i111", "start_date_local": "2026-06-11T07:35:18", "type": "Ride", "name": "Ochtendrit",
     "moving_time": 5520, "elapsed_time": 5710, "distance": 45230.5, "calories": 612, "average_heartrate": 148.4},
    {"id": "i222", "start_date_local": "2026-06-11T18:02:00", "type": "Run", "name": None,
     "moving_time": 1860, "distance": 6100, "calories": 285, "average_heartrate": 156},
    {"id": "i333", "start_date_local": "2026-06-10T19:00:00", "type": "WeightTraining", "name": "Kracht",
     "moving_time": 3600, "distance": None, "calories": None, "average_heartrate": 120},
]

class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.ok, self.status_code = data, status == 200, status
    def json(self):
        return self._data

# zonder key → leeg
os.environ.pop("INTERVALS_API_KEY", None)
check("intervals: geen key → lege lijst", intervals.activiteiten_tussen("2026-06-10", "2026-06-11") == [])

os.environ["INTERVALS_API_KEY"] = "testkey"

with mock.patch.object(intervals.requests, "get", return_value=FakeResp(VOORBEELD_API)) as g:
    acts = intervals.activiteiten_tussen("2026-06-10", "2026-06-11")
    check("intervals: 3 activiteiten geparsed", len(acts) == 3, f"kreeg {len(acts)}")
    a = acts[0]
    check("intervals: kcal exact", a["kcal"] == 612, str(a))
    check("intervals: datum uit start_date_local", a["datum"] == "2026-06-11", a["datum"])
    check("intervals: duur_min uit moving_time", a["duur_min"] == 92, str(a["duur_min"]))
    check("intervals: afstand_km afgerond", a["afstand_km"] == 45.2, str(a["afstand_km"]))
    check("intervals: gem_hs afgerond", a["gem_hs"] == 148, str(a["gem_hs"]))
    check("intervals: naam fallback op type", acts[1]["naam"] == "Run", acts[1]["naam"])
    check("intervals: kcal None → 0", acts[2]["kcal"] == 0, str(acts[2]["kcal"]))
    check("intervals: auth correct", g.call_args.kwargs["auth"] == ("API_KEY", "testkey"))
    check("intervals: params correct", g.call_args.kwargs["params"] == {"oldest": "2026-06-10", "newest": "2026-06-11"})

with mock.patch.object(intervals.requests, "get", return_value=FakeResp(VOORBEELD_API)):
    vandaag = intervals.activiteiten_van("2026-06-11")
    check("intervals: activiteiten_van filtert op dag", len(vandaag) == 2 and all(x["datum"] == "2026-06-11" for x in vandaag))
    check("intervals: sport_kcal_totaal", intervals.sport_kcal_totaal(vandaag) == 897, str(intervals.sport_kcal_totaal(vandaag)))
    regel = intervals.sport_regel(vandaag)
    check("intervals: sport_regel", "Ride 92 min" in regel and "45.2 km" in regel and "Run" in regel, regel)

check("intervals: dagdoel 1.0", intervals.dagdoel(2750, 1.0, 600) == 3350)
check("intervals: dagdoel 0.5", intervals.dagdoel(2750, 0.5, 600) == 3050)
check("intervals: dagdoel zonder sport", intervals.dagdoel(2750, 1.0, 0) == 2750)

# fouten → stil falen
with mock.patch.object(intervals.requests, "get", return_value=FakeResp({"error": "x"}, 401)):
    check("intervals: HTTP 401 → lege lijst", intervals.activiteiten_tussen("2026-06-11", "2026-06-11") == [])
with mock.patch.object(intervals.requests, "get", side_effect=ConnectionError("down")):
    check("intervals: exception → lege lijst", intervals.activiteiten_tussen("2026-06-11", "2026-06-11") == [])
with mock.patch.object(intervals.requests, "get", return_value=FakeResp({"raar": True})):
    check("intervals: niet-lijst antwoord → lege lijst", intervals.activiteiten_tussen("2026-06-11", "2026-06-11") == [])

# ── 2. process_food ───────────────────────────────────────────────────────────
import process_food

check("process_food: SPORT_COMPENSATIE uit config", process_food.SPORT_COMPENSATIE == 1.0)

# fetch_sport_today: API geeft vandaag+gisteren; alles naar sheets, alleen vandaag telt
posted = []
def fake_post_ok(url, json=None, timeout=None, allow_redirects=None, **kw):
    posted.append(json)
    return FakeResp({"status": "ok"})

vandaag_str = "2026-06-11"
with mock.patch.object(intervals.requests, "get", return_value=FakeResp(VOORBEELD_API)), \
     mock.patch.object(process_food.requests, "post", side_effect=fake_post_ok):
    acts, kcal = process_food.fetch_sport_today(vandaag_str)
    check("process_food: alleen vandaag in resultaat", len(acts) == 2 and kcal == 897, f"{len(acts)} acts, {kcal} kcal")
    check("process_food: sport-payload bevat 3 activiteiten (incl. gisteren)",
          len(posted) == 1 and posted[0]["type"] == "sport" and len(posted[0]["activiteiten"]) == 3)

# fetch_sport_today met API down → leeg, geen post, geen exception
posted.clear()
with mock.patch.object(intervals.requests, "get", side_effect=ConnectionError("down")), \
     mock.patch.object(process_food.requests, "post", side_effect=fake_post_ok):
    acts, kcal = process_food.fetch_sport_today(vandaag_str)
    check("process_food: API down → (lege lijst, 0) zonder post", acts == [] and kcal == 0 and posted == [])

# analyze_food: sportcontext in prompt + dynamisch doel
captured_prompts = []
def fake_groq_create(**kwargs):
    captured_prompts.append(kwargs["messages"][0]["content"])
    resp = types.SimpleNamespace()
    resp.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps({
        "ontbijt": {"kcal": 500, "omschrijving": "havermout"},
        "lunch": {"kcal": 800, "omschrijving": "broodjes"},
        "avondeten": {"kcal": 1200, "omschrijving": "pasta"},
        "snacks": {"kcal": 300, "omschrijving": "noten"},
        "calories": 2800, "eiwitten": 150, "koolhydraten": 320,
        "vetten": 85, "vezels": 30, "score": 8, "notitie": "prima dag"
    })))]
    return resp

with mock.patch.object(process_food.groq_client.chat.completions, "create", side_effect=fake_groq_create):
    data = process_food.analyze_food("ontbijt: havermout", 600, "Ride 92 min")
    p = captured_prompts[-1]
    check("process_food: prompt bevat sport-kcal", "600 kcal verbrand" in p)
    check("process_food: prompt bevat dynamisch doel 3350", "3350 kcal" in p)
    check("process_food: analyse-resultaat ok", data["calories"] == 2800)

captured_prompts.clear()
with mock.patch.object(process_food.groq_client.chat.completions, "create", side_effect=fake_groq_create):
    process_food.analyze_food("ontbijt: havermout")  # zonder sport
    check("process_food: zonder sport geen sportcontext", "verbrand" not in captured_prompts[-1])

# volledige main(): gemockte telegram + sheets + intervals via ÉÉN router
# (process_food.requests en intervals.requests zijn hetzelfde module-object!)
class GetRouter:
    """Routeert alle requests.get-calls: Telegram, intervals.icu en Apps Script doGet."""
    def __init__(self, updates, intervals_data=None, intervals_error=None):
        self.updates = updates
        self.updates_served = False
        self.intervals_data = intervals_data if intervals_data is not None else []
        self.intervals_error = intervals_error
    def __call__(self, url, timeout=None, params=None, allow_redirects=None, auth=None, **kw):
        if "intervals.icu" in url:
            if self.intervals_error:
                raise self.intervals_error
            return FakeResp(self.intervals_data)
        if "getUpdates" in url:
            if self.updates_served:
                return FakeResp({"result": []})
            self.updates_served = True
            return FakeResp({"result": self.updates})
        return FakeResp([])  # Apps Script doGet (streak, gewicht-check)

sent_messages = []
saved_payloads = []
def fake_post_all(url, json=None, data=None, files=None, timeout=None, allow_redirects=None, **kw):
    if "sendMessage" in url:
        sent_messages.append(json["text"])
        return FakeResp({"ok": True})
    saved_payloads.append(json)
    return FakeResp({"status": "ok"})

router = GetRouter(
    updates=[{"update_id": 1, "message": {"from": {"id": 123, "is_bot": False},
              "date": datetime.datetime.now().timestamp(),
              "text": "ontbijt: havermout met banaan"}}],
    intervals_data=VOORBEELD_API,
)

with mock.patch.object(process_food.requests, "get", side_effect=router), \
     mock.patch.object(process_food.requests, "post", side_effect=fake_post_all), \
     mock.patch.object(process_food.groq_client.chat.completions, "create", side_effect=fake_groq_create), \
     mock.patch.object(process_food, "save_last_update_id", lambda x: None), \
     mock.patch.object(process_food.datetime, "datetime", wraps=datetime.datetime) as fake_dt:
    fake_dt.now = lambda tz=None: datetime.datetime(2026, 6, 11, 23, 58, tzinfo=tz) if tz else datetime.datetime(2026, 6, 11, 23, 58)
    fake_dt.strptime = datetime.datetime.strptime
    process_food.main()

overzicht = [m for m in sent_messages if "Voedingsoverzicht" in m]
check("main: overzicht verstuurd", len(overzicht) == 1)
if overzicht:
    o = overzicht[0]
    check("main: 🚴-blok aanwezig", "🚴 Sport: *897 kcal*" in o, o[:400])
    check("main: dagdoel-regel klopt", "2750 + 897 = *3647 kcal*" in o, o[:400])
maaltijd_saves = [p for p in saved_payloads if p and p.get("type") is None and "calories" in p]
sport_saves    = [p for p in saved_payloads if p and p.get("type") == "sport"]
check("main: maaltijdrij bevat sport_kcal", len(maaltijd_saves) == 1 and maaltijd_saves[0]["sport_kcal"] == 897)
check("main: sport-activiteiten gepost", len(sport_saves) == 1 and len(sport_saves[0]["activiteiten"]) == 3)

# main() zonder maaltijden maar mét sport
sent_messages.clear(); saved_payloads.clear()
router2 = GetRouter(updates=[], intervals_data=VOORBEELD_API)
with mock.patch.object(process_food.requests, "get", side_effect=router2), \
     mock.patch.object(process_food.requests, "post", side_effect=fake_post_all), \
     mock.patch.object(process_food.datetime, "datetime", wraps=datetime.datetime) as fake_dt2:
    fake_dt2.now = lambda tz=None: datetime.datetime(2026, 6, 11, 23, 58, tzinfo=tz) if tz else datetime.datetime(2026, 6, 11, 23, 58)
    fake_dt2.strptime = datetime.datetime.strptime
    process_food.main()
check("main zonder eten: sport tóch gelogd", any(p.get("type") == "sport" for p in saved_payloads if p))
check("main zonder eten: melding bevat sport", any("Wel gesport" in m for m in sent_messages))

# ── 3. tips ───────────────────────────────────────────────────────────────────
import tips
check("tips: SPORT_COMPENSATIE", tips.SPORT_COMPENSATIE == 1.0)
captured_prompts.clear()
with mock.patch.object(tips.groq_client.chat.completions, "create", side_effect=lambda **kw: (
        captured_prompts.append(kw["messages"][0]["content"]),
        types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
            content=json.dumps({"kcal_gegeten": 1500, "eiwitten": 80, "koolhydraten": 150,
                                "vetten": 50, "vezels": 15, "maaltijden_samenvatting": "x", "aanbevelingen": ["y"]})))])
    )[1]):
    tips.analyze_partial_day("lunch: brood", 600, "Ride 92 min")
    check("tips: sportcontext in prompt", "3350 kcal" in captured_prompts[-1])

# ── 4. remind ─────────────────────────────────────────────────────────────────
import remind
msg = remind.build_smart_message(
    ["lunch: broodjes"],
    [{"id": "i111", "datum": "2026-06-11", "naam": "Ochtendrit", "type": "Ride",
      "duur_min": 92, "afstand_km": 45.2, "kcal": 612, "gem_hs": 148}],
    612,
)
check("remind: sportregel in slim bericht", "🚴 Gesport: *612 kcal*" in msg, msg[:300])
check("remind: dynamisch doel 3362", "3362" in msg, msg[:300])

# remind: intervals down → main valt niet om (sport leeg, generieke herinnering)
remind_sent = []
def remind_router(url, *a, **kw):
    if "intervals.icu" in url:
        raise ConnectionError("down")
    return FakeResp({"result": []})
with mock.patch.object(remind.requests, "get", side_effect=remind_router), \
     mock.patch.object(remind.requests, "post",
                       side_effect=lambda url, json=None, **kw: (remind_sent.append(json["text"]), FakeResp({"ok": True}))[1]):
    remind.main()
check("remind: main draait met intervals down", len(remind_sent) == 1 and "Calorie Tracker" in remind_sent[0])

# ── 5. weekly_summary ─────────────────────────────────────────────────────────
import weekly_summary as ws
check("weekly: SPORT_COMPENSATIE", ws.SPORT_COMPENSATIE == 1.0)

vandaag = datetime.date(2026, 6, 11)
maaltijden_rows = [{"datum": (vandaag - datetime.timedelta(days=i)).isoformat(), "calories": 2700,
                    "eiwitten": 140, "koolhydraten": 300, "vetten": 80, "vezels": 25,
                    "score": 8, "notities": "", "ontbijt_kcal": 500, "lunch_kcal": 700,
                    "avondeten_kcal": 1200, "snacks_kcal": 300} for i in range(1, 15)][::-1]
gewicht_rows = [{"datum": (vandaag - datetime.timedelta(days=i)).isoformat(), "gewicht": 75 + i * 0.05}
                for i in range(1, 20)][::-1]
sport_rows = [
    {"datum": (vandaag - datetime.timedelta(days=2)).isoformat(), "kcal": 612, "type": "Ride", "id": "i1"},
    {"datum": (vandaag - datetime.timedelta(days=2)).isoformat(), "kcal": 285, "type": "Run", "id": "i2"},
    {"datum": (vandaag - datetime.timedelta(days=5)).isoformat(), "kcal": 553, "type": "Ride", "id": "i3"},
]

def fake_ws_fetch(data_type, limit):
    return {"maaltijden": maaltijden_rows, "gewicht": gewicht_rows, "sport": sport_rows}[data_type]

ws_messages = []

class WSFakeDT(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 11, 8, 0, tzinfo=tz)

with mock.patch.object(ws, "fetch_data", side_effect=fake_ws_fetch), \
     mock.patch.object(ws, "send_message", side_effect=lambda t: ws_messages.append(t)), \
     mock.patch.object(ws.datetime, "datetime", WSFakeDT), \
     mock.patch.object(ws.groq_client.chat.completions, "create",
                       side_effect=lambda **kw: types.SimpleNamespace(choices=[types.SimpleNamespace(
                           message=types.SimpleNamespace(content="Goed bezig!"))])):
    ws.main()
check("weekly: bericht verstuurd", len(ws_messages) == 1)
if ws_messages:
    w = ws_messages[0]
    check("weekly: sportblok", "🚴 *Sport deze week:*" in w, w[:600])
    check("weekly: 3 activiteiten op 2 dagen", "3 activiteiten op 2 dagen" in w, w)
    check("weekly: totaal verbrand", "1450 kcal verbrand" in w, w)
    # gem dagdoel: 7 gelogde dagen, sport op 2 daarvan (897+553)/7 = 207 → 2957
    check("weekly: dynamisch doel in doelblok", "2957" in w, w)

# zonder sport-data (oude Apps Script → lege lijst): geen sportblok, doel = 2750
ws_messages.clear()
with mock.patch.object(ws, "fetch_data", side_effect=lambda t, l: {"maaltijden": maaltijden_rows, "gewicht": gewicht_rows, "sport": []}[t]), \
     mock.patch.object(ws, "send_message", side_effect=lambda t: ws_messages.append(t)), \
     mock.patch.object(ws.datetime, "datetime", WSFakeDT), \
     mock.patch.object(ws.groq_client.chat.completions, "create",
                       side_effect=lambda **kw: types.SimpleNamespace(choices=[types.SimpleNamespace(
                           message=types.SimpleNamespace(content="Top!"))])):
    ws.main()
check("weekly: zonder sport geen sportblok", "🚴" not in ws_messages[0] and "(2750 kcal)" in ws_messages[0], ws_messages[0][:400])

# ── 6. monthly_report ─────────────────────────────────────────────────────────
import monthly_report as mr
check("monthly: SPORT_COMPENSATIE", mr.SPORT_COMPENSATIE == 1.0)
mr_maaltijden = [{"datum": f"2026-05-{d:02d}", "calories": 2600 + d * 10, "eiwitten": 140, "score": 8,
                  "ontbijt_kcal": 500, "lunch_kcal": 700, "avondeten_kcal": 1100, "snacks_kcal": 300}
                 for d in range(1, 26)]
mr_gewicht = [{"datum": f"2026-05-{d:02d}", "gewicht": 74 + d * 0.02} for d in range(1, 31)]
mr_sport = [{"datum": "2026-05-04", "kcal": 612, "id": "a"}, {"datum": "2026-05-11", "kcal": 540, "id": "b"},
            {"datum": "2026-05-11", "kcal": 200, "id": "c"}]

mr_sent = {"caption": None, "photo": False}
def fake_mr_fetch(t, l):
    return {"maaltijden": mr_maaltijden, "gewicht": mr_gewicht, "sport": mr_sport}[t]
def fake_send_photo(png, caption):
    mr_sent["photo"] = len(png) > 1000
    mr_sent["caption"] = caption
    return True

class MRFakeDT(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 1, 8, 30, tzinfo=tz)

with mock.patch.object(mr, "fetch_data", side_effect=fake_mr_fetch), \
     mock.patch.object(mr, "send_photo", side_effect=fake_send_photo), \
     mock.patch.object(mr, "groq_reflectie", return_value="Mooie maand."), \
     mock.patch.object(mr.datetime, "datetime", MRFakeDT):
    mr.main()
check("monthly: grafiek gemaakt (png)", mr_sent["photo"])
if mr_sent["caption"]:
    c = mr_sent["caption"]
    check("monthly: sportregel in caption", "🚴 3 activiteiten op 2 dagen — 1352 kcal verbrand" in c, c)

print()
if FOUTEN:
    print(f"❌ {len(FOUTEN)} test(s) gefaald: {FOUTEN}")
    sys.exit(1)
print("✅ Alle tests geslaagd")
