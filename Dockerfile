FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    CONVERTCORD_URBAN_API_URL=http://127.0.0.1:8080/api

WORKDIR /app

# Create data directory for reminders persistence
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-noto-core libcairo2 nodejs npm chromium \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/data

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY renderer/package.json renderer/package-lock.json /app/renderer/
RUN cd /app/renderer && npm ci

COPY ppv-resolver/package.json ppv-resolver/package-lock.json /app/ppv-resolver/
RUN cd /app/ppv-resolver && npm ci

COPY vendor/unofficial-urban-dictionary-api/package.json vendor/unofficial-urban-dictionary-api/package-lock.json /app/vendor/unofficial-urban-dictionary-api/
RUN cd /app/vendor/unofficial-urban-dictionary-api && npm ci --omit=dev

COPY convertcord /app/convertcord
COPY data /app/data
COPY renderer /app/renderer
COPY ppv-resolver /app/ppv-resolver
COPY vendor/unofficial-urban-dictionary-api /app/vendor/unofficial-urban-dictionary-api
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

RUN cd /app/renderer && npm run build:css
RUN chmod +x /app/docker-entrypoint.sh

CMD ["/app/docker-entrypoint.sh"]
