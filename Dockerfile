# The API image for Render (story #195). Render builds it from the private GitHub.com repo.
# It holds the code and the config only: the data is in MotherDuck (database.* in
# config/settings.production.yaml), so no warehouse file is in the image.
FROM python:3.12-slim

# MotherDuck supports DuckDB up to this version (deploy/md_import.py MOTHERDUCK_DUCKDB);
# the project itself uses DuckDB 2.0 locally.
ARG MOTHERDUCK_DUCKDB=1.5.6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    REVINT_SETTINGS_OVERLAY=config/settings.production.yaml \
    REVINT_PATHS_USERS=/tmp/revint/users.json \
    HOME=/home/revint

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv

WORKDIR /app
# dependencies first, from the lock file only, so code changes reuse this layer
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-dev \
    && uv pip install --python /app/.venv/bin/python "duckdb==${MOTHERDUCK_DUCKDB}"
COPY deploy/entrypoint.sh ./deploy/entrypoint.sh

# a non-root user; DuckDB keeps its MotherDuck extension in the home folder
RUN useradd --create-home --uid 10001 revint \
    && chown -R revint:revint /home/revint \
    && chmod 0555 /app/deploy/entrypoint.sh
USER revint
# install the MotherDuck extension now, for this DuckDB and this user, so the service never
# downloads it at start-up (story #197: the runtime download failed on Render)
RUN /app/.venv/bin/python -c "import duckdb; duckdb.connect().execute('INSTALL motherduck')"

ENV PATH="/app/.venv/bin:$PATH"
CMD ["sh", "/app/deploy/entrypoint.sh"]
