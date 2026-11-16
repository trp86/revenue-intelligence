# revenue-intelligence

Revenue intelligence POC for sales managers.

## Start the app

1. `uv sync` and, once, `cd frontend; npm install`.
2. Create a user who can sign in (story #191). The password is asked for and never shown:

   ```powershell
   uv run revint user add <name>
   ```

   Users are kept in `data/users.json` (git-ignored). `uv run revint user list` shows the names and
   `uv run revint user remove <name>` removes one. Without a user nobody can sign in.
3. Start the API and the frontend: `uv run revint serve`, and `cd frontend; npm run dev`.
   Open http://localhost:5173 and sign in.
