#!/usr/bin/env bash
# Web-модуль: ждёт Ollama, тянет модели через API, поднимает Python.
set -euo pipefail

if [[ "${SUBLEARN_OLLAMA_OPTIONAL:-0}" == "1" ]]; then
  echo "[web] Ollama optional — starting API without local AI"
  echo "[web] starting on :${SUBLEARN_PORT:-${PORT:-8765}}"
  exec python3 /app/server.py
fi

MODEL_HEAVY="${SUBLEARN_OLLAMA_MODEL:-qwen3:4b}"
MODEL_LIGHT="${SUBLEARN_OLLAMA_MODEL_LIGHT:-qwen3:1.7b}"
OLLAMA_URL="${SUBLEARN_OLLAMA_URL:-http://ollama:11434}"
OLLAMA_URL="${OLLAMA_URL%/}"

echo "[web] waiting for Ollama at ${OLLAMA_URL}..."
for i in $(seq 1 180); do
  if curl -sf "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
    echo "[web] Ollama is up"
    break
  fi
  sleep 1
  if [[ "$i" -eq 180 ]]; then
    echo "[web] Ollama did not become ready at ${OLLAMA_URL}"
    echo "[web] Check: docker compose logs ollama"
    echo "[web] Or host Metal: SUBLEARN_OLLAMA_URL=http://host.docker.internal:11434"
    exit 1
  fi
done

model_present() {
  local name="$1"
  curl -sf "${OLLAMA_URL}/api/tags" | grep -Fq "${name}"
}

pull_model() {
  local name="$1"
  if model_present "${name}"; then
    echo "[web] model on disk: ${name}"
    return 0
  fi
  echo "[web] pulling ${name} via Ollama API (first run may take several minutes)..."
  curl -sf --max-time 3600 "${OLLAMA_URL}/api/pull" \
    -H 'Content-Type: application/json' \
    -d "{\"name\":\"${name}\",\"stream\":false}" \
    >/tmp/ollama-pull-"${name//[:/]/_}".json \
    || {
      echo "[web] pull failed for ${name}:"
      cat "/tmp/ollama-pull-${name//[:/]/_}.json" 2>/dev/null || true
      exit 1
    }
  if ! model_present "${name}"; then
    echo "[web] model ${name} still missing after pull"
    exit 1
  fi
}

pull_model "${MODEL_LIGHT}"
pull_model "${MODEL_HEAVY}"

# Выгрузить ВСЕ модели из RAM при старте: cold start, warm idle включается по AI/prefetch.
python3 - "$OLLAMA_URL" <<'PY' || true
import json, sys, urllib.request
url = sys.argv[1]
try:
    tags = json.load(urllib.request.urlopen(url + "/api/tags", timeout=5))
except Exception:
    sys.exit(0)
for item in tags.get("models") or []:
    name = item.get("name") or item.get("model") or ""
    if not name:
        continue
    req = urllib.request.Request(
        url + "/api/generate",
        data=json.dumps({"model": name, "keep_alive": 0}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=30).read()
        print(f"[web] unloaded {name}")
    except Exception as exc:
        print(f"[web] unload {name} skipped: {exc}")
PY

echo "[web] models on disk: light=${MODEL_LIGHT} heavy=${MODEL_HEAVY} (cold start; warm idle 3m after AI/prefetch)"
echo "[web] starting on :${SUBLEARN_PORT:-8765}"
exec python3 /app/server.py
