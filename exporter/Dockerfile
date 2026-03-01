FROM python:3.11-slim
WORKDIR /app
RUN apt-get update -y && apt-get install -y --no-install-recommends ca-certificates curl wget && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py scraper.py ./
EXPOSE 8000
CMD ["python", "main.py"]