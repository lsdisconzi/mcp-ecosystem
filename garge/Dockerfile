FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs data storage

EXPOSE 8066
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8066"]
