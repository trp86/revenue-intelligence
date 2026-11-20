# The API image for Railway (story #193). Railway builds it from the folder that
# `uv run python deploy/stage.py` prepares; Docker is not needed on the laptop.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    REVINT_SETTINGS_OVERLAY=config/settings.production.yaml \
    REVINT_PATHS_WAREHOUSE=/app/data/warehouse.duckdb \
    REVINT_PATHS_APP_DB=/data/app.duckdb \
    REVINT_PATHS_USERS=/data/users.json

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv

WORKDIR /app
# dependencies first, from the lock file only, so code changes reuse this layer
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-dev
COPY data/warehouse.duckdb ./data/warehouse.duckdb
COPY deploy/entrypoint.sh ./deploy/entrypoint.sh

# a non-root user; /data is the Railway volume (app.duckdb and the users file)
RUN useradd --create-home --uid 10001 revint \
    && mkdir -p /data \
    && chown -R revint:revint /data \
    && chmod 0555 /app/deploy/entrypoint.sh
USER revint

ENV PATH="/app/.venv/bin:$PATH"
CMD ["sh", "/app/deploy/entrypoint.sh"]
