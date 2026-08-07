"""
JanSetu — Global Django settings.

Only the pieces Django actually needs are enabled: staticfiles, DRF and the
three JanSetu apps. The relational DB layer, sessions, admin and the built-in
auth app are intentionally omitted — JanSetu is a MongoDB-backed REST API with
JWT authentication.
"""

import os
from datetime import timedelta
from pathlib import Path

import mongoengine
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths & environment
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# Load variables from a local `.env` file when present (never required).
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: str = "") -> list:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core Django settings
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-jansetu-dev-key-change-in-production")
DEBUG = _env_bool("DEBUG", True)
ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS", "*")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "rest_framework",
    # JanSetu application modules (kept inside the `apps` package).
    "apps.core",
    "apps.authentication",
    "apps.complaints",
    "apps.ai_services",
    "apps.admin_panel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "jansetu.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": False,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.static",
            ],
        },
    },
]

WSGI_APPLICATION = "jansetu.wsgi.application"
ASGI_APPLICATION = "jansetu.asgi.application"

# ---------------------------------------------------------------------------
# Database — MongoDB via MongoEngine
# ---------------------------------------------------------------------------
# Django still requires a DATABASES key, but JanSetu never touches it. All
# persistence goes through MongoEngine (see MONGODB_URI below). The value is
# an in-memory SQLite database purely to satisfy the Django checks.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# MongoDB connection string. Works with:
#   • MongoDB Atlas:  mongodb+srv://<user>:<pass>@cluster0.xxxx.mongodb.net/jansetu
#   • Local MongoDB:  mongodb://localhost:27017/jansetu
#   • In-memory dev:  mongomock://localhost/jansetu_test   (see requirements-dev.txt)
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/jansetu")

# Connect lazily-ish: MongoEngine connects on first query, but registering the
# alias here keeps every Document in the app on the same connection.
if MONGODB_URI.startswith("mongomock://"):
    # In-memory MongoDB (tests / demo without a real server). Requires the
    # `mongomock` package from requirements-dev.txt.
    try:
        import mongomock
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "MONGODB_URI uses mongomock but mongomock is not installed. "
            "Run: pip install -r requirements-dev.txt"
        ) from exc
    db_name = MONGODB_URI.split("://", 1)[1].split("/", 1)[-1] or "jansetu"
    mongoengine.connect(
        db=db_name,
        alias="default",
        host="mongodb://localhost",
        mongo_client_class=mongomock.MongoClient,
    )
else:
    mongoengine.connect(host=MONGODB_URI, alias="default")

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.authentication.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # JanSetu has no django.contrib.auth — anonymous requests carry no user.
    "UNAUTHENTICATED_USER": None,
    "UNAUTHENTICATED_TOKEN": None,
    "EXCEPTION_HANDLER": "apps.core.exceptions.custom_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 9,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
}

# ---------------------------------------------------------------------------
# JWT configuration (PyJWT based — see apps/authentication/authentication.py)
# ---------------------------------------------------------------------------
JWT_SETTINGS = {
    "SECRET_KEY": os.getenv("JWT_SECRET", SECRET_KEY),
    "ALGORITHM": "HS256",
    "ACCESS_TOKEN_EXPIRY": timedelta(hours=int(os.getenv("JWT_EXPIRY_HOURS", "24"))),
    "REFRESH_TOKEN_EXPIRY": timedelta(days=int(os.getenv("JWT_REFRESH_EXPIRY_DAYS", "7"))),
}

# ---------------------------------------------------------------------------
# Google Gemini AI (mock responses are used automatically when unavailable)
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_FALLBACK_MODELS = _env_list("GEMINI_FALLBACK_MODELS", "gemini-1.5-flash,gemini-1.5-pro")

# ---------------------------------------------------------------------------
# Static & media files
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Upload limits (bytes)
MAX_AUDIO_SIZE = int(os.getenv("MAX_AUDIO_SIZE", "15")) * 1024 * 1024  # 15 MB
MAX_PHOTO_SIZE = int(os.getenv("MAX_PHOTO_SIZE", "10")) * 1024 * 1024  # 10 MB
MAX_DOC_SIZE = int(os.getenv("MAX_DOC_SIZE", "10")) * 1024 * 1024      # 10 MB

# ---------------------------------------------------------------------------
# Admin Approval & Face Authentication
# ---------------------------------------------------------------------------
# Face-match threshold: cosine similarity must be >= this value (0.90 = 90%).
FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.90"))
# Minimum frames a live user must provide during verification (anti-spoofing).
FACE_MIN_SAMPLES = int(os.getenv("FACE_MIN_SAMPLES", "3"))
# Minimum client-reported liveness score (0-100) required to pass the check.
FACE_MIN_LIVENESS = float(os.getenv("FACE_MIN_LIVENESS", "50"))
# Number of face images required during registration.
FACE_REGISTER_MIN_IMAGES = int(os.getenv("FACE_REGISTER_MIN_IMAGES", "5"))
# DEV ONLY — when True, face verification skips the embedding comparison and
# only requires a detected face + liveness, so demo accounts can log in with
# any webcam. Set to False in production for strict biometric matching.
FACE_DEMO_MODE = _env_bool("FACE_DEMO_MODE", True)
# Encryption key for facial embeddings (Fernet). Auto-derived from the Django
# secret when not supplied — set an explicit key in production.
FACE_ENCRYPTION_KEY = os.getenv("FACE_ENCRYPTION_KEY", "")

# Brute-force protection: lock an account after N failed login attempts.
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))

# ---------------------------------------------------------------------------
# Email notifications
# ---------------------------------------------------------------------------
# Leave EMAIL_HOST empty to log emails to the console instead of sending.
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "JanSetu <noreply@jansetu.gov.in>")

# ---------------------------------------------------------------------------
# Localisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
