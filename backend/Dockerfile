FROM python:3.12.9-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt

COPY backend/app ./app
COPY alembic.ini ./alembic.ini
COPY database/migrations ./database/migrations

EXPOSE 8000
CMD ["sh", "-c", "python -m app.migrate && exec python -m app.server"]

FROM runtime AS tests

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements-test.txt ./requirements-test.txt
RUN pip install --no-cache-dir --requirement requirements-test.txt
COPY backend/tests ./tests
COPY backend/pytest.ini ./pytest.ini
COPY observability/grafana-cloud-alert /observability/grafana-cloud-alert
COPY scripts/test.sh ./scripts/test.sh
COPY scripts/pipeline.py ./scripts/pipeline.py
COPY scripts/repair_runner.py ./scripts/repair_runner.py
COPY .github/workflows/pipeline.yml ./.github/workflows/pipeline.yml
COPY .github/agents ./.github/agents

FROM runtime AS production
