FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on

WORKDIR /app

# Create data directory for reminders persistence
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core libcairo2 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/data

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY convertcord /app/convertcord
COPY data /app/data

CMD ["python", "-m", "convertcord.bot"]
