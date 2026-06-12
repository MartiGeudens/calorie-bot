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
            if "/wellness" in url:
                return FakeResp(getattr(self, "wellness_data", []))
            if "/events" in url:
                return FakeResp(getattr(self, "events_data", []))
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
     mock.patch.object(ws, "wellness_tussen", return_value=[]), \
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
     mock.patch.object(ws, "wellness_tussen", return_value=[]), \
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
     mock.patch.object(mr, "wellness_tussen", return_value=[]), \
     mock.patch.object(mr, "send_photo", side_effect=fake_send_photo), \
     mock.patch.object(mr, "groq_reflectie", return_value="Mooie maand."), \
     mock.patch.object(mr.datetime, "datetime", MRFakeDT):
    mr.main()
check("monthly: grafiek gemaakt (png)", mr_sent["photo"])
if mr_sent["caption"]:
    c = mr_sent["caption"]
    check("monthly: sportregel in caption", "🚴 3 activiteiten op 2 dagen — 1352 kcal verbrand" in c, c)

# ════════════════════════════════════════════════════════════════════════════
# FASE 2 — wellness, herstel-alert, eiwitdoel, carb-advies, correlaties
# ════════════════════════════════════════════════════════════════════════════

WELLNESS_API = [
    {"id": "2026-06-11", "hrv": 62, "restingHR": 48, "sleepSecs": 26280, "sleepScore": 81, "readiness": 75},
    {"id": "2026-06-12", "hrv": 58.4, "restingHR": 50, "sleepSecs": 24480, "sleepScore": 72, "readiness": None},
    {"id": "2026-06-10", "hrv": None, "restingHR": None, "sleepSecs": None, "sleepScore": None, "readiness": None},
]

# ── intervals: wellness-parsing ───────────────────────────────────────────────
with mock.patch.object(intervals.requests, "get", return_value=FakeResp(WELLNESS_API)):
    wrecs = intervals.wellness_tussen("2026-06-10", "2026-06-12")
    check("wellness: 3 records, gesorteerd", len(wrecs) == 3 and wrecs[0]["datum"] == "2026-06-10")
    w11 = next(r for r in wrecs if r["datum"] == "2026-06-11")
    check("wellness: velden geparsed", w11["hrv"] == 62 and w11["rhr"] == 48 and w11["slaap_u"] == 7.3 and w11["slaapscore"] == 81)
    w10 = next(r for r in wrecs if r["datum"] == "2026-06-10")
    check("wellness: lege dag → None-velden", all(w10[k] is None for k in ("hrv", "rhr", "slaap_u", "slaapscore", "readiness")))
    wv = intervals.wellness_van("2026-06-12")
    check("wellness: wellness_van pakt juiste dag", wv and wv["hrv"] == 58.4)
regel = intervals.wellness_regel({"hrv": 58.4, "rhr": 50, "slaap_u": 6.8, "slaapscore": 72})
check("wellness: regel-formattering", regel == "HRV 58 · RHR 50 · 6.8u slaap (score 72)", regel)
check("wellness: lege regel", intervals.wellness_regel(None) == "")

# ── intervals: trainingsload ──────────────────────────────────────────────────
LOAD_API = [{"id": "iL1", "start_date_local": "2026-06-12T08:30:00", "type": "Ride", "name": "Rit",
             "moving_time": 4416, "distance": 28766, "calories": 824, "average_heartrate": 148,
             "icu_training_load": 130}]
with mock.patch.object(intervals.requests, "get", return_value=FakeResp(LOAD_API)):
    lacts = intervals.activiteiten_van("2026-06-12")
    check("load: icu_training_load geparsed", lacts[0]["load"] == 130)
    check("load: sport_load_totaal", intervals.sport_load_totaal(lacts) == 130)

# ── intervals: herstel-alert ──────────────────────────────────────────────────
import datetime as _dt
def _mk_wellness(vandaag, hrv_per_offset, rhr_per_offset):
    out = []
    for off, hrv in hrv_per_offset.items():
        d = (_dt.date.fromisoformat(vandaag) - _dt.timedelta(days=off)).isoformat()
        out.append({"datum": d, "hrv": hrv, "rhr": rhr_per_offset.get(off), "slaap_u": 7, "slaapscore": 75, "readiness": None})
    return out

VD = "2026-06-12"
basis_hrv = {o: 60 for o in range(3, 10)}
basis_rhr = {o: 48 for o in range(3, 10)}

# vuurt: 3 lage HRV-dagen + verhoogde RHR
recs = _mk_wellness(VD, {**basis_hrv, 0: 50, 1: 51, 2: 49}, {**basis_rhr, 0: 53, 1: 52, 2: 53})
alert = intervals.herstel_alert(recs, VD, 3, 3)
check("alert: vuurt bij 3 lage dagen + hoge RHR", alert is not None and alert["dagen"] == 3, str(alert))
check("alert: baseline klopt", alert and alert["hrv_baseline"] == 60.0, str(alert))

# vuurt niet: RHR normaal
recs = _mk_wellness(VD, {**basis_hrv, 0: 50, 1: 51, 2: 49}, {**basis_rhr, 0: 48, 1: 49, 2: 48})
check("alert: stil bij normale RHR", intervals.herstel_alert(recs, VD, 3, 3) is None)

# vuurt niet: maar 2 lage dagen
recs = _mk_wellness(VD, {**basis_hrv, 0: 50, 1: 51, 2: 61}, {**basis_rhr, 0: 53, 1: 52, 2: 53})
check("alert: stil bij 2/3 lage dagen", intervals.herstel_alert(recs, VD, 3, 3) is None)

# vuurt niet: HRV-gat in recente reeks
recs = _mk_wellness(VD, {**basis_hrv, 0: 50, 2: 49}, {**basis_rhr, 0: 53, 2: 53})
check("alert: stil bij ontbrekende nacht", intervals.herstel_alert(recs, VD, 3, 3) is None)

# vuurt niet: te weinig baseline-dagen
recs = _mk_wellness(VD, {0: 50, 1: 51, 2: 49, 3: 60, 4: 60}, {0: 53, 1: 52, 2: 53, 3: 48, 4: 48})
check("alert: stil bij te korte baseline", intervals.herstel_alert(recs, VD, 3, 3) is None)

# ── intervals: alcohol_contrast ───────────────────────────────────────────────
wel30 = []
for i in range(30):
    d = (_dt.date(2026, 6, 12) - _dt.timedelta(days=i)).isoformat()
    wel30.append({"datum": d, "hrv": 60, "rhr": 48, "slaap_u": 7, "slaapscore": 80, "readiness": None})
# nacht ná alcoholdag: HRV 48, slaapscore 65
maal30 = []
alcohol_offsets = {3, 9, 15, 21}
for i in range(1, 29):
    d = (_dt.date(2026, 6, 12) - _dt.timedelta(days=i)).isoformat()
    if i in alcohol_offsets:
        maal30.append({"datum": d, "maaltijden": "frietjes en 3 pintjes"})
        nacht = (_dt.date.fromisoformat(d) + _dt.timedelta(days=1)).isoformat()
        for r in wel30:
            if r["datum"] == nacht:
                r["hrv"], r["slaapscore"] = 48, 65
    else:
        maal30.append({"datum": d, "maaltijden": "havermout en kip met rijst"})
contrast = intervals.alcohol_contrast(maal30, wel30)
check("contrast: berekend", contrast is not None and contrast["n_alcohol"] == 4, str(contrast))
check("contrast: HRV-verschil = -12", contrast and contrast["d_hrv"] == -12.0, str(contrast))
check("contrast: slaapscore-verschil = -15", contrast and contrast["d_slaapscore"] == -15.0, str(contrast))
check("contrast: None bij <21 nachten", intervals.alcohol_contrast(maal30, wel30[:15]) is None)
geen_alc = [{"datum": r["datum"], "maaltijden": "water en brood"} for r in maal30]
check("contrast: None zonder alcoholdagen", intervals.alcohol_contrast(geen_alc, wel30) is None)
check("contrast: geen vals woord-match ('origineel')",
      not intervals.ALCOHOL_RE.search("origineel gerecht met gember"))
check("contrast: 'pintje' matcht wel", bool(intervals.ALCOHOL_RE.search("twee pintjes gedronken")))

# ── process_food: volledige run met wellness + zware trainingsdag ────────────
check("process_food: wellness-config geladen", process_food.TSS_ZWAAR == 100 and process_food.EIWIT_EXTRA_G == 20)

ACTS_ZWAAR = [{"id": "iZ1", "start_date_local": "2026-06-11T08:30:00", "type": "Ride", "name": "Lange rit",
               "moving_time": 7200, "distance": 60000, "calories": 1200, "average_heartrate": 150,
               "icu_training_load": 130}]
WELLNESS_VANDAAG = [
    {"id": "2026-06-10", "hrv": 61, "restingHR": 49, "sleepSecs": 27000, "sleepScore": 80, "readiness": None},
    {"id": "2026-06-11", "hrv": 58, "restingHR": 50, "sleepSecs": 24480, "sleepScore": 72, "readiness": None},
]
sent_messages.clear(); saved_payloads.clear(); captured_prompts.clear()
router3 = GetRouter(
    updates=[{"update_id": 9, "message": {"from": {"id": 123, "is_bot": False},
              "date": datetime.datetime.now().timestamp(), "text": "lunch: kip met rijst"}}],
    intervals_data=ACTS_ZWAAR,
)
router3.wellness_data = WELLNESS_VANDAAG
with mock.patch.object(process_food.requests, "get", side_effect=router3), \
     mock.patch.object(process_food.requests, "post", side_effect=fake_post_all), \
     mock.patch.object(process_food.groq_client.chat.completions, "create", side_effect=fake_groq_create), \
     mock.patch.object(process_food, "save_last_update_id", lambda x: None), \
     mock.patch.object(process_food.datetime, "datetime", wraps=datetime.datetime) as fdt3:
    fdt3.now = lambda tz=None: datetime.datetime(2026, 6, 11, 23, 58, tzinfo=tz) if tz else datetime.datetime(2026, 6, 11, 23, 58)
    fdt3.strptime = datetime.datetime.strptime
    process_food.main()

p3 = captured_prompts[-1]
check("fase2 main: herstelcontext in prompt", "Herstelstatus vannacht" in p3 and "HRV 58" in p3, p3[-400:])
check("fase2 main: zware dag in prompt", "zware trainingsdag" in p3 and "170g" in p3)
check("fase2 main: eiwitdoel-regel in prompt", "- Eiwitten: 170g" in p3)
wellness_saves = [x for x in saved_payloads if x and x.get("type") == "wellness"]
check("fase2 main: wellness opgeslagen (2 dagen)", len(wellness_saves) == 1 and len(wellness_saves[0]["records"]) == 2, str(wellness_saves))
ov3 = [m for m in sent_messages if "Voedingsoverzicht" in m]
check("fase2 main: eiwitregel in 🚴-blok", ov3 and "eiwitdoel *170g*" in ov3[0], ov3[0][:400] if ov3 else "")

# ── tips: herstel + eiwitdoel in prompt ───────────────────────────────────────
check("tips: wellness-config geladen", tips.TSS_ZWAAR == 100 and tips.EIWIT_EXTRA_G == 20)
captured_prompts.clear()
with mock.patch.object(tips.groq_client.chat.completions, "create", side_effect=lambda **kw: (
        captured_prompts.append(kw["messages"][0]["content"]),
        types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
            content=json.dumps({"kcal_gegeten": 1500, "eiwitten": 80, "koolhydraten": 150,
                                "vetten": 50, "vezels": 15, "maaltijden_samenvatting": "x", "aanbevelingen": ["y"]})))])
    )[1]):
    tips.analyze_partial_day("lunch: brood", 824, "Ride 74 min", "HRV 58 · RHR 50 · 6.8u slaap (score 72)", 130, 170)
    pt = captured_prompts[-1]
    check("tips fase2: herstel in prompt", "Herstelstatus vannacht" in pt)
    check("tips fase2: eiwitdoel 170g in prompt", "- Eiwitten: 170g" in pt and "trainingsload 130" in pt)

# ── remind: carb-advies geplande training ─────────────────────────────────────
with mock.patch.object(remind, "geplande_workouts", return_value=[
        {"naam": "Lange duurrit", "type": "Ride", "duur_min": 150, "load": 140}]):
    regel = remind.morgen_training_regel()
    check("remind: carb-advies bij zware workout", "Lange duurrit" in regel and "koolhydraten" in regel, regel)
with mock.patch.object(remind, "geplande_workouts", return_value=[
        {"naam": "Losrijden", "type": "Ride", "duur_min": 30, "load": 25}]):
    check("remind: stil bij lichte workout", remind.morgen_training_regel() == "")
with mock.patch.object(remind, "geplande_workouts", return_value=[]):
    check("remind: stil zonder kalender", remind.morgen_training_regel() == "")

# ── gewicht_check: herstel-alert om 15:00 ─────────────────────────────────────
import gewicht_check as gc
gc_messages = []

# dag 3: vuurt (gisteren nog niet waar)
recs_d3 = _mk_wellness(VD, {**basis_hrv, 0: 50, 1: 51, 2: 49}, {**basis_rhr, 0: 53, 1: 52, 2: 53})
with mock.patch.object(gc, "wellness_tussen", return_value=recs_d3), \
     mock.patch.object(gc, "send_message", side_effect=lambda t: gc_messages.append(t)):
    gc.check_herstel_alert(VD)
check("gewicht_check: alert verstuurd op dag 3", len(gc_messages) == 1 and "Herstel hapert" in gc_messages[0], str(gc_messages))

# dag 4: conditie gold gisteren ook → geen herhaling
gc_messages.clear()
recs_d4 = _mk_wellness(VD, {**{o: 60 for o in range(4, 11)}, 0: 50, 1: 51, 2: 49, 3: 50},
                       {**{o: 48 for o in range(4, 11)}, 0: 53, 1: 52, 2: 53, 3: 53})
with mock.patch.object(gc, "wellness_tussen", return_value=recs_d4), \
     mock.patch.object(gc, "send_message", side_effect=lambda t: gc_messages.append(t)):
    gc.check_herstel_alert(VD)
check("gewicht_check: geen herhaalbericht op dag 4", gc_messages == [])

# geen data → stil, geen exception
with mock.patch.object(gc, "wellness_tussen", return_value=[]), \
     mock.patch.object(gc, "send_message", side_effect=lambda t: gc_messages.append(t)):
    gc.check_herstel_alert(VD)
check("gewicht_check: stil zonder wellness-data", gc_messages == [])

# ── weekly: herstelblok + correlatie ──────────────────────────────────────────
wel_week = []
for i in range(28):
    d = (datetime.date(2026, 6, 11) - datetime.timedelta(days=i)).isoformat()
    wel_week.append({"datum": d, "hrv": 62 if i >= 7 else 57, "rhr": 48 if i >= 7 else 50,
                     "slaap_u": 7.2, "slaapscore": 78, "readiness": None})
maal_alc = [dict(r) for r in maaltijden_rows]
for r in maal_alc[:4]:
    r["maaltijden"] = "pasta en 2 pintjes"
for r in maal_alc[4:]:
    r["maaltijden"] = r.get("maaltijden") or "gewone dag kip rijst"
# nachten na de 4 alcoholdagen verlagen
for r in maal_alc[:4]:
    nacht = (datetime.date.fromisoformat(r["datum"]) + datetime.timedelta(days=1)).isoformat()
    for w in wel_week:
        if w["datum"] == nacht:
            w["hrv"], w["slaapscore"] = 49, 64

ws_messages.clear()
with mock.patch.object(ws, "fetch_data", side_effect=lambda t, l: {"maaltijden": maal_alc, "gewicht": gewicht_rows, "sport": sport_rows}[t]), \
     mock.patch.object(ws, "wellness_tussen", return_value=wel_week), \
     mock.patch.object(ws, "send_message", side_effect=lambda t: ws_messages.append(t)), \
     mock.patch.object(ws.datetime, "datetime", WSFakeDT), \
     mock.patch.object(ws.groq_client.chat.completions, "create",
                       side_effect=lambda **kw: types.SimpleNamespace(choices=[types.SimpleNamespace(
                           message=types.SimpleNamespace(content="Top!"))])):
    ws.main()
w2 = ws_messages[0]
check("weekly fase2: herstelblok aanwezig", "🫀 *Herstel deze week:*" in w2, w2[:800])
check("weekly fase2: HRV met vorige week", "HRV" in w2 and "vorige week" in w2)
check("weekly fase2: alcohol-correlatie", "🍺 Nacht na alcohol" in w2, w2)

# ── monthly: wellness in grafiek + caption ────────────────────────────────────
wel_mei = [{"datum": f"2026-05-{d:02d}", "hrv": 60, "rhr": 48, "slaap_u": 7.1, "slaapscore": 77, "readiness": None}
           for d in range(1, 31)]
mr_sent["caption"] = None; mr_sent["photo"] = False
with mock.patch.object(mr, "fetch_data", side_effect=fake_mr_fetch), \
     mock.patch.object(mr, "wellness_tussen", return_value=wel_mei), \
     mock.patch.object(mr, "send_photo", side_effect=fake_send_photo), \
     mock.patch.object(mr, "groq_reflectie", return_value="Mooie maand."), \
     mock.patch.object(mr.datetime, "datetime", MRFakeDT):
    mr.main()
check("monthly fase2: grafiek met wellness-panelen", mr_sent["photo"])
check("monthly fase2: wellnessregel in caption", mr_sent["caption"] and "🫀 Gem. HRV 60" in mr_sent["caption"], str(mr_sent["caption"]))

# ── import_wellness: historische backfill ─────────────────────────────────────
import import_wellness as iw

iw_posts = []
def iw_fake_post(url, payload):
    iw_posts.append(payload)
    return True

wel_hist = [{"datum": f"2026-06-{d:02d}", "hrv": 60, "rhr": 48, "slaap_u": 7.0, "slaapscore": 78, "readiness": None}
            for d in range(1, 12)]
wel_hist.append({"datum": "2026-06-12", "hrv": None, "rhr": None, "slaap_u": None, "slaapscore": None, "readiness": None})
act_hist = [{"id": f"h{d}", "datum": f"2026-06-{d:02d}", "naam": "Rit", "type": "Ride",
             "duur_min": 60, "afstand_km": 25.0, "kcal": 500, "gem_hs": 140, "load": 60} for d in (2, 5, 9)]

with mock.patch.object(iw, "wellness_tussen", return_value=wel_hist), \
     mock.patch.object(iw, "activiteiten_tussen", return_value=act_hist), \
     mock.patch.object(iw, "post_naar_sheets", side_effect=iw_fake_post), \
     mock.patch.object(iw.sys, "argv", ["import_wellness.py", "2026-06-01", "2026-06-12"]):
    iw.main()
w_posts = [x for x in iw_posts if x["type"] == "wellness"]
s_posts = [x for x in iw_posts if x["type"] == "sport"]
check("import: wellness gepost (lege dag eruit gefilterd)", len(w_posts) == 1 and len(w_posts[0]["records"]) == 11, str(len(w_posts[0]["records"]) if w_posts else 0))
check("import: sport standaard mee", len(s_posts) == 1 and len(s_posts[0]["activiteiten"]) == 3)

iw_posts.clear()
with mock.patch.object(iw, "wellness_tussen", return_value=wel_hist), \
     mock.patch.object(iw, "activiteiten_tussen", return_value=act_hist) as iw_acts, \
     mock.patch.object(iw, "post_naar_sheets", side_effect=iw_fake_post), \
     mock.patch.object(iw.sys, "argv", ["import_wellness.py", "2026-06-01", "--zonder-sport"]):
    iw.main()
check("import: --zonder-sport slaat sport over", not [x for x in iw_posts if x["type"] == "sport"] and not iw_acts.called)

# batching: 120 records → 3 batches van 50/50/20
iw_posts.clear()
wel_groot = [{"datum": (datetime.date(2026, 1, 1) + datetime.timedelta(days=i)).isoformat(),
              "hrv": 60, "rhr": 48, "slaap_u": 7.0, "slaapscore": 78, "readiness": None} for i in range(120)]
with mock.patch.object(iw, "wellness_tussen", return_value=wel_groot), \
     mock.patch.object(iw, "post_naar_sheets", side_effect=iw_fake_post), \
     mock.patch.object(iw.sys, "argv", ["import_wellness.py", "2026-01-01", "2026-04-30", "--zonder-sport"]):
    iw.main()
check("import: batching 50/50/20", [len(x["records"]) for x in iw_posts] == [50, 50, 20], str([len(x["records"]) for x in iw_posts]))

# foutpaden: ongeldige datum + mislukte batch → SystemExit
import contextlib
with mock.patch.object(iw.sys, "argv", ["import_wellness.py", "01-06-2026"]):
    try:
        iw.main()
        check("import: ongeldige datum → exit", False)
    except SystemExit as e:
        check("import: ongeldige datum → exit", "Ongeldige datum" in str(e))
with mock.patch.object(iw, "wellness_tussen", return_value=wel_hist), \
     mock.patch.object(iw, "post_naar_sheets", return_value=False), \
     mock.patch.object(iw.sys, "argv", ["import_wellness.py", "2026-06-01", "2026-06-12", "--zonder-sport"]):
    try:
        iw.main()
        check("import: mislukte batch → exit met melding", False)
    except SystemExit as e:
        check("import: mislukte batch → exit met melding", "mislukte batch" in str(e))

print()
if FOUTEN:
    print(f"❌ {len(FOUTEN)} test(s) gefaald: {FOUTEN}")
    sys.exit(1)
print("✅ Alle tests geslaagd")
