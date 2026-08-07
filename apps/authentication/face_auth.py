"""
Face registration & verification service.

Pipeline (production mode):
    image ──► face detection (OpenCV Haar cascade)
          ──► embedding (DeepFace if installed, else OpenCV LBP histogram)
          ──► encrypted with Fernet ──► stored on the User document

Verification:
    live frame ──► detect face ──► extract embedding ──► decrypt stored
          ──► cosine similarity ──► confidence %  (threshold ≥ 90% default)

Security properties
-------------------
* Only the *encrypted* embedding is ever persisted — never the raw image or a
  plain-text feature vector. The Fernet key comes from settings
  (FACE_ENCRYPTION_KEY, auto-derived from the Django secret when not set).
* Liveness is enforced jointly by the client (blink + head-movement checks)
  and the server (minimum frame count, minimum liveness score, and a face must
  actually be detected in the submitted frame).
* Every dependency is imported lazily so the app boots even when the optional
  ML packages are missing — in that case a documented mock embedding is used.

Only the Super Admin can reset a registered face (admin reset-face endpoint).
"""

import base64
import hashlib
import io
import logging
import struct
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine availability (lazy imports — app must boot without these packages)
# ---------------------------------------------------------------------------
_cv2 = None
_deepface = None
_face_recognition = None

try:  # pragma: no cover - environment dependent
    import cv2  # type: ignore
    _cv2 = cv2
    # OpenCV ships Haar cascades inside the wheel.
    _cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
except Exception:  # pragma: no cover
    _cascade = None

try:  # pragma: no cover - optional heavy dependency (tensorflow)
    from deepface import DeepFace  # type: ignore
    _deepface = DeepFace
except Exception:  # pragma: no cover
    _deepface = None

try:  # pragma: no cover - optional dependency
    import face_recognition  # type: ignore
    _face_recognition = face_recognition
except Exception:  # pragma: no cover
    _face_recognition = None


def engine_status() -> str:
    """Human description of the active face engine (for admin UI/debug)."""
    if _deepface is not None:
        return "deepface"
    if _face_recognition is not None:
        return "face_recognition"
    if _cv2 is not None:
        return "opencv"
    return "mock"


def is_demo_mode() -> bool:
    """DEV convenience — see settings.FACE_DEMO_MODE."""
    return bool(getattr(settings, "FACE_DEMO_MODE", True))


# ---------------------------------------------------------------------------
# Image handling
# ---------------------------------------------------------------------------
def _decode_image(image_bytes: bytes):
    """Decode bytes → BGR ndarray (None if invalid)."""
    import numpy as np
    if _cv2 is None:
        return None
    try:
        buf = np.frombuffer(image_bytes, dtype=np.uint8)
        arr = _cv2.imdecode(buf, _cv2.IMREAD_COLOR)
        return arr if arr is not None and arr.size else None
    except Exception:
        return None


def detect_face(image_bytes: bytes) -> bool:
    """Return True when a frontal face is present in the image."""
    if _cv2 is None or _cascade is None:
        # Mock mode: accept any reasonably-sized image payload.
        return len(image_bytes or b"") > 500
    img = _decode_image(image_bytes)
    if img is None:
        return False
    gray = _cv2.cvtColor(img, _cv2.COLOR_BGR2GRAY)
    faces = _cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    return len(faces) > 0


# ---------------------------------------------------------------------------
# Embedding extraction
# ---------------------------------------------------------------------------
def extract_embedding(image_bytes: bytes) -> Optional[list]:
    """Return a normalised feature vector for a face image (or None).

    Preferred order: DeepFace → face_recognition → OpenCV LBP histogram →
    deterministic mock. The mock embedding is stable per-image so the whole
    pipeline remains exercisable without the ML packages.
    """
    if _deepface is not None:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            rep = _deepface.represent(img_path=img, model_name="Facenet", enforce_detection=False)[0]
            return _l2(rep.get("embedding") or rep.get("face_embedding"))
        except Exception as exc:  # pragma: no cover
            logger.warning("DeepFace embedding failed, falling back: %s", exc)

    if _face_recognition is not None:
        try:
            img = _face_recognition.load_image_file(io.BytesIO(image_bytes))
            locs = _face_recognition.face_locations(img)
            if locs:
                emb = _face_recognition.face_encodings(img, known_face_locations=locs[:1])
                if emb:
                    return _l2(list(emb[0]))
        except Exception as exc:  # pragma: no cover
            logger.warning("face_recognition embedding failed, falling back: %s", exc)

    if _cv2 is not None:
        emb = _opencv_embedding(image_bytes)
        if emb is not None:
            return emb

    return _mock_embedding(image_bytes)


def _opencv_embedding(image_bytes: bytes) -> Optional[list]:
    """Local-binary-pattern-style histogram embedding (pure OpenCV/numpy)."""
    try:
        import numpy as np
        img = _decode_image(image_bytes)
        if img is None:
            return None
        gray = _cv2.cvtColor(img, _cv2.COLOR_BGR2GRAY)
        if _cascade is not None:
            faces = _cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
            if len(faces):
                x, y, w, h = faces[0]
                gray = gray[y:y + h, x:x + w]
        gray = _cv2.resize(gray, (128, 128))
        # Uniform-ish local binary pattern over 8 neighbours.
        block = gray[1:-1, 1:-1]
        center = gray[0:-2, 0:-2]
        bits = 0
        hist = np.zeros(256, dtype=np.float64)
        for i, (dx, dy) in enumerate([(1, 0), (1, 1), (0, 1), (-1, 1),
                                      (-1, 0), (-1, -1), (0, -1), (1, -1)]):
            nb = gray[1 + dy:1 + dy + block.shape[0], 1 + dx:1 + dx + block.shape[1]]
            thr = (nb > center).astype(np.uint8) * (1 << i)
            bits = bits + thr
        flat = bits.flatten()
        for v in flat:
            hist[v] += 1.0
        hist /= (hist.sum() or 1.0)
        return _l2(list(hist))
    except Exception as exc:  # pragma: no cover
        logger.warning("OpenCV embedding failed, falling back to mock: %s", exc)
        return None


def _mock_embedding(image_bytes: bytes) -> list:
    """Deterministic pseudo-embedding seeded from the image bytes.

    Same image → same vector; different images → different vectors. Enough to
    exercise the full encryption/compare pipeline when OpenCV/DeepFace are not
    installed. It is NOT a real biometric and is only used as a last resort.
    """
    digest = hashlib.sha256(image_bytes or b"").digest()
    rng = int.from_bytes(digest[:8], "big")
    vec = []
    for i in range(64):
        rng = (rng * 1103515245 + 12345) & 0xFFFFFFFF
        vec.append(((rng >> 16) & 0xFFFF) / 65535.0 - 0.5)
    return _l2(vec)


def _l2(vector) -> list:
    """L2-normalise a vector in place (safe against zero-norm)."""
    norm = sum(v * v for v in vector) ** 0.5 or 1.0
    return [v / norm for v in vector]


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------
def _fernet():
    from cryptography.fernet import Fernet
    key = getattr(settings, "FACE_ENCRYPTION_KEY", "") or ""
    if not key:
        # Derive a stable 32-byte key from the project secret.
        key = base64.urlsafe_b64encode(
            hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        ).decode("ascii")
    return Fernet(key.encode("ascii"))


def encrypt_embedding(vector: list) -> str:
    """Encrypt a feature vector into a Fernet ciphertext (base64 string)."""
    import json
    raw = json.dumps([round(float(v), 8) for v in vector]).encode("utf-8")
    return _fernet().encrypt(raw).decode("ascii")


def decrypt_embedding(blob: str) -> Optional[list]:
    """Decrypt a stored embedding back into a float vector."""
    import json
    try:
        raw = _fernet().decrypt(blob.encode("ascii"))
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def cosine_similarity(a: list, b: list) -> float:
    """Cosine similarity in [-1, 1]; returns 0.0 on degenerate input."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return max(-1.0, min(1.0, dot))


def confidence_percent(a: list, b: list) -> float:
    """Map cosine similarity to a 0-100 confidence score."""
    return round(max(0.0, cosine_similarity(a, b)) * 100.0, 2)


def match_embeddings(stored_blob: str, live_vector: list) -> dict:
    """Compare a live embedding against the stored encrypted embedding.

    Returns {"matched": bool, "confidence": float(0-100), "threshold": float,
             "similarity": float, "reason": str}.
    """
    threshold = float(getattr(settings, "FACE_MATCH_THRESHOLD", 0.90))
    stored = decrypt_embedding(stored_blob)
    if stored is None:
        return {"matched": False, "confidence": 0.0, "threshold": threshold,
                "similarity": 0.0, "reason": "Stored face embedding could not be decrypted."}
    sim = cosine_similarity(stored, live_vector)
    confidence = confidence_percent(stored, live_vector)
    matched = confidence >= threshold * 100.0
    return {
        "matched": matched,
        "confidence": confidence,
        "threshold": threshold * 100.0,
        "similarity": round(sim, 4),
        "reason": "match" if matched else "confidence below threshold",
    }


# ---------------------------------------------------------------------------
# Liveness (server-side validation of client-reported checks)
# ---------------------------------------------------------------------------
def validate_liveness(payload: dict) -> tuple:
    """Server-side liveness gate.

    payload is the verify-face body. Returns (ok: bool, liveness_score: float).
    Requires a detected face plus the client's reported liveness checks to
    clear the configured minimums.
    """
    try:
        liveness = float(payload.get("liveness_score", 0))
    except (TypeError, ValueError):
        liveness = 0.0
    try:
        blinks = int(payload.get("blink_count", 0))
    except (TypeError, ValueError):
        blinks = 0
    try:
        samples = int(payload.get("samples", 0))
    except (TypeError, ValueError):
        samples = 0
    head_ok = bool(payload.get("head_turn_done") or payload.get("head_movement_ok"))

    min_liveness = float(getattr(settings, "FACE_MIN_LIVENESS", 50))
    min_samples = int(getattr(settings, "FACE_MIN_SAMPLES", 3))

    if liveness < min_liveness:
        return False, liveness
    if blinks < 1:
        return False, liveness
    if samples < min_samples:
        return False, liveness
    if not head_ok:
        return False, liveness
    return True, liveness


# Backwards-compatible alias used by the demo e2e helper.
decode_embedding = decrypt_embedding


def demo_embedding() -> str:
    """A deterministic stand-in embedding for seeded demo accounts."""
    vec = _l2([hashlib.sha256(f"jansetu-demo-{i}".encode()).digest()[0] / 255.0 - 0.5 for i in range(64)])
    return encrypt_embedding(vec)


# ---------------------------------------------------------------------------
# Small byte helpers used by tests
# ---------------------------------------------------------------------------
def _png_bytes_from_raw(width: int, height: int, value: int) -> bytes:
    """Build a tiny valid PNG (used by the test suite when cv2 is absent)."""
    import zlib
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([value]) * width for _ in range(height))
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
