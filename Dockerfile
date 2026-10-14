# Multi-stage: dependencies are installed in the builder stage; the runtime
# image carries only the interpreter, installed packages, and app code.
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
# ca-certificates for outbound TLS; then drop to a non-root user.
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser \
    && chown appuser:appuser /app
COPY --from=builder /install /usr/local
COPY --chown=appuser:appuser exporter/*.py ./
USER appuser
EXPOSE 8000
CMD ["python", "main.py"]
