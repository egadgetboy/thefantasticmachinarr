FROM python:3.11-slim

LABEL maintainer="The Fantastic Machinarr"

WORKDIR /app

# Install tzdata for timezone support
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/fantastic_machinarr/

RUN mkdir -p /config/logs

EXPOSE 8080

# Environment variables
# TZ can be set at runtime: -e TZ=America/Chicago
ENV PYTHONUNBUFFERED=1
ENV TZ=UTC

CMD ["python", "-m", "fantastic_machinarr", "--host", "0.0.0.0", "--port", "8080"]
