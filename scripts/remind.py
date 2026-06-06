import os
import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])

resp = requests.post(
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    json={
        "chat_id": CHAT_ID,
        "text": (
            "*Calorie Tracker* — Goedenavond Marti!\n\n"
            "Wat heb je vandaag gegeten?\n\n"
            "Je kan maaltijden doorheen de dag insturen of alles nu in één keer beschrijven. Alles wat je vandaag gestuurd hebt wordt meegenomen! \n\n"
            "_Ontbijt: havermout met banaan_\n"
            "_Lunch: broodje kaas en tomaat_\n"
            "_Avondeten: pasta bolognese_\n"
            "_Snack: appel en handvol noten_\n\n"
            "Ik analyseer alles automatisch om middernacht! "
        ),
        "parse_mode": "Markdown",
    },
    timeout=10,
)

if resp.ok:
    print("Herinnering verstuurd!")
else:
    print(f"Fout: {resp.status_code} — {resp.text}")
    exit(1)
