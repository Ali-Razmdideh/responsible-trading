# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.11

# ---- builder ----------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV"

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---- runtime ----------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 1000 app \
 && useradd  --system --uid 1000 --gid app --home /app --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

COPY --chown=app:app src/ ./src/
COPY --chown=app:app run.py validate.py ./
COPY --chown=app:app trades.json economic_calendar.json risk_model.md ./
COPY --chown=app:app pyproject.toml pytest.ini ./

RUN mkdir -p artifacts features messages \
 && chown -R app:app /app

USER app

ENTRYPOINT ["python", "-u", "run.py"]
CMD []
