# Deploying for free: Netlify + Render + MotherDuck (story #195)

```
browser ──https──► Netlify (the built frontend, free)
                     │  /api/*  is forwarded (proxy)
                     ▼
                   Render (the API, free; code only, built from the private GitHub.com repo)
                     │  DuckDB over the internet
                     ▼
                   MotherDuck (the warehouse + saved suggestions, free)
```

- Netlify forwards `/api/*` to Render, so the browser only talks to the Netlify address: sign-in
  cookies work in every browser and no CORS setup is needed (docs/decisions.md section 16).
- The data is in MotherDuck, so the API image holds code and config only. MotherDuck supports
  DuckDB up to **1.5.6** while the project uses 2.0: the API image pins 1.5.6, and the upload
  converts the warehouse through Parquet and checks the API on 1.5.6 first (section 17).
- **Never uploaded or committed:** `.env`, `data/` (raw, bronze, warehouse, users, app.duckdb).
  The MotherDuck token, the Gemini key and the users' password hashes are Render variables.

**Free plans (checked 2026-11-21):**

| Service | Free plan | What it means here |
|---|---|---|
| MotherDuck | $0, no card, 10 GB storage, 10 h compute a month | The ~200 MB warehouse fits; queries are short |
| Render | $0, about 512 MB, sleeps after 15 idle minutes, 750 h a month, no disk | The first visit after a sleep takes about a minute, and everyone signs in again (sessions are kept in memory) |
| Netlify | $0 | Enough |

## Once: the private GitHub.com repo

The company GitHub stays the main repo. The private GitHub.com repo only feeds Render.

1. Check that nothing private is tracked (no data, `.env` or database files):

   ```powershell
   uv run pytest tests/unit/test_deploy.py -k tracked
   ```

2. Add it as a second remote and push `main` (use your repo's address):

   ```powershell
   git remote add github https://github.com/<you>/<repo>.git
   git push github main
   ```

   Push again (`git push github main`) whenever you want Render to get the latest code.

## 1. The data to MotherDuck

1. In MotherDuck, open **Settings > Access tokens**, create a token, and add one line to your `.env`
   (git-ignored; never paste the token anywhere else):

   ```
   MOTHERDUCK_TOKEN=<your token>
   ```

2. Upload the warehouse. It first checks the API on DuckDB 1.5.6 and uploads only if that passes
   (about 2 minutes; the first run downloads DuckDB 1.5.6):

   ```powershell
   uv run python deploy/upload_warehouse.py
   ```

   It replaces the `revint` database in MotherDuck and creates `revint_app` (saved suggestions)
   when missing. `--check` runs the check without uploading.

## 2. The API on Render

1. In Render: **New > Blueprint**, connect your GitHub.com account, pick the private repo. Render
   reads `render.yaml` and proposes the free web service `revenue-intelligence-api`.
2. Enter the three secret values Render asks for:
   - `MOTHERDUCK_TOKEN`: the same token as in `.env`;
   - `GEMINI_API_KEY`: the same key as in `.env`;
   - `REVINT_USERS_JSON`: your users on one line. Create users locally first
     (`uv run revint user add <name>`), then print the line with:

     ```powershell
     uv run python -c "import json; print(json.dumps(json.load(open('data/users.json'))))"
     ```

     It holds only password hashes, never the passwords.
3. Click **Apply**. The first build takes a few minutes. Render shows the address, like
   `https://revenue-intelligence-api.onrender.com`.
4. Check in a browser (the first request may take a minute while it wakes):
   - `https://<render-address>/api/v1/health` shows `"status": "ready"`;
   - `https://<render-address>/api/v1/overview` answers `not_signed_in` (the data is protected).

## 3. The frontend on Netlify

1. Build it with your Render address (no path, no trailing slash):

   ```powershell
   cd frontend
   npm run build:netlify -- https://<render-address>
   ```

2. Open https://app.netlify.com/drop and drag the `frontend/dist` folder onto the page. Netlify
   gives you an address like `https://<name>.netlify.app`.
3. Open it, sign in, and check Overview, the Explorer, an opportunity and **Get suggestions**.
   Reload an opportunity page: it must not show a 404.

## Updating

| What changed | Do this |
|---|---|
| Code | `git push github main`; Render rebuilds by itself |
| Data | `uv run revint build all` and `uv run revint opportunities build` locally, then `uv run python deploy/upload_warehouse.py` |
| Frontend | `npm run build:netlify -- https://<render-address>`, then in Netlify open the site's **Deploys** tab and drag `dist` there |
| Users | `uv run revint user add/remove <name>` locally, then paste the new one-line JSON into `REVINT_USERS_JSON` on Render; it restarts |

## Troubleshooting

- **The page loads but sign-in says it cannot reach its server:** Render is asleep or still
  building; open `https://<render-address>/api/v1/health`, wait a minute, and try again. If it
  stays down, check the address in `frontend/dist/_redirects` and rebuild the frontend.
- **Render logs say "no MOTHERDUCK_TOKEN" or the health shows not ready:** set the token on Render
  and run the upload again.
- **The upload stops with "the API check on duckdb 1.5.6 failed":** something in the API does not
  work on the DuckDB version MotherDuck runs; nothing was uploaded. Send the printed lines to the
  developer.
- **Suggestions fail:** check `GEMINI_API_KEY` on Render; the daily limit (`ai.daily_call_limit`)
  also applies online.
