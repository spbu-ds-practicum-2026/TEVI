import argparse
import json
import sys
from contextlib import nullcontext


def max_in_window(times: list[int], window_ns: int) -> int:
    times = sorted(times)
    left = 0
    max_count = 0

    for right, now in enumerate(times):
        while now - times[left] > window_ns:
            left += 1

        max_count = max(max_count, right - left + 1)

    return max_count


def read_admissions(path: str) -> dict[str, list[int]]:
    times_by_user: dict[str, list[int]] = {}

    source = nullcontext(sys.stdin) if path == "-" else open(path, encoding="utf-8")

    with source as log:
        for line in log:
            line = line.strip()

            if not line.startswith("{"):
                _, separator, line = line.partition(" INFO admission ")
                if not separator:
                    continue

            record = json.loads(line)
            if record.get("event") != "admission":
                continue

            user_id = record["user_id"]
            times_by_user.setdefault(user_id, []).append(record["ts"])

    return times_by_user


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "log_path",
        nargs="?",
        default="-",
        help="Путь к журналу допусков. По умолчанию читает из stdin.",
    )
    args = parser.parse_args()

    with open("config/cluster.json", encoding="utf-8") as file:
        config = json.load(file)

    limit = config["L"]
    window_s = config["T"]
    window_ns = int(window_s * 1_000_000_000)
    times_by_user = read_admissions(args.log_path)

    if not times_by_user:
        print("В журнале нет событий admission. Проверка невозможна.")
        return 1

    violation_found = False

    for user_id, times in sorted(times_by_user.items()):
        peak = max_in_window(times, window_ns)
        print(f"{user_id}: максимум {peak} за {window_s} с (лимит {limit})")

        if peak > limit:
            violation_found = True

    print("Лимит превышен" if violation_found else "Лимит соблюдён")
    return 1 if violation_found else 0


if __name__ == "__main__":
    raise SystemExit(main())