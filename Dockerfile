# BoloSIP container image (Doc/deployment-plan.md §4). Used by Railway and by the
# `docker` CI job. Python 3.12 (the embedding packages' tested version), the embed extra,
# and the embedding model baked into the image so a restart never downloads it.
#
#   docker build -t bolosip .
#   docker run --rm -p 8000:8000 -v bolosip-data:/data bolosip
#
# Facts-only. No investment advice.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BOLOSIP_SKIP_DOTENV=1 \
    BOLOSIP_HOST=:: \
    PORT=8000 \
    BOLOSIP_RETRIEVER=embed \
    BOLOSIP_LLM=off \
    BOLOSIP_MODEL_CACHE=/app/.cache/models \
    BOLOSIP_DB=/data/bolosip.sqlite3 \
    BOLOSIP_CHROMA_DIR=/data/chroma

WORKDIR /app

# 1. Dependencies: only re-run when pyproject.toml (or the version) changes.
COPY pyproject.toml README.md ./
COPY bolosip/__init__.py bolosip/__init__.py
RUN pip install --no-cache-dir ".[embed]"

# 2. The embedding model (about 550 MB), downloaded once per dependency change.
COPY bolosip/ bolosip/
RUN python -c "import sys; from bolosip import embedder; sys.exit(0 if embedder.load(allow_download=True) else 1)"

# 3. Code and data (changes daily with the refresh commit).
COPY . .
RUN useradd --system --uid 10001 --home-dir /app app \
    && chmod 0755 scripts/docker-entrypoint.sh \
    && chown -R app:app /app/.cache

EXPOSE 8000
# The entrypoint makes /data writable for `app` (Railway mounts volumes as root), then
# drops root. `python server.py` runs as PID 1, so it gets SIGTERM on every redeploy.
ENTRYPOINT ["scripts/docker-entrypoint.sh"]
CMD ["python", "server.py"]
