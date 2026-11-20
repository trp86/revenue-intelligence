# Deploying by hand: the API on Railway, the frontend on Netlify (story #193)

The app goes online in two parts, both uploaded from your laptop:

```
browser ──https──► Netlify (the built frontend)
                     │  /api/*  is forwarded (proxy)
                     ▼
                   Railway (the API: FastAPI + the warehouse + sign-in + Gemini)
```

Netlify forwards `/api/*` to Railway, so the browser only ever talks to the Netlify address. Sign-in
cookies then work in every browser (Safari and Firefox block cookies between two different sites),
and no CORS setup is needed (docs/decisions.md section 16).

**Never uploaded:** `.env`, `data/users.json`, `data/app.duckdb`, the raw and bronze data. The API
upload is an allow-list built by `deploy/stage.py`; the Gemini key and the users are Railway
variables.

**Cost (Railway's pricing page, 2026-11-20); Netlify's free plan is enough:**

| Railway plan | Cost | Memory | Behaviour |
|---|---|---|---|
| Free Trial | $0, one-time $5 credit for 30 days | 1 GB | Always on; stops when the credit or the 30 days run out |
| Free | $0 a month ($1 usage credit) | 0.5 GB | Sleeps after 5 to 10 idle minutes; the next visit wakes it, and everyone signs in again (sessions are in memory) |
| Hobby | $5 a month ($5 usage included) | up to 48 GB | Always on |

Start with the Free Trial to show the app. The Free plan's 0.5 GB may be tight for the API and the
~200 MB warehouse; the Railway logs show it when memory runs out.

## Once: accounts and tools

1. Create a Railway account at https://railway.com and a Netlify account at https://netlify.com.
2. Install the Railway command line tool and sign in (a browser window opens):

   ```powershell
   npm install -g @railway/cli
   railway login
   ```

## 1. Prepare the upload (on your laptop)

1. Make sure the warehouse is built and has the opportunity tables (the app works locally).
2. Create the users who may sign in. The password is asked for and never shown:

   ```powershell
   uv run revint user add <name>
   ```

3. Build the upload folder `deploy/.stage` (about 200 MB; git-ignored):

   ```powershell
   uv run python deploy/stage.py
   ```

## 2. The API on Railway

1. First deploy: creates a project and a service from the upload folder:

   ```powershell
   railway up deploy/.stage --path-as-root --new --name revenue-intelligence
   ```

   Railway finds the `Dockerfile` and builds it. The first build takes a few minutes.
2. In the Railway dashboard, open the service:
   - **Volume:** add a volume with mount path `/data` (it keeps saved suggestions and the users
     file across restarts).
   - **Variables:** add
     - `GEMINI_API_KEY` = your key (the same as in your local `.env`);
     - `REVINT_USERS_JSON` = the contents of `data/users.json` on one line. Print it with:

       ```powershell
       uv run python -c "import json; print(json.dumps(json.load(open('data/users.json'))))"
       ```

       It holds only password hashes, never the passwords.
   - **Networking:** click **Generate Domain**. You get an address like
     `https://revenue-intelligence-production.up.railway.app`.
3. Railway restarts the service with the new settings. Check it in a browser:
   - `https://<railway-address>/api/v1/health` shows `"status": "ready"`;
   - `https://<railway-address>/api/v1/overview` answers `not_signed_in` (the data is protected).

## 3. The frontend on Netlify

1. Build the frontend with your Railway address (no path, no trailing slash):

   ```powershell
   cd frontend
   npm run build:netlify -- https://<railway-address>
   ```

   This writes `frontend/dist`, including `dist/_redirects` with the forwarding rules.
2. Open https://app.netlify.com/drop and drag the `frontend/dist` folder onto the page. Netlify
   gives you an address like `https://<name>.netlify.app`. Optionally rename the site in
   **Site configuration > Change site name**.
3. Open the Netlify address, sign in, and check Overview, the Explorer, an opportunity and
   **Get suggestions**. Reload an opportunity page: it must not show a 404.

## Updating

| What changed | Do this |
|---|---|
| Code or data | `uv run python deploy/stage.py`, then `railway up deploy/.stage --path-as-root` (the project is already linked) |
| Frontend | `npm run build:netlify -- https://<railway-address>`, then in Netlify open the site's **Deploys** tab and drag `dist` there (dragging onto the drop page again would create a second site) |
| Users | `uv run revint user add/remove <name>` locally, then paste the new one-line JSON into `REVINT_USERS_JSON`; Railway restarts the service |

Restarting the API signs everyone out (sessions are kept in memory; docs/decisions.md section 15).

## Troubleshooting

- **The Netlify page loads but sign-in fails with "cannot reach its server":** the API is not
  running or the address in `_redirects` is wrong. Open `https://<railway-address>/api/v1/health`,
  and rebuild the frontend with the right address.
- **"no users" in the Railway logs:** `REVINT_USERS_JSON` is missing or empty.
- **Suggestions fail:** check `GEMINI_API_KEY` in the Railway variables. The daily limit
  (`ai.daily_call_limit`) also applies online.
