# Multi-stage: dependencies are installed in the builder stage; the runtime
# image carries only the interpreter, installed packages, and app code.
# (openssl + sh stay in the runtime image: the entrypoint generates the
# mock's self-signed TLS cert at container startup.)
FROM python:3.11-slim AS builder
WORKDIR /app
COPY mock_onefs/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends openssl curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /certs \
    && chown appuser:appuser /app /certs
COPY --from=builder /install /usr/local
COPY --chown=appuser:appuser mock_onefs/ ./mock_onefs/
COPY mock_onefs/entrypoint.sh /entrypoint.sh
# Strip any CRLF (Windows checkouts) so the shebang stays valid,
# then make executable.
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh
EXPOSE 8080
USER appuser
ENTRYPOINT ["/entrypoint.sh"]
