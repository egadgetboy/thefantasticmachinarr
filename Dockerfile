FROM python:3.11-slim

LABEL maintainer="The Fantastic Machinarr"
LABEL version="1.0.0"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/fantastic_machinarr/

RUN mkdir -p /config/logs

EXPOSE 8080

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "fantastic_machinarr", "--host", "0.0.0.0", "--port", "8080"]
