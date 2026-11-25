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

## Тесты

В локальном виртуальном окружении выполни:

```sh
python -m pip install -r requirements.txt pytest
python -m pytest
```
