FROM python:3.12-slim-bookworm

USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server.py ad-skip.js index.html app.js styles.css favicon.svg ./
COPY backend ./backend
COPY frontend ./frontend
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && sed -i 's/\r$//' /entrypoint.sh

ENV SUBLEARN_OLLAMA_URL=http://ollama:11434
ENV SUBLEARN_OLLAMA_MODEL=qwen3:4b
ENV SUBLEARN_OLLAMA_NUM_THREAD=2
ENV SUBLEARN_HOST=0.0.0.0
ENV SUBLEARN_PORT=8765
ENV SUBLEARN_DATA_DIR=/app/data
ENV OLLAMA_KEEP_ALIVE=3m

EXPOSE 8765

ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
