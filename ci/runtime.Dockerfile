FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update -qq && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock
WORKDIR /app
COPY app ./app
COPY src ./src
COPY bundles ./bundles
RUN mkdir -p /app/events && chown 10001:10001 /app/events
USER 10001:10001
ENV MODEL_DIR=/app/bundles/candidate MONITORING_EVENTS_PATH=/app/events/events.jsonl
HEALTHCHECK --interval=10s --timeout=5s --retries=12 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
