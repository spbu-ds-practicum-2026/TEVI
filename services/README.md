# TEVI: Distributed Rate Limiting Middleware

Все команды должны выполняться из корня репозитория

## Сборка и запуск

```sh
docker compose config --quiet
docker compose build
docker compose up -d --wait
docker compose ps
curl -i http://localhost:8080/health
```

Compose запускает распределитель, четыре узла и target. С хоста доступен порт распределителя `8080`. Узлы и target доступны по именам сервисов во внутренней сети.

`/health` подтверждает работоспособность процесса. Узлы начинают принимать клиентские запросы после стартового карантина `T + T_grace` (13 секунд с текущей конфигурацией). После карантина можно проверить сквозной маршрут:

```sh
printf '\000\377\200\n' | curl -i http://localhost:8080/v1/check \
  -H 'X-User-Id: demo-user' -H 'Content-Type: application/octet-stream' --data-binary @-
```

Ожидаемый ответ - HTTP 200 с пустым телом. При недоступном target узел возвращает 502, при отсутствии доступных узлов распределитель возвращает 503.

## Генератор и проверка лимита

Генератор запускается с хоста. Подготовив виртуальное окружение и дождавшись прохождения начального карантина, можно отправить серию запросов одним пользователем командой:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install httpx anyio
python generator/services/load_generator/generator.py http://localhost:8080/v1/check \
  --count 104 --interval 0 --user-id load-demo
docker compose logs --no-color --no-log-prefix node1 node2 node3 node4 2>&1 |
  python generator/services/load_generator/checker.py -
```

Генератор отправляет запросы последовательно и пишет клиентские результаты в `requests.jsonl`. При текущих `L = 100` и `T = 10 с` 104 запроса за одно окно дают ответы 429. Checker читает события `admission` из логов узлов и проверяет максимум допусков за скользящее окно.

## Smoke-тест и остановка

```sh
docker compose down
python scripts/smoke_compose.py
```

Smoke-тест использует порт 8080 и зависимости генератора из виртуального окружения. Он поднимает отдельный Compose-проект, проверяет HTTP, gossip, нагрузку и журналы, затем удаляет контейнеры и сети этого проекта.
