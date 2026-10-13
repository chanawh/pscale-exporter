FROM python:3.11-slim
WORKDIR /app
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*
COPY mock_onefs/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mock_onefs/ ./mock_onefs/
COPY mock_onefs/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
