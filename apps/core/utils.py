"""Shared helper utilities."""

import random
import re
import string
from datetime import datetime, timezone


def now_utc() -> datetime:
    """Timezone-aware UTC timestamp (stored in MongoDB)."""
    return datetime.now(timezone.utc)


_rng = random.SystemRandom()
_ALPHANUM = string.ascii_uppercase + string.digits


def generate_code(prefix: str, length: int = 8) -> str:
    """Return a human-friendly random code, e.g. `APP-4K9XM2P7`."""
    suffix = "".join(_rng.choice(_ALPHANUM) for _ in range(length))
    return f"{prefix}-{suffix}"


def get_client_ip(request) -> str:
    """Best-effort client IP extraction (honours common proxy headers)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def save_media_upload(uploaded_file, relative_dir: str, filename: str) -> str:
    """Persist an uploaded file under MEDIA_ROOT and return its public URL."""
    from django.conf import settings
    dest_dir = settings.MEDIA_ROOT / relative_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    with dest.open("wb+") as handle:
        for chunk in uploaded_file.chunks():
            handle.write(chunk)
    return f"{settings.MEDIA_URL}{relative_dir}/{filename}"


def utc_to_ist(dt) -> datetime:
    """Convert a stored UTC datetime to the Indian Standard Time zone.

    Falls back to the naive input if `zoneinfo` cannot resolve the zone.
    """
    if dt is None:
        return dt
    try:
        from zoneinfo import ZoneInfo
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return dt


def normalize_phone(phone: str) -> str:
    """Strip whitespace/dashes from a phone number and validate roughly."""
    cleaned = re.sub(r"[^0-9+]", "", phone or "")
    return cleaned


def validate_password_strength(password: str) -> list:
    """Return a list of human readable problems with a password (empty = OK)."""
    problems = []
    if len(password) < 8:
        problems.append("Password must be at least 8 characters long.")
    if not any(c.isalpha() for c in password):
        problems.append("Password must contain at least one letter.")
    if not any(c.isdigit() for c in password):
        problems.append("Password must contain at least one digit.")
    return problems
