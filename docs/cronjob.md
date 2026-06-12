# cron-job.org Setup

GitHub Actions' built-in `schedule` is unreliable (can be delayed by 15–30 minutes). cron-job.org triggers workflows at exact times by calling the GitHub API directly.

## 1. Create a GitHub Personal Access Token (PAT)

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens).
2. Click **Generate new token (classic)**.
3. Give it a name (e.g. `cron-job-calorie-bot`).
4. Set expiration as needed (or no expiration).
5. Under **Scopes**, check **workflow**.
6. Click **Generate token** and copy it immediately.

## 2. Create an account on cron-job.org

Go to [cron-job.org](https://cron-job.org) and create a free account.

## 3. Create a job for each workflow

For each row in the table below, create one job in cron-job.org.

**Settings that are the same for every job:**

- **Request method**: POST
- **Request body**: `{"ref": "main"}`
- **Headers**:
  ```
  Authorization: Bearer YOUR_GITHUB_PAT
  Content-Type: application/json
  Accept: application/vnd.github+json
  ```
- **Timezone**: Europe/Brussels
- **Expected status code**: 204

**Per-job settings:**

| Workflow | URL | Schedule |
|---|---|---|
| Gewichtsvraag | `.../gewicht-vraag.yml/dispatches` | Daily at 07:00 |
| Gewicht check | `.../gewicht-check.yml/dispatches` | Daily at 15:00 |
| Herinnering | `.../herinnering.yml/dispatches` | Daily at 21:00 |
| Verwerking | `.../verwerking.yml/dispatches` | Daily at **23:58** |
| Wekelijks overzicht | `.../weekly-samenvatting.yaml/dispatches` | Monday at 08:00 |
| Maandrapport | `.../monthly-rapport.yml/dispatches` | 1st of the month at 08:30 |
| Tips check | `.../tips-check.yml/dispatches` | Every 10 min staggered: `9,19,29,39,49,59 * * * *` |
| Recept check | `.../recept-check.yml/dispatches` | Every 30 min staggered: `5,35 * * * *` |

> **Why 23:58 and not 00:00?** The daily processing must run *before* midnight: the script stamps the row with the current date, and Telegram only keeps unconfirmed messages for 24 hours. Running at 23:58 keeps the date correct and the message window safely inside that limit.

**Full URL base** (replace `...` above):
```
https://api.github.com/repos/MartiGeudens/calorie-bot/actions/workflows
```

Example full URL for gewicht-vraag:
```
https://api.github.com/repos/MartiGeudens/calorie-bot/actions/workflows/gewicht-vraag.yml/dispatches
```

## 4. Verify a job

After saving a job, click **Run now**. The response should be HTTP **204**. If you get 401, the PAT is wrong or missing the `workflow` scope. If you get 404, double-check the workflow filename.

## Notes

- The Tips check and Recept check run frequently. This is fine — GitHub Actions minutes are free for public repositories.
- The staggered timing for recept-check (`5,35`) prevents it from running at the exact same minute as tips-check.
- If you rename a workflow file, update the URL in cron-job.org to match.
