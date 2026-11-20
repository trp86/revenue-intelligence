#!/bin/sh
# Start the API on Railway (story #193).
# The users file comes from the REVINT_USERS_JSON variable (the hashes from data/users.json,
# never plain passwords) and is written to the volume; then the API serves on $PORT.
set -eu

if [ -n "${REVINT_USERS_JSON:-}" ]; then
  umask 077
  printf "%s" "$REVINT_USERS_JSON" > "$REVINT_PATHS_USERS"
fi
if [ ! -s "$REVINT_PATHS_USERS" ]; then
  echo "no users: set REVINT_USERS_JSON (see docs/deploy.md); nobody can sign in" >&2
fi

exec revint serve --host 0.0.0.0 --port "${PORT:-8000}"
