"""
Face registration & verification service.

Pipeline (production mode):
    image ──► face detection (OpenCV Haar cascade)
          ──► embedding (DeepFace / face_recognition / OpenCV LBP histogram)
          ──► encrypted with Fernet ──► stored on the User document

Verification:
    live frame ──► analyze_frame (single decode + detect + lighting + embed)
          ──► decrypt stored ──► cosine similarity ──► confidence %
          (threshold ≥ 90% default)

Performance notes (see FACE_AUTH_OPTIMIZATION.txt)
--------------------------------------------------
* The heavy models are loaded ONCE per process (module-level cache + thread
  lock) and reused for every request — never rebuilt per login.
* `analyze_frame()` performs decode → detect → lighting → embedding in a
  single pass over the image, so the verify endpoint never decodes or scans
  the frame twice.
* The engine is selected from settings.FACE_ENGINE ("opencv" by default,
  the lightweight Haar + LBP path). DeepFace / face_recognition are used only
  when explicitly requested and installed.

Security properties
-------------------
* Only the *encrypted* embedding is ever persisted — never the raw image or a
  plain-text feature vector. The Fernet key comes from settings
  (FACE_ENCRYPTION_KEY, auto-derived from the Django secret when not set).
* Liveness is enforced jointly by the client (blink OR head-turn gesture) and
  the server (minimum samples, minimum liveness score, and a face must actually
  be detected in the submitted frame).
* Every dependency is imported lazily so the app boots even when the optional
  ML packages are missing — in that case a documented mock embedding is used.

Only the Super Admin can reset a registered face (admin reset-face endpoint).
"""

import base64
import hashlib
import io
import logging
import struct
import threading
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine availability (lazy imports — app must boot without these packages)
# ---------------------------------------------------------------------------
_cv2 = None
_deepface = None
_face_recognition = None
_cascade = None

try:  # pragma: no cover - environment dependent
    import cv2  # type: ignore
    _cv2 = cv2
    # OpenCV ships Haar cascades inside the wheel. Loaded once at import time —
    # this is the "load the model once when the server starts" requirement.
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

# Once-only model registry for the optional heavy engines (deepface /
# face_recognition). Guarded by a lock so a burst of concurrent logins never
# loads the model twice.
_MODEL_LOCK = threading.Lock()
_MODEL_CACHE = {}


def _load_deepface_model(model_name: str = "Facenet"):
    """Load (once) and return the DeepFace embedding model."""
    key = f"deepface:{model_name}"
    with _MODEL_LOCK:
        if key not in _MODEL_CACHE:
            from deepface.commons import functions  # type: ignore
            _MODEL_CACHE[key] = functions.load_model(
                model_name=model_name,
                task="facial_recognition",
            )
        return _MODEL_CACHE[key]


# ---------------------------------------------------------------------------
# Engine selection (settings.FACE_ENGINE, cached)
# ---------------------------------------------------------------------------
_ENGINE_CACHE = {}  # {requested_engine: resolved_engine} — respects override_settings


def _resolve_engine() -> str:
    """Pick the active engine honouring settings.FACE_ENGINE availability.

    "opencv" (default) → Haar cascade detection + LBP histogram embedding.
    Falls back gracefully to the deterministic mock when nothing is installed.
    Resolution is cached per requested value so runtime lookups stay free while
    tests using override_settings(FACE_ENGINE=...) still see the right engine.
    """
    requested = (getattr(settings, "FACE_ENGINE", "opencv") or "opencv").strip().lower()
    if requested in _ENGINE_CACHE:
        return _ENGINE_CACHE[requested]

    order = {
        "auto": ("deepface", "face_recognition", "opencv", "mock"),
        "deepface": ("deepface", "opencv", "mock"),
        "face_recognition": ("face_recognition", "opencv", "mock"),
        "opencv": ("opencv", "mock"),
        "mock": ("mock",),
    }.get(requested, ("opencv", "mock"))

    availability = {
        "deepface": _deepface is not None,
        "face_recognition": _face_recognition is not None,
        "opencv": _cv2 is not None,
        "mock": True,
    }
    resolved = "mock"
    for engine in order:
        if availability[engine]:
            resolved = engine
            break
    _ENGINE_CACHE[requested] = resolved
    return resolved


def engine_status() -> str:
    """Human description of the active face engine (for admin UI/debug)."""
    return _resolve_engine()


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


def _brightness_of(gray) -> Optional[float]:
    """Mean luminance (0-255) of a grayscale frame, or None when unavailable."""
    try:
        import numpy as np
        return float(np.mean(gray))
    except Exception:  # pragma: no cover
        return None


def analyze_frame(image_bytes: bytes) -> dict:
    """Single-pass frame analysis: decode → detect → lighting → embedding.

    Returns a dict with the keys:
        ok         bool   — True when exactly one face is usable
        embedding  list|None — L2-normalised feature vector (None on failure)
        faces      int    — number of frontal faces found
        face_box   tuple|None — (x, y, w, h) of the primary face
        brightness float|None — mean luminance of the decoded frame
        error      str|None — "undecodable" | "no_face" | "multiple_faces"
                              | "low_light" | None

    This replaces the old detect-then-extract double scan: the frame is
    decoded and scanned exactly once per request.
    """
    if _cv2 is None or _cascade is None:
        # Mock mode: accept any reasonably-sized payload, deterministic vector.
        return {
            "ok": True,
            "embedding": _mock_embedding(image_bytes),
            "faces": 1,
            "face_box": None,
            "brightness": None,
            "error": None,
        }

    img = _decode_image(image_bytes)
    if img is None:
        return {"ok": False, "embedding": None, "faces": 0, "face_box": None,
                "brightness": None, "error": "undecodable"}

    gray = _cv2.cvtColor(img, _cv2.COLOR_BGR2GRAY)
    brightness = _brightness_of(gray)
    faces = _cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))

    max_faces = int(getattr(settings, "FACE_MAX_FACES", 1))
    if len(faces) == 0:
        return {"ok": False, "embedding": None, "faces": 0, "face_box": None,
                "brightness": brightness, "error": "no_face"}
    if len(faces) > max_faces:
        return {"ok": False, "embedding": None, "faces": len(faces),
                "face_box": tuple(int(v) for v in faces[0]),
                "brightness": brightness, "error": "multiple_faces"}

    box = tuple(int(v) for v in faces[0])
    min_brightness = float(getattr(settings, "FACE_MIN_BRIGHTNESS", 40))
    if brightness is not None and brightness < min_brightness:
        return {"ok": False, "embedding": None, "faces": 1, "face_box": box,
                "brightness": brightness, "error": "low_light"}

    embedding = _embed_from_gray(gray, box)
    return {"ok": embedding is not None, "embedding": embedding, "faces": 1,
            "face_box": box, "brightness": brightness, "error": None}


# ---------------------------------------------------------------------------
# Embedding extraction
# ---------------------------------------------------------------------------
def extract_embedding(image_bytes: bytes) -> Optional[list]:
    """Return a normalised feature vector for a face image (or None).

    Engine order follows settings.FACE_ENGINE. The fallback chain never throws
    — the deterministic mock keeps the whole pipeline exercisable without the
    ML packages.
    """
    engine = _resolve_engine()
    try:
        if engine == "deepface" and _deepface is not None:
            return _deepface_embedding(image_bytes)
        if engine == "face_recognition" and _face_recognition is not None:
            return _fr_embedding(image_bytes)
        if engine == "opencv" and _cv2 is not None:
            return _opencv_embedding(image_bytes)
    except Exception as exc:  # pragma: no cover
        logger.warning("Face engine %s failed, falling back: %s", engine, exc)
    return _mock_embedding(image_bytes)


def _deepface_embedding(image_bytes: bytes) -> Optional[list]:
    """Facenet-style embedding via the (once-loaded) DeepFace model."""
    from PIL import Image
    model = _load_deepface_model("Facenet")
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    rep = _deepface.represent(
        img_path=img,
        model=model,
        enforce_detection=False,
        align=False,
        detector_backend="skip",
    )[0]
    return _l2(rep.get("embedding") or rep.get("face_embedding"))


def _fr_embedding(image_bytes: bytes) -> Optional[list]:
    """dlib face_recognition embedding (128-d). Model loads once per process."""
    img = _face_recognition.load_image_file(io.BytesIO(image_bytes))
    locs = _face_recognition.face_locations(img)
    if locs:
        emb = _face_recognition.face_encodings(img, known_face_locations=locs[:1])
        if emb:
            return _l2(list(emb[0]))
    return None


def _embed_from_gray(gray, box) -> Optional[list]:
    """Local-binary-pattern histogram embedding from a grayscale frame + box."""
    try:
        import numpy as np
        x, y, w, h = box
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
        logger.warning("OpenCV embedding failed: %s", exc)
        return None


def _opencv_embedding(image_bytes: bytes) -> Optional[list]:
    """Backwards-compatible wrapper: decode + detect + LBP embedding."""
    if _cv2 is None:
        return None
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
    return _embed_from_gray(gray, (0, 0, 128, 128))


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
    if len(stored) != len(live_vector):
        return {"matched": False, "confidence": 0.0, "threshold": threshold,
                "similarity": 0.0,
                "reason": "Face profile was created with a different model. Please re-register your face."}
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

    Mode (settings.FACE_LIVENESS_MODE, default "relaxed"):
      * relaxed — ONE lightweight gesture is enough: the user blinks once OR
        turns their head slightly (spec: "Blink once OR turn head slightly").
      * strict  — the original behaviour: blink AND head-turn both required.
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
    min_samples = int(getattr(settings, "FACE_MIN_SAMPLES", 1))
    mode = (getattr(settings, "FACE_LIVENESS_MODE", "relaxed") or "relaxed").strip().lower()

    if samples < min_samples:
        return False, liveness
    if liveness < min_liveness:
        return False, liveness

    if mode == "strict":
        return (blinks >= 1 and head_ok), liveness
    # relaxed — any single gesture is sufficient.
    return (blinks >= 1 or head_ok), liveness


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
