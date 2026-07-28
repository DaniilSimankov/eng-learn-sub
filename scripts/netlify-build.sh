#!/usr/bin/env bash
# Собирает каталог public/ для Netlify: только фронт + config.js с URL бэкенда.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/public"

rm -rf "$OUT"
mkdir -p "$OUT/frontend/utils" "$OUT/frontend/subtitles" "$OUT/frontend/api" "$OUT/sample"

cp "$ROOT/index.html" "$ROOT/app.js" "$ROOT/styles.css" "$ROOT/ad-skip.js" "$ROOT/favicon.svg" "$OUT/"
cp "$ROOT/frontend/utils/storage.js" "$OUT/frontend/utils/"
cp "$ROOT/frontend/subtitles/parser.js" "$OUT/frontend/subtitles/"
cp "$ROOT/frontend/api/client.js" "$OUT/frontend/api/"
if [ -f "$ROOT/sample/demo.srt" ]; then
  cp "$ROOT/sample/demo.srt" "$OUT/sample/"
fi

API_URL="${SUBLEARN_API_URL:-}"
API_URL="${API_URL%/}"

if [ -n "$API_URL" ]; then
  API_JS="$(printf '%s' "$API_URL" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
else
  API_JS="''"
fi

cat > "$OUT/frontend/config.js" <<EOF
(function bootstrapSubLearnConfig(globalScope) {
  globalScope.SUBLEARN_API_BASE = ${API_JS};

  globalScope.SubLearnApiUrl = function subLearnApiUrl(path) {
    const base = String(globalScope.SUBLEARN_API_BASE || '').replace(/\/$/, '');
    const normalized = path.startsWith('/') ? path : \`/\${path}\`;
    return \`\${base}\${normalized}\`;
  };
}(window));
EOF

echo "[netlify] public/ ready ($(find "$OUT" -type f | wc -l | tr -d ' ') files)"
if [ -n "$API_URL" ]; then
  echo "[netlify] API base: ${API_URL}"
else
  echo "[netlify] warning: SUBLEARN_API_URL is not set — API calls will fail until you add it in Netlify env vars"
fi
