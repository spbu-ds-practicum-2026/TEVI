# Distributor

Выполняй команды из папки `distributor/`.

## Локальный запуск (Python 3.12)

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
CONFIG_PATH=../config/cluster.json python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Запуск в Docker

```sh
docker build -t fdc-distributor .
docker run --rm -p 8080:8080 \
  --mount "type=bind,source=$(realpath ../config/cluster.json),target=/app/cluster.json,readonly" \
  -e CONFIG_PATH=/app/cluster.json \
  fdc-distributor
```

Приложение читает файл из `CONFIG_PATH` один раз при запуске. Если путь не задан, файл недоступен или данные не проходят валидацию, сервер завершает запуск с ошибкой. Все временные параметры в общем файле указаны в секундах.

## Проверка

При запущенном сервере выполни в другом терминале:

```sh
curl -i http://localhost:8080/health
```

Ожидается HTTP 200 и JSON `{"status": "ok"}`.

## Приём gossip

`POST /internal/gossip` принимает полную таблицу членства от узла и сохраняет её вместе со временем получения. Пример запроса для общего `config/cluster.json`:

```sh
curl -i http://localhost:8080/internal/gossip \
  -H 'Content-Type: application/json' \
  --data '{
    "sender": "n1",
    "table": [
      {"node_id": "n1", "addr": "node1:8080", "status": "alive", "incarnation": 1, "ready": true},
      {"node_id": "n2", "addr": "node2:8080", "status": "alive", "incarnation": 1, "ready": true},
      {"node_id": "n3", "addr": "node3:8080", "status": "alive", "incarnation": 1, "ready": true},
      {"node_id": "n4", "addr": "node4:8080", "status": "alive", "incarnation": 1, "ready": true}
    ]
  }'
```

- **200 OK** — таблица сохранена. Текущий ответ: `{"table": [], "is_in_active": true, "continuously_live": true}`.
- **400 Bad Request** — состав таблицы расходится с конфигурацией кластера.
- **422 Unprocessable Entity** — тело содержит некорректный JSON или нарушает структуру gossip-сообщения.

## Тесты

В локальном виртуальном окружении выполни:

```sh
python -m pip install -r requirements.txt pytest
python -m pytest
```
