# Groq AI Setup

## 1. Create an account

Go to [console.groq.com](https://console.groq.com) and sign up.

## 2. Generate an API key

1. In the Groq console, go to **API Keys**.
2. Click **Create API Key**.
3. Give it a name (e.g. `calorie-bot`).
4. Copy the key — it starts with `gsk_`.

The key is only shown once. Save it immediately.

## 3. Add to GitHub

1. Go to your repository on GitHub.
2. Navigate to **Settings > Secrets and variables > Actions**.
3. Click **New repository secret**:

| Name | Value |
|---|---|
| `GROQ_API_KEY` | Your API key (`gsk_...`) |

## Notes

- The bot uses the `llama-3.3-70b-versatile` model.
- Groq's free tier has generous rate limits. A single daily analysis run uses one request.
- If you hit rate limits, the script retries up to 3 times automatically.
