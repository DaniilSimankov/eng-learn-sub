#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "SubLearn: сборка и запуск контейнера..."
docker compose up -d --build

echo "Жду http://127.0.0.1:8765 (первый запуск качает модель ~2 GB)..."
for i in $(seq 1 600); do
  if curl -sf http://127.0.0.1:8765/ >/dev/null 2>&1; then
    echo "Готово: http://127.0.0.1:8765"
    if command -v open >/dev/null 2>&1; then
      open "http://127.0.0.1:8765" || true
    elif command -v xdg-open >/dev/null 2>&1; then
      xdg-open "http://127.0.0.1:8765" || true
    fi
    echo "Логи: docker compose logs -f"
    exit 0
  fi
  if (( i % 15 == 0 )); then
    echo "  ещё жду… (${i}/600) — docker compose logs -f"
  fi
  sleep 2
done

echo "Сервер ещё не ответил. Смотрите логи: docker compose logs -f"
exit 1
