# Telegram Bot Setup

## 1. Create the bot

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot`.
3. Choose a display name (e.g. `Calorie Tracker`).
4. Choose a username ending in `bot` (e.g. `MartiCalorieBot`).
5. BotFather replies with your **bot token** — a string like `123456789:ABCdef...`.

Save this token. You will need it as the `BOT_TOKEN` GitHub secret.

## 2. Get your chat ID

1. Send any message to your new bot.
2. Open this URL in a browser (replace `YOUR_TOKEN`):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
3. In the JSON response, find `"chat": {"id": 123456789}`. That number is your **chat ID**.

Save this number as the `CHAT_ID` GitHub secret.

## 3. Add secrets to GitHub

1. Go to your repository on GitHub.
2. Navigate to **Settings > Secrets and variables > Actions**.
3. Click **New repository secret** for each:

| Name | Value |
|---|---|
| `BOT_TOKEN` | The token from BotFather |
| `CHAT_ID` | Your numeric chat ID |

## 4. Set bot commands (optional)

In BotFather, send `/setcommands`, select your bot, then paste:

```
tips - Calorie budget en aanbevelingen voor vandaag
recept_ai - Recept toevoegen met AI-macro's (naam: ingrediënten)
recept - Recept toevoegen met eigen macro's (naam: ingrediënten | kcal, eiwit, koolh, vet)
```
