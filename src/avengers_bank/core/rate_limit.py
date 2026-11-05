"""요청 횟수 제한 (로그인 실패, 이체 요청, PIN 오류).

서버 한 대(컨테이너 1개)로 돌리므로 메모리에 센다. 서버를 여러 대로 늘리면 Redis 같은 공유 저장소로 옮겨야 한다.
창(window) 안에 남은 시각만 들고 있다가 오래된 것은 버리는 슬라이딩 윈도 방식이다.
"""

import math
import time
from collections import deque
from threading import Lock

from avengers_bank.core.exceptions import ApiException


class TooManyRequestsException(ApiException):
    def __init__(self, message: str, *, code: str, retry_after: int):
        super().__init__(
            status_code=429,
            code=code,
            message=message,
            headers={"Retry-After": str(retry_after)},
            extra={"retry_after_seconds": retry_after},
        )


class RateLimiter:
    def __init__(self, *, limit: int, window_seconds: int, code: str, message: str):
        self.limit = limit
        self.window = window_seconds
        self.code = code
        self.message = message
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        """창 밖으로 나간 기록을 버린다. 비면 키도 지워서 메모리가 쌓이지 않게 한다."""
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if not hits:
            del self._hits[key]
        return hits

    def _raise_if_full(self, hits: deque[float], now: float) -> None:
        if len(hits) >= self.limit:
            retry_after = max(1, math.ceil(hits[0] + self.window - now))
            raise TooManyRequestsException(self.message, code=self.code, retry_after=retry_after)

    def check(self, key: str) -> None:
        """이미 한도를 채웠으면 429. 세지는 않는다 (실패만 세는 경우에 먼저 부른다)."""
        now = time.monotonic()
        with self._lock:
            self._raise_if_full(self._prune(key, now), now)

    def hit(self, key: str) -> None:
        """한 번 센다. 이미 한도를 채웠으면 세지 않고 429."""
        now = time.monotonic()
        with self._lock:
            self._raise_if_full(self._prune(key, now), now)
            self._hits.setdefault(key, deque()).append(now)

    def record(self, key: str) -> None:
        """한도 검사 없이 한 번 센다 (실패를 기록할 때)."""
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            self._hits.setdefault(key, deque()).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


# 같은 아이디로 비밀번호를 10분에 5번 틀리면 잠시 막는다 (무차별 대입 방지)
login_failures = RateLimiter(
    limit=5, window_seconds=600, code="TOO_MANY_LOGIN_ATTEMPTS",
    message="비밀번호를 여러 번 틀렸어요. 잠시 후 다시 시도해 주세요.",
)
# 같은 IP에서 아이디를 바꿔 가며 시도하는 것도 막는다
login_failures_by_ip = RateLimiter(
    limit=20, window_seconds=600, code="TOO_MANY_LOGIN_ATTEMPTS",
    message="로그인 시도가 너무 많아요. 잠시 후 다시 시도해 주세요.",
)
# 이체 요청은 사용자당 1분에 20번까지 (자동화된 반복 요청 방지)
transfer_requests = RateLimiter(
    limit=20, window_seconds=60, code="TOO_MANY_TRANSFER_REQUESTS",
    message="이체 요청이 너무 잦아요. 잠시 후 다시 시도해 주세요.",
)
# 이체 PIN을 30분에 5번 틀리면 PIN 승인을 잠근다
pin_failures = RateLimiter(
    limit=5, window_seconds=1800, code="PIN_LOCKED",
    message="이체 PIN을 여러 번 틀려 잠시 잠갔어요. 30분 뒤 다시 시도해 주세요.",
)

ALL_LIMITERS = (login_failures, login_failures_by_ip, transfer_requests, pin_failures)
