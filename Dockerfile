FROM python:3.12-slim

WORKDIR /opt/asterix-monitor

COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends g++ libexpat1-dev && \
    pip install --no-cache-dir -r requirements.txt && \
    apt-get purge -y g++ libexpat1-dev && apt-get autoremove -y && \
    apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*

COPY app/ app/

ENV ASTERIX_UDP_PORT=23401
ENV WEB_PORT=8080
ENV BUFFER_MAX_MESSAGES=50000

EXPOSE ${WEB_PORT}
EXPOSE ${ASTERIX_UDP_PORT}/udp

CMD uvicorn app.main:app --host 0.0.0.0 --port ${WEB_PORT}
