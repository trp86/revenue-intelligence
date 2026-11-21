#!/bin/sh
# Start the API on Render (story #195).
# The users file comes from the REVINT_USERS_JSON variable (the hashes from data/users.json,
# never plain passwords). Render free has no disk, so it is written to a temporary folder on
# every start; the data itself is in MotherDuck. Then the API serves on $PORT.
set -eu

mkdir -p "$(dirname "$REVINT_PATHS_USERS")"
if [ -n "${REVINT_USERS_JSON:-}" ]; then
  umask 077
  printf "%s" "$REVINT_USERS_JSON" > "$REVINT_PATHS_USERS"
fi
if [ ! -s "$REVINT_PATHS_USERS" ]; then
  echo "no users: set REVINT_USERS_JSON (see docs/deploy.md); nobody can sign in" >&2
fi
if [ -z "${MOTHERDUCK_TOKEN:-}" ]; then
  echo "no MOTHERDUCK_TOKEN: the API cannot reach its data (see docs/deploy.md)" >&2
fi

exec revint serve --host 0.0.0.0 --port "${PORT:-10000}"
