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

COPY backend/requirements-test.txt ./requirements-test.txt
RUN pip install --no-cache-dir --requirement requirements-test.txt
COPY backend/tests ./tests
COPY backend/pytest.ini ./pytest.ini
COPY scripts/test.sh ./scripts/test.sh

FROM runtime AS production
