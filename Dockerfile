FROM ollama/ollama:latest

USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server.py ad-skip.js index.html app.js styles.css ./
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && sed -i 's/\r$//' /entrypoint.sh

ENV SUBLEARN_OLLAMA_URL=http://127.0.0.1:11434
ENV SUBLEARN_OLLAMA_MODEL=qwen2.5:7b
ENV SUBLEARN_HOST=0.0.0.0
ENV SUBLEARN_PORT=8765
ENV OLLAMA_HOST=127.0.0.1:11434

EXPOSE 8765

ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
