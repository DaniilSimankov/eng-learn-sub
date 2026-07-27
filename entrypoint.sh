#!/usr/bin/env bash
# Web-модуль: ждёт Ollama, тянет модель через API, поднимает Python.
set -euo pipefail

MODEL="${SUBLEARN_OLLAMA_MODEL:-qwen3:4b}"
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
  curl -sf "${OLLAMA_URL}/api/tags" | grep -Fq "${MODEL}"
}

if ! model_present; then
  echo "[web] pulling ${MODEL} via Ollama API (first run may take several minutes)..."
  # stream:false — один JSON в конце; без CLI ollama в web-контейнере
  curl -sf --max-time 3600 "${OLLAMA_URL}/api/pull" \
    -H 'Content-Type: application/json' \
    -d "{\"name\":\"${MODEL}\",\"stream\":false}" \
    >/tmp/ollama-pull.json \
    || {
      echo "[web] pull failed:"
      cat /tmp/ollama-pull.json 2>/dev/null || true
      exit 1
    }
  if ! model_present; then
    echo "[web] model ${MODEL} still missing after pull"
    exit 1
  fi
fi

# Выгрузить прочие модели из RAM на стороне Ollama.
python3 - "$OLLAMA_URL" "$MODEL" <<'PY' || true
import json, sys, urllib.request
url, keep = sys.argv[1], sys.argv[2]
try:
    tags = json.load(urllib.request.urlopen(url + "/api/tags", timeout=5))
except Exception:
    sys.exit(0)
for item in tags.get("models") or []:
    name = item.get("name") or item.get("model") or ""
    if not name:
        continue
    if name == keep or name.startswith(f"{keep}-") or name.startswith(f"{keep}:"):
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

echo "[web] warming ${MODEL}..."
curl -sf --max-time 120 "${OLLAMA_URL}/api/chat" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"stream\":false,\"think\":false,\"keep_alive\":\"${OLLAMA_KEEP_ALIVE:-10m}\",\"options\":{\"num_ctx\":512,\"num_predict\":8,\"num_thread\":${SUBLEARN_OLLAMA_NUM_THREAD:-2}},\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}" \
  >/dev/null || echo "[web] warmup skipped"

echo "[web] model ready: ${MODEL}"
echo "[web] starting on :${SUBLEARN_PORT:-8765}"
exec python3 /app/server.py
