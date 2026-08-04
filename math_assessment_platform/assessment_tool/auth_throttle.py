"""
Cache-backed auth throttling for login and password-reset requests.

Tracks failed (or reset) attempts by client IP and by identity (username/email),
applies progressive delays, and temporarily locks after too many attempts.
"""

from __future__ import annotations

import logging
import time

from django.core.cache import cache

logger = logging.getLogger(__name__)

SCOPE_LOGIN = "login"
SCOPE_PASSWORD_RESET = "password_reset"

# Step 1: lock after this many attempts; lock lasts LOCKOUT_SECONDS.
FAILURE_LIMIT = 7
LOCKOUT_SECONDS = 10 * 60
# Sliding window for counting attempts before / during lockout.
FAILURE_WINDOW_SECONDS = 15 * 60

# Step 2: progressive delay (seconds) keyed by current failure count
# before the new attempt is processed. Cap before lockout.
_PROGRESSIVE_DELAY_SECONDS = {
    0: 0,
    1: 1,
    2: 2,
    3: 4,
    4: 4,
    5: 8,
    6: 8,
}

LOCKED_MESSAGE = (
    "Too many attempts from this device or account. "
    "Please wait about 10 minutes and try again."
)


def get_client_ip(request) -> str:
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if forwarded:
        # First hop is the original client when proxies append left-to-right.
        return forwarded.split(",")[0].strip() or "unknown"
    return (request.META.get("REMOTE_ADDR") or "").strip() or "unknown"


def normalize_identity(raw: str | None) -> str:
    return (raw or "").strip().lower()[:255]


def _fail_key(scope: str, kind: str, value: str) -> str:
    return f"auth_throttle:fail:{scope}:{kind}:{value}"


def _lock_key(scope: str, kind: str, value: str) -> str:
    return f"auth_throttle:lock:{scope}:{kind}:{value}"


def _failure_count(scope: str, kind: str, value: str) -> int:
    if not value:
        return 0
    try:
        return int(cache.get(_fail_key(scope, kind, value)) or 0)
    except (TypeError, ValueError):
        return 0


def _is_key_locked(scope: str, kind: str, value: str) -> bool:
    if not value:
        return False
    return bool(cache.get(_lock_key(scope, kind, value)))


def is_locked(*, scope: str, request, identity: str | None = None) -> bool:
    """True if IP or identity is currently locked out for this scope."""
    ip = get_client_ip(request)
    ident = normalize_identity(identity)
    return _is_key_locked(scope, "ip", ip) or (
        bool(ident) and _is_key_locked(scope, "id", ident)
    )


def failure_count_for_request(*, scope: str, request, identity: str | None = None) -> int:
    """Highest failure count among IP and identity (for progressive delay)."""
    ip = get_client_ip(request)
    ident = normalize_identity(identity)
    return max(
        _failure_count(scope, "ip", ip),
        _failure_count(scope, "id", ident) if ident else 0,
    )


def progressive_delay_seconds(*, scope: str, request, identity: str | None = None) -> int:
    count = failure_count_for_request(scope=scope, request=request, identity=identity)
    if count >= FAILURE_LIMIT:
        return 0
    return int(_PROGRESSIVE_DELAY_SECONDS.get(count, 8))


def apply_progressive_delay(*, scope: str, request, identity: str | None = None) -> int:
    """
    Sleep according to prior failure count. Returns seconds slept.
    Call only when not already locked (caller should short-circuit locks first).
    """
    delay = progressive_delay_seconds(scope=scope, request=request, identity=identity)
    if delay > 0:
        time.sleep(delay)
    return delay


def _bump_failure(scope: str, kind: str, value: str) -> int:
    if not value:
        return 0
    key = _fail_key(scope, kind, value)
    try:
        # add() initializes; incr() bumps. Race-safe enough for throttle counters.
        if cache.add(key, 1, timeout=FAILURE_WINDOW_SECONDS):
            count = 1
        else:
            try:
                count = int(cache.incr(key))
            except ValueError:
                cache.set(key, 1, timeout=FAILURE_WINDOW_SECONDS)
                count = 1
            # Refresh TTL so the window extends with continued abuse.
            try:
                cache.touch(key, FAILURE_WINDOW_SECONDS)
            except Exception:
                # Some cache backends may not support touch; counter still works.
                pass
    except Exception:
        logger.exception("auth_throttle bump failed scope=%s kind=%s", scope, kind)
        return 0

    if count >= FAILURE_LIMIT:
        cache.set(_lock_key(scope, kind, value), 1, timeout=LOCKOUT_SECONDS)
    return count


def record_failure(*, scope: str, request, identity: str | None = None) -> int:
    """
    Record a failed login or a password-reset request attempt.
    Returns the max failure count after bumping (IP and identity).
    """
    ip = get_client_ip(request)
    ident = normalize_identity(identity)
    ip_count = _bump_failure(scope, "ip", ip)
    id_count = _bump_failure(scope, "id", ident) if ident else 0
    return max(ip_count, id_count)


def clear_failures(*, scope: str, request, identity: str | None = None) -> None:
    """Clear counters and locks after a successful login (or equivalent)."""
    ip = get_client_ip(request)
    ident = normalize_identity(identity)
    for kind, value in (("ip", ip), ("id", ident)):
        if not value:
            continue
        cache.delete(_fail_key(scope, kind, value))
        cache.delete(_lock_key(scope, kind, value))
