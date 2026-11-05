FROM python:3.12-slim
LABEL com.clashbot="1"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      fonts-dejavu-core fonts-noto-core fonts-noto-cjk libfribidi0 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 bot && mkdir -p /keys && chown bot:bot /keys
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY clashbot ./clashbot
USER bot
HEALTHCHECK --interval=60s --timeout=5s --start-period=90s --retries=3 CMD ["python", "-m", "clashbot", "health"]
ENTRYPOINT ["python", "-m", "clashbot"]
CMD ["run"]
