#!/usr/bin/env bash
set -euo pipefail

MODEL="${SUBLEARN_OLLAMA_MODEL:-qwen3:4b}"
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

# Выгрузить прочие модели из RAM.
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
        print(f"[sublearn] unloaded {name}")
    except Exception as exc:
        print(f"[sublearn] unload {name} skipped: {exc}")
PY

echo "[sublearn] warming ${MODEL}..."
curl -sf "${OLLAMA_URL}/api/chat" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"stream\":false,\"think\":false,\"keep_alive\":\"${OLLAMA_KEEP_ALIVE:-10m}\",\"options\":{\"num_ctx\":512,\"num_predict\":8},\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}" \
  >/dev/null || echo "[sublearn] warmup skipped"

echo "[sublearn] model ready: ${MODEL} (word + phrase agents)"
echo "[sublearn] starting web server on :${SUBLEARN_PORT:-8765}"
exec python3 /app/server.py
