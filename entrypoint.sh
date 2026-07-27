#!/usr/bin/env bash
set -euo pipefail

MODEL="${SUBLEARN_OLLAMA_MODEL:-qwen2.5:7b}"
OLLAMA_URL="${SUBLEARN_OLLAMA_URL:-http://127.0.0.1:11434}"

echo "[sublearn] starting ollama..."
ollama serve >/tmp/ollama.log 2>&1 &
OLLAMA_PID=$!

cleanup() {
  kill "$OLLAMA_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "[sublearn] waiting for ollama..."
for i in $(seq 1 120); do
  if curl -sf "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$OLLAMA_PID" 2>/dev/null; then
    echo "[sublearn] ollama exited early:"
    cat /tmp/ollama.log || true
    exit 1
  fi
  sleep 1
  if [[ "$i" -eq 120 ]]; then
    echo "[sublearn] ollama did not become ready"
    cat /tmp/ollama.log || true
    exit 1
  fi
done

if ! curl -sf "${OLLAMA_URL}/api/tags" | grep -Fq "${MODEL}"; then
  echo "[sublearn] pulling model ${MODEL} (first run may take several minutes)..."
  ollama pull "${MODEL}"
fi

echo "[sublearn] model ready: ${MODEL}"
echo "[sublearn] starting web server on :${SUBLEARN_PORT:-8765}"
exec python3 /app/server.py
