"""Teacher accounts: password hashing, session tokens and a brake on password guessing.

Pure functions and one small class, so they can be tested without the server.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time

# scrypt from the standard library, so the server needs no extra packages.
# 2**15 takes about a quarter of a second on a small machine, which is fine for
# the rare login and too slow for a guessing loop. Tests lower it.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 64 * 1024 * 1024

SESSION_SECONDS = 30 * 24 * 60 * 60
MIN_PASSWORD = 8
MAX_PASSWORD = 200
MAX_EMAIL = 200
MAX_TEACHER_NAME = 60

# Wrong passwords for one email beyond this many in the window block logins until it ends.
LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60

EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(Exception):
    """A sign-up or login the rules do not allow. The message is shown to the user."""


def clean_email(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AccountError("Your email is missing.")
    email = value.strip().lower()
    if len(email) > MAX_EMAIL or not EMAIL_SHAPE.match(email):
        raise AccountError("That does not look like an email address.")
    return email


def clean_password(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise AccountError("Your password is missing.")
    if len(value) < MIN_PASSWORD:
        raise AccountError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if len(value) > MAX_PASSWORD:
        raise AccountError(f"Use a password of at most {MAX_PASSWORD} characters.")
    return value


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    """A self-describing hash, so the cost can be raised later without a migration."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=SCRYPT_MAXMEM, dklen=32
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def check_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=SCRYPT_MAXMEM,
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_key(token: str) -> str:
    """What the database keeps: a token's hash, so a leaked table does not log anyone in."""
    return hashlib.sha256(token.encode()).hexdigest()


class LoginBrake:
    """Remembers recent wrong passwords per email and says how long a login must wait."""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}

    def _recent(self, email: str, now: float) -> list[float]:
        since = now - LOGIN_WINDOW_SECONDS
        recent = [moment for moment in self._failures.get(email, []) if moment > since]
        if recent:
            self._failures[email] = recent
        else:
            self._failures.pop(email, None)
        return recent

    def wait(self, email: str, now: float | None = None) -> int:
        """Seconds until a login for this email may be tried, or 0 when it may be tried now."""
        now = time.time() if now is None else now
        recent = self._recent(email, now)
        if len(recent) < LOGIN_ATTEMPTS:
            return 0
        return max(1, int(recent[0] + LOGIN_WINDOW_SECONDS - now))

    def failed(self, email: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._failures.setdefault(email, []).append(now)

    def succeeded(self, email: str) -> None:
        self._failures.pop(email, None)
