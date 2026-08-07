"""Targeted verification for the post-review fixes (sort, analytics, uploads)."""

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jansetu.settings")
django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.test import Client  # noqa: E402


def call(method, path, body=None, token=None, form=None):
    c = Client()
    kwargs = {"HTTP_AUTHORIZATION": "Bearer " + token} if token else {}
    if form is not None:
        kwargs["data"] = form
    elif body is not None:
        kwargs["data"] = json.dumps(body)
        kwargs["content_type"] = "application/json"
    r = getattr(c, method.lower())("/api" + path, **kwargs)
    try:
        data = r.json()
    except Exception:
        data = r.content.decode()[:200]
    return r.status_code, data


def _tiny_png():
    import base64
    import struct
    import zlib
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 64, 64, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([128]) * 64 for _ in range(64))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


def login(identifier, password):
    s, d = call("POST", "/auth/login/", {"identifier": identifier, "password": password})
    assert s == 200, (s, d)
    if d.get("requires_face"):
        s2, d2 = call("POST", "/auth/verify-face/", {
            "face_token": d["face_token"], "image": _tiny_png(),
            "liveness_score": 90, "blink_count": 2, "head_turn_done": True, "samples": 6,
        })
        assert s2 == 200, (s2, d2)
        return d2["access_token"]
    return d["access_token"]


def main():
    call_command("seed_data", verbosity=0)
    token = login("official@example.com", "Official@123")

    # --- 1. Urgency sorts actually sort now (was silently ignored before) ---
    s, up = call("GET", "/complaints/?sort=urgency_score&page=1", token=token)
    s, down = call("GET", "/complaints/?sort=-urgency_score&page=1", token=token)
    asc = [c["urgency_score"] for c in up["results"]]
    desc = [c["urgency_score"] for c in down["results"]]
    assert asc == sorted(asc), f"urgency asc not sorted: {asc}"
    assert desc == sorted(desc, reverse=True), f"urgency desc not sorted: {desc}"
    print("1. urgency sort asc/desc OK:", asc[:4], "/", desc[:4])

    # --- 2. Validator analytics now show real verified/rejected counts ----
    vtok = login("validator@example.com", "Validator@123")
    s, d = call("GET", "/analytics/", token=vtok)
    by = d["by_status"]
    assert by["VERIFIED"] >= 3 and by["REJECTED"] >= 2, f"validator analytics wrong: {by}"
    print("2. validator analytics OK:", by)

    # --- 3. Magic-byte validation rejects a renamed non-image file --------
    ctok = login("citizen@example.com", "Citizen@123")
    s, d = call("POST", "/complaints/", form={
        "category": "Other",
        "description": "testing upload guard",
        "photo": SimpleUploadedFile("evil.jpg", b"<script>alert(1)</script>", content_type="image/jpeg"),
    }, token=ctok)
    assert s == 400, f"magic-byte guard failed: {s} {d}"
    print("3. magic-byte upload guard OK (400):", str(d)[:60])

    print("\nALL_FIX_CHECKS_PASSED")


if __name__ == "__main__":
    main()
