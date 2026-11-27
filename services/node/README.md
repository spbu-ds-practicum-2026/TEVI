# Лимитер узла

Модуль узла для демо с фиксированным составом кластера. Лимитер считает
квоту `L // n0` для каждого пользователя на одном узле и хранит метки
допущенных запросов в скользящем окне. Метка на левой границе окна
ещё учитывается. Для лимитера достаточно стандартной библиотеки Python.

## Пример из каталога `services/node`

```python
from collections import defaultdict, deque

from app.services.rate_limiter.quota_calculator import QuotaCalculator
from app.services.rate_limiter.rate_limiter import RateLimiter
from app.services.rate_limiter.window_store import WindowStore

window_ns = 10_000_000_000
store = WindowStore(window_ns, window_ns, defaultdict(deque))
limiter = RateLimiter(store, QuotaCalculator(limit=100, n_0=4))
decision = limiter.allow("demo-user")
assert (decision.allowed, decision.n, decision.q) == (True, 4, 25)
```

Для стенда возьми `L`, `n0` и `T` из `services/config/cluster.json`.
В конфиге `T` задан в секундах, а `WindowStore` принимает наносекунды.
TTL должен быть не меньше длины окна.

При подключении HTTP-обработчика используй один экземпляр лимитера на узел.
После проверки готовности узла передай текстовый `X-User-Id` в
`limiter.allow(user_id)`. При допуске обработчик может переслать запрос
в целевой сервис, при исчерпании квоты возвращает `429`.
Периодически вызывай `store.evict_idle(now_ns)` в том же цикле событий,
используя тот же источник монотонного времени, что и лимитер.
Динамический расчёт квоты по таблице участников относится к следующему этапу.

## Тесты

Из каталога `services/node` в Python-окружении с установленным `pytest`:

```sh
python -m pytest -q tests
```
