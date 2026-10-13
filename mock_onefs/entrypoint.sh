#!/bin/sh
# Generate a self-signed cert on first start (OneFSClient uses https://
# with verify=False, so a self-signed cert is accepted).
set -e
mkdir -p /certs
if [ ! -f /certs/cert.pem ]; then
    openssl req -x509 -newkey rsa:2048 \
        -keyout /certs/key.pem -out /certs/cert.pem \
        -days 365 -nodes -subj "/CN=mock-onefs"
fi
exec uvicorn mock_onefs.app:app --host 0.0.0.0 --port 8080 \
    --ssl-keyfile /certs/key.pem --ssl-certfile /certs/cert.pem
