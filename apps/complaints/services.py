"""Complaint identifiers: unique ID, 6-digit PIN and SHA-256 integrity hash."""

import hashlib
import random
import string

_ALPHABET = string.ascii_uppercase + string.digits
_rng = random.SystemRandom()


def generate_complaint_id() -> str:
    """Return a human friendly unique complaint ID, e.g. `JST-4K9XM2P7`."""
    suffix = "".join(_rng.choice(_ALPHABET) for _ in range(8))
    return f"JST-{suffix}"


def generate_pin() -> str:
    """Return a random 6-digit PIN (zero-padded), e.g. `042718`."""
    return f"{_rng.randint(0, 999999):06d}"


def compute_sha256(complaint_id: str, pin: str, description: str = "") -> str:
    """Deterministic SHA-256 over the complaint identity + content."""
    canonical = f"{complaint_id}|{pin}|{(description or '').strip()}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
