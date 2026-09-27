# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models \
    UPLOAD_DIR=/uploads \
    DATA_DIR=/data

# "dev": pytest/ruff/mypy inside the container (used by `docker compose exec api pytest`).
# "ml": sentence-transformers + PyMuPDF for ingestion.
ARG EXTRAS=dev,ml

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --create-home app \
    && mkdir -p /models /uploads /data \
    && chown app:app /models /uploads

# CPU-only PyTorch first: the default wheel bundles CUDA (~2.5 GB) that we don't need.
RUN pip install --upgrade pip \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install dependencies (cached layer): a stub package lets pip resolve the project.
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install -e ".[${EXTRAS}]"

COPY . .
RUN chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
