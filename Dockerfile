# ── 阶段 1: 构建 ──
FROM python:3.13-slim AS builder

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
COPY api/ api/
COPY web/ web/

RUN pip install --no-cache-dir --prefix=/install -e .


# ── 阶段 2: 运行 ──
FROM python:3.13-slim

LABEL maintainer="IFA"
LABEL description="IFA - AI-Powered Index Fund Analysis API"

RUN groupadd --gid 1000 appuser && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY api/ api/
COPY web/ web/

RUN mkdir -p /app/results /app/local_data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs')" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
