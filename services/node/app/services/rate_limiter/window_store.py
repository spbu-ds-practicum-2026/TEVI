from collections import defaultdict, deque

class WindowStore:
    def __init__(
        self,
        window_ns: int,
        idle_ttl_ns: int,
        windows: defaultdict[str, deque[int]]
    ):
        if idle_ttl_ns < window_ns:
            raise ValueError("idle_ttl_ns must be at least window_ns")

        self.window_ns = window_ns
        self.idle_ttl_ns = idle_ttl_ns
        self.windows = windows

    def prune_and_count(self, user_id: str, now_ns: int) -> int:
        if user_id not in self.windows:
            return 0

        while(self.windows[user_id] and self.windows[user_id][0] + self.window_ns < now_ns):
            self.windows[user_id].popleft()

        answer = len(self.windows[user_id])

        if answer == 0:
            del self.windows[user_id]

        return answer

    def record(self, user_id: str, now_ns: int) -> None:
        if user_id not in self.windows:
            self.windows[user_id] = deque([now_ns])
        else:
            self.windows[user_id].append(now_ns)

    def evict_idle(self, now_ns: int) -> int:
        answer = 0
        to_delete = []

        for user_id in self.windows:
            if(not self.windows[user_id] or self.windows[user_id][-1] + self.idle_ttl_ns < now_ns):
                to_delete.append(user_id)

        for user_id in to_delete:
            answer += 1
            del self.windows[user_id]

        return answer
