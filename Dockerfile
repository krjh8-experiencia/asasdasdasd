FROM python:3.11-slim

# Evita errores de apt
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y default-jre-headless ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["bash", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
