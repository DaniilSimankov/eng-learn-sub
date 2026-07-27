#!/usr/bin/env bash
set -euo pipefail

MODEL="${SUBLEARN_OLLAMA_MODEL:-qwen2.5:3b}"
WORD_MODEL="${SUBLEARN_OLLAMA_WORD_MODEL:-$MODEL}"
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

ensure_model() {
  local m="$1"
  if curl -sf "${OLLAMA_URL}/api/tags" | grep -Fq "${m}"; then
    return 0
  fi
  echo "[sublearn] pulling model ${m} (first run may take several minutes)..."
  ollama pull "${m}"
}

ensure_model "${MODEL}"
if [[ "${WORD_MODEL}" != "${MODEL}" ]]; then
  ensure_model "${WORD_MODEL}"
fi

# Выгрузить всё лишнее из RAM (раньше могли висеть 3b+7b ≈ 7 GB).
unload_other_models() {
  local keep1="$1"
  local keep2="$2"
  local tags
  tags="$(curl -sf "${OLLAMA_URL}/api/tags" || true)"
  python3 - "$OLLAMA_URL" "$keep1" "$keep2" <<'PY' || true
import json, sys, urllib.request
url, keep1, keep2 = sys.argv[1], sys.argv[2], sys.argv[3]
keep = {keep1, keep2}
try:
    tags = json.load(urllib.request.urlopen(url + "/api/tags", timeout=5))
except Exception:
    sys.exit(0)
for item in tags.get("models") or []:
    name = item.get("name") or item.get("model") or ""
    if not name:
        continue
    base = name.split(":")[0]
    keep_hit = any(
        name == k or name.startswith(k + ":") or name.startswith(k + "-") or base == k.split(":")[0]
        for k in keep
    )
    if keep_hit:
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
}

unload_other_models "${MODEL}" "${WORD_MODEL}"

warmup_model() {
  local m="$1"
  local ctx="$2"
  echo "[sublearn] warming ${m}..."
  curl -sf "${OLLAMA_URL}/api/chat" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${m}\",\"stream\":false,\"keep_alive\":\"${OLLAMA_KEEP_ALIVE:-10m}\",\"options\":{\"num_ctx\":${ctx},\"num_predict\":8},\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}" \
    >/dev/null || echo "[sublearn] warmup ${m} skipped"
}

# Одна модель в RAM. Если word≠line — греем только word (частые клики); line подгрузится по запросу.
warmup_model "${WORD_MODEL}" 256

echo "[sublearn] models ready: words=${WORD_MODEL} lines=${MODEL}"
echo "[sublearn] starting web server on :${SUBLEARN_PORT:-8765}"
exec python3 /app/server.py
