# API and worker (same image, different command). Linux wheels exist for every native
# dependency (livekit, ai-coustics, onnxruntime for Silero) on glibc 2.28+, x86_64 and arm64.
FROM python:3.14-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    TTS_CACHE_DIR=/data/tts_cache

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# Mount points exist in the image, owned by the app user: Docker gives a fresh named volume the
# ownership of the directory it is mounted on (a missing one would be owned by root, unwritable).
RUN useradd --system --uid 10001 --create-home app && mkdir -p /data/tts_cache && chown -R app /data
USER app

CMD ["kpi-api"]
