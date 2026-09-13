FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH"
WORKDIR /app

RUN groupadd --gid 10001 agentos \
    && useradd --uid 10001 --gid agentos --create-home --shell /usr/sbin/nologin agentos \
    && mkdir -p /app/.agentos \
    && chown -R agentos:agentos /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/src /app/src
COPY --from=builder /build/README.md /app/README.md
COPY .env.example /app/.env.example

USER agentos
EXPOSE 8000
VOLUME ["/app/.agentos"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"

CMD ["python", "-m", "agentos", "serve", "--host", "0.0.0.0", "--port", "8000"]
