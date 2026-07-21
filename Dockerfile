FROM python:3.12-alpine3.24

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --gid 10001 --system app \
    && adduser --uid 10001 --system --disabled-password --no-create-home \
        --ingroup app app

COPY requirements.lock ./

RUN python -m pip install --no-cache-dir --requirement requirements.lock

COPY pyproject.toml README.md ./
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./

USER app:app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
