# Rate limiter

Модуль узла для демо с фиксированным составом кластера. Зависимостей вне стандартной библиотеки Python нет.

При запуске процесса узла из папки `node/`:

```python
from collections import defaultdict, deque

from app.services.rate_limiter.quota_calculator import QuotaCalculator
from app.services.rate_limiter.rate_limiter import RateLimiter
from app.services.rate_limiter.window_store import WindowStore

window_ns = 10_000_000_000
store = WindowStore(window_ns, window_ns, defaultdict(deque))
limiter = RateLimiter(store, QuotaCalculator(limit=100, n_0=4))
```

На стенде значения `L`, `n0` и `T` бери из общего конфига `config/cluster.json`. `T` указан в секундах, а хранилище ожидает наносекунды. TTL должен быть не меньше окна.

В обработчике `POST /internal/check` после проверки готовности узла передавай текстовый `X-User-Id` в `limiter.allow(user_id)`. При `decision.allowed` пересылай запрос на `/handle`, при отказе возвращай `429`. Все запросы к данному узлу используют один экземпляр лимитера. Проверка и запись метки выполняются синхронно в одном цикле событий. В том же цикле периодически запускай `limiter.store.evict_idle(time.monotonic_ns())`.

Для запуска тестов из `node/` нужен `pytest`.

```sh
python -m pytest -q tests
```
