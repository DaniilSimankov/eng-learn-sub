#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "SubLearn: сборка web + запуск ollama/web..."
docker compose up -d --build

echo "Жду http://127.0.0.1:8765 (первый запуск качает модель ИИ, напр. qwen3:4b)..."
for i in $(seq 1 600); do
  if curl -sf http://127.0.0.1:8765/ >/dev/null 2>&1; then
    echo "Готово: http://127.0.0.1:8765"
    echo "Сервисы: docker compose ps"
    echo "Логи:     docker compose logs -f web ollama"
    exit 0
  fi
  if (( i % 15 == 0 )); then
    echo "  ещё жду… (${i}/600) — docker compose logs -f web ollama"
  fi
  sleep 2
done

echo "Сервер ещё не ответил. Смотрите: docker compose logs -f web ollama"
exit 1
