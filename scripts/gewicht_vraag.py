import os
import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])

resp = requests.post(
 f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
 json={
 "chat_id": CHAT_ID,
 "text": (
 "*Goedemorgen Marti!*\n\n"
 "Wat is je gewicht vandaag?\n"
 "Stuur gewoon een getal, bv: `72.5`"
 ),
 "parse_mode": "Markdown",
 },
 timeout=10,
)

if resp.ok:
 print("Gewichtsvraag verstuurd!")
else:
 print(f"Fout: {resp.status_code} — {resp.text}")
 exit(1)
