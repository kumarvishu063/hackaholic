"""
JanSetu end-to-end smoke test.

Exercises the full API in a single process (no network, no DB server):

    MONGODB_URI=mongomock://localhost/jansetu_dev python scripts/e2e_smoke.py

Uses Django's test client so it shares one in-memory MongoDB instance.
"""

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

API = "/api"


def call(method, path, body=None, token=None, form=None, content_type=None):
    """Issue an in-process request and return (status_code, json)."""
    client = Client()
    kwargs = {}
    if token:
        kwargs["HTTP_AUTHORIZATION"] = "Bearer " + token
    if form is not None:
        kwargs["data"] = form
    elif body is not None:
        kwargs["data"] = json.dumps(body)
        kwargs["content_type"] = content_type or "application/json"
    response = getattr(client, method.lower())(API + path, **kwargs)
    try:
        data = response.json()
    except Exception:
        data = response.content.decode()[:200]
    return response.status_code, data


def _tiny_png():
    """Build a minimal PNG payload for the (demo-mode) face-verify step."""
    import base64
    import struct
    import zlib
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 64, 64, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([128]) * 64 for _ in range(64))
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


def login(email, password):
    status, data = call("POST", "/auth/login/", {"identifier": email, "password": password})
    assert status == 200, (status, data)
    if data.get("requires_face"):
        # Approved staff must complete face auth (demo mode is ON by default).
        face_token = data["face_token"]
        s2, d2 = call("POST", "/auth/verify-face/", {
            "face_token": face_token,
            "image": _tiny_png(),
            "liveness_score": 90,
            "blink_count": 2,
            "head_turn_done": True,
            "samples": 6,
        })
        assert s2 == 200, (s2, d2)
        return d2["access_token"], d2["user"]
    return data["access_token"], data["user"]


def main():
    call_command("seed_data", verbosity=0)
    print("== seed ok ==")

    # 1. Citizen registration
    s, d = call("POST", "/auth/register/", {
        "full_name": "E2E Citizen", "email": "e2e@test.com", "password": "E2ePass123",
        "confirm_password": "E2ePass123", "phone": "+919999999999",
    })
    assert s == 201, (s, d)
    citizen_token = d["access_token"]
    print("1. register:", s, d["user"]["role"])

    # 2. Duplicate email rejected
    s, d = call("POST", "/auth/register/", {
        "full_name": "Dup", "email": "e2e@test.com", "password": "E2ePass123",
        "confirm_password": "E2ePass123",
    })
    assert s == 400, (s, d)
    print("2. duplicate email:", s)

    # 3. Complaint with audio + photo (multipart; mock AI path)
    wav = bytes.fromhex("52494646240000005741455645") + b"\x00" * 60
    s, d = call("POST", "/complaints/", form={
        "category": "Water Supply",
        "description": "No water for three days in our block.",
        "address": "HSR Layout, Bengaluru",
        "latitude": "12.9121",
        "longitude": "77.6446",
        "audio": SimpleUploadedFile("complaint.wav", wav, content_type="audio/wav"),
        "photo": SimpleUploadedFile("evidence.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 40, content_type="image/jpeg"),
    }, token=citizen_token)
    assert s == 201, (s, d)
    print("3. submit w/ files:", s, d["complaint_id"], d["status"], "urgency", d["urgency_score"], "| ai:", d["ai_source"])
    print("   transcript:", d["transcript"][:70])
    print("   audio_url:", d["audio_url"], "| photo_url:", d["photo_url"])
    complaint_id = d["complaint_id"]

    # 4. Own complaint list
    s, d = call("GET", "/complaints/?page=1", token=citizen_token)
    print("4. citizen list count:", d["count"])

    # 5. PIN visible to owner only
    s, d = call("GET", "/complaints/" + complaint_id + "/", token=citizen_token)
    assert d["complaint_pin"], "owner must see pin"
    validator_token, _ = login("validator@example.com", "Validator@123")
    s, d = call("GET", "/complaints/" + complaint_id + "/", token=validator_token)
    assert d["complaint_pin"] is None, "validator must NOT see pin"
    print("5. pin visibility ok (owner only)")

    # 6. Validator queue
    s, d = call("GET", "/complaints/?status=PENDING_VALIDATION&page=1", token=validator_token)
    print("6. validator pending count:", d["count"])

    # 7. Validator verifies
    s, d = call("POST", "/complaints/" + complaint_id + "/validate/",
                {"action": "verify", "remarks": "Verified, photos match."}, token=validator_token)
    assert s == 200 and d["status"] == "VERIFIED", (s, d)
    print("7. verify:", s, d["status"])

    # 8. Re-verification blocked
    s, d = call("POST", "/complaints/" + complaint_id + "/validate/", {"action": "verify", "remarks": ""}, token=validator_token)
    assert s == 400, (s, d)
    print("8. re-verify blocked:", s)

    # 9. Official resolves
    official_token, _ = login("official@example.com", "Official@123")
    s, d = call("POST", "/complaints/" + complaint_id + "/resolve/", {"remarks": "Resolved on 5 Aug."}, token=official_token)
    assert s == 200 and d["status"] == "RESOLVED", (s, d)
    print("9. resolve:", s, d["status"])

    # 10. Analytics
    s, d = call("GET", "/analytics/", token=official_token)
    print("10. analytics total:", d["total"], "| by_status:", d["by_status"], "| avg:", d["avg_urgency"])

    # 11. Search + filter + sort
    s, d = call("GET", "/complaints/?status=RESOLVED&q=water&sort=-urgency_score&page=1", token=official_token)
    print("11. filtered count:", d["count"])

    # 12. No token → 401
    s, d = call("GET", "/complaints/")
    assert s == 401, (s, d)
    print("12. no-token blocked:", s)

    # 13. Citizen cannot validate → 403
    s, d = call("POST", "/complaints/" + complaint_id + "/validate/", {"action": "verify"}, token=citizen_token)
    assert s == 403, (s, d)
    print("13. citizen-validate blocked:", s)

    # 14. Timeline entries
    s, d = call("GET", "/complaints/" + complaint_id + "/", token=citizen_token)
    print("14. timeline:", [t["action"] for t in d["timeline"]])

    # 15. Profile update + password change
    s, d = call("PUT", "/auth/profile/", {"full_name": "E2E Citizen Updated", "phone": "+919888888888"}, token=citizen_token)
    assert s == 200 and d["user"]["full_name"] == "E2E Citizen Updated", (s, d)
    s, d = call("POST", "/auth/change-password/",
                {"current_password": "E2ePass123", "new_password": "NewPass456", "confirm_password": "NewPass456"},
                token=citizen_token)
    assert s == 200, (s, d)
    print("15. profile + password ok")

    print("\nALL_API_CHECKS_PASSED")


if __name__ == "__main__":
    main()
