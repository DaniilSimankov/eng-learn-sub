# SubLearn

Учи английский по видео с интерактивными субтитрами: клик по слову → перевод, словарь и разбор фразы через ИИ.

Открой после запуска: **[http://127.0.0.1:8765](http://127.0.0.1:8765)**

---

## Быстрый старт (Docker)

**Требования:** [Docker](https://docs.docker.com/get-docker/) и Docker Compose v2.

```bash
git clone <repo-url> english-learn
cd english-learn
./start.sh
```

Скрипт соберёт образ, поднимет контейнеры и дождётся готовности API. Первый запуск дольше обычного — скачивается модель `qwen3:4b` в Ollama.

Эквивалент без скрипта:

```bash
docker compose up -d --build
```

| Действие | Команда |
|----------|---------|
| Стоп | `docker compose down` |
| Логи | `docker compose logs -f web ollama` |
| Статус | `docker compose ps` |
| Сброс моделей/словаря | `docker compose down -v` |

---

## Архитектура

Два сервиса в одном Compose: веб-приложение и локальная LLM.

```
┌─────────────────────────────────────────────────────────────┐
│  Браузер  →  http://127.0.0.1:8765                          │
└───────────────────────────┬─────────────────────────────────┘
                            │
              ┌─────────────▼─────────────┐
              │  web  (Python :8765)      │
              │  • статика (HTML/JS/CSS)  │
              │  • REST API               │
              │  • HLS / субтитры прокси  │
              │  • SQLite словарь         │
              └───────┬─────────┬─────────┘
                      │         │
           Google     │         │  внутренняя сеть
           Translate  │         │  compose
                      │         ▼
                      │  ┌──────────────────┐
                      │  │ ollama :11434    │
                      │  │ qwen3:4b         │
                      │  │ (только по кнопке│
                      │  │  «объяснить ИИ») │
                      │  └──────────────────┘
                      ▼
              CDN / источник
```

| Сервис | Роль | Ресурсы (по умолчанию) |
|--------|------|------------------------|
| **web** | UI, API, прокси медиа, словарь | 1 CPU · 768 MB · порт **8765** |
| **ollama** | Локальная модель для разбора фраз | 2 CPU · 4 GB · только внутри сети |

Модель стартует cold (на диске). После клика ИИ или prefetch (открытие попапа / hover на «ИИ») держится в RAM `OLLAMA_KEEP_ALIVE=3m`, потом сама выгружается. Во время playback prefetch не стартует. Быстрые клики по словам идут через Google Translate.

### Поток данных

1. Пользователь вставляет ссылку на страницу с поддерживаемым плеером или загружает файлы с диска.
2. `web` резолвит страницу → ID источника / поток / субтитры.
3. Плеер играет HLS через `/api/stream`, субтитры через `/api/subtitles`.
4. Клик по слову → `/api/translate` (Google).
5. Кнопка ИИ → `/api/explain` → Ollama (`qwen3:4b`). Prefetch: `POST /api/ai-warm` при открытии попапа / hover.
6. Словарь сохраняется в SQLite (`vocab_data` volume).

---

## Структура проекта

```
english-learn/
├── backend/
│   ├── app.py           # Альтернативная точка входа backend
│   ├── data/
│   │   └── vocab_repo.py # SQLite-репозиторий словаря
│   └── http/
│       └── io.py        # JSON body + HTTP response helper'ы
├── frontend/
│   ├── api/
│   │   └── client.js    # Клиент для /api/* запросов
│   ├── subtitles/
│   │   └── parser.js    # Парсинг SRT/VTT
│   └── utils/
│       └── storage.js   # Безопасная обертка над localStorage
├── server.py          # HTTP-сервер: статика + API + прокси
├── app.js             # Клиент: плеер, субтитры, словарь, попапы
├── index.html         # UI
├── styles.css         # Стили
├── ad-skip.js         # Инъекция пропуска рекламы в embed
├── entrypoint.sh      # Старт web: ждёт Ollama → pull модели → server.py
├── start.sh           # Удобный запуск compose + ожидание порта
├── Dockerfile         # Образ Python 3.12 (web)
├── docker-compose.yml # Сервисы web + ollama, volumes
├── sample/            # Демо-субтитры
└── data/              # Локальная БД (gitignore; в Docker — volume)
```

### API (кратко)

| Метод | Путь | Назначение |
|-------|------|------------|
| `GET` | `/api/resolve` | Разобрать страницу серии |
| `GET` | `/api/embed` | Прокси embed-плеера |
| `GET` | `/api/stream` | Прокси HLS / медиа |
| `GET` | `/api/subtitles` | Прокси субтитров |
| `GET` | `/api/translate` | Перевод слова/фразы |
| `GET` | `/api/ai-status` | Готовность Ollama (`ready` / `loaded`) |
| `POST` | `/api/ai-warm` | Prefetch: загрузить модель в RAM на keep-alive |
| `POST` | `/api/explain` | Объяснение через ИИ |
| `GET/POST/DELETE` | `/api/vocab` | Словарь |
| `POST` | `/api/vocab/import` | Импорт словаря |

---

## Переменные окружения

Задаются в `docker-compose.yml` у сервиса `web` (и частично у `ollama`).

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `SUBLEARN_HOST` | `0.0.0.0` | Хост биндинга |
| `SUBLEARN_PORT` | `8765` | Порт |
| `SUBLEARN_DATA_DIR` | `/app/data` | Каталог SQLite |
| `SUBLEARN_OLLAMA_URL` | `http://ollama:11434` | URL Ollama |
| `SUBLEARN_OLLAMA_MODEL` | `qwen3:4b` | Имя модели |
| `SUBLEARN_OLLAMA_NUM_THREAD` | `2` | Потоки инференса |
| `OLLAMA_KEEP_ALIVE` | `3m` | Тёплый idle: сколько держать модель в RAM после AI/prefetch |
| `SUBLEARN_TRANSLATE_ENGINE` | `google` | Движок перевода |
| `SUBLEARN_GOOGLE_TRANSLATE` | `1` | Вкл. Google Translate |

---

## Опционально: Ollama на Mac (Metal)

В Docker на Mac модель идёт через CPU внутри VM. Для ускорения можно использовать [Ollama.app](https://ollama.com/) на хосте (Metal):

```bash
# на хосте
ollama pull qwen3:4b

# только web; в docker-compose у web укажите:
# SUBLEARN_OLLAMA_URL: http://host.docker.internal:11434
docker compose up -d --build web
docker compose stop ollama   # контейнерный ollama не нужен
```

---

## Volumes

| Volume | Содержимое |
|--------|------------|
| `ollama_data` | Скачанные модели Ollama |
| `vocab_data` | SQLite-словарь (`vocab.db`) |

Исходники (`server.py`, `app.js`, …) смонтированы в `web` — правки на хосте подхватываются после перезапуска контейнера:

```bash
docker compose restart web
```

---

## Без Docker (локально)

Нужны Python 3.12+ и (опционально) запущенный Ollama.

```bash
export SUBLEARN_OLLAMA_URL=http://127.0.0.1:11434
export SUBLEARN_HOST=127.0.0.1
export SUBLEARN_PORT=8765
python3 server.py
```

Открой [http://127.0.0.1:8765](http://127.0.0.1:8765).

---

## Лицензия

Личный / учебный проект. Используйте ответственно и в соответствии с правилами источников контента.
