"""
JWT utilities and the Django REST Framework authentication backend.

Tokens carry `user_id`, `role` and `token_type` claims and are signed with
HMAC-SHA256 using the project secret key. Access tokens are short lived;
refresh tokens are long lived and can be exchanged for a fresh pair.
"""

from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication

from apps.authentication.models import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sign(payload: dict) -> str:
    return jwt.encode(
        payload,
        settings.JWT_SETTINGS["SECRET_KEY"],
        algorithm=settings.JWT_SETTINGS["ALGORITHM"],
    )


def create_access_token(user: User) -> str:
    """Short-lived token used on every authenticated request."""
    payload = {
        "user_id": str(user.id),
        "role": user.role,
        "token_type": "access",
        "iat": _now(),
        "exp": _now() + settings.JWT_SETTINGS["ACCESS_TOKEN_EXPIRY"],
    }
    return _sign(payload)


def create_refresh_token(user: User) -> str:
    """Long-lived token exchanged for a new access token."""
    payload = {
        "user_id": str(user.id),
        "role": user.role,
        "token_type": "refresh",
        "iat": _now(),
        "exp": _now() + settings.JWT_SETTINGS["REFRESH_TOKEN_EXPIRY"],
    }
    return _sign(payload)


def create_face_challenge_token(user: User, ttl_minutes: int = 10) -> str:
    """Short-lived token that authorises one face-verification exchange.

    Issued after a successful password login by an approved validator/official.
    The client redeems it at /api/auth/verify-face/ with a live frame; on a
    successful match it is exchanged for the real access/refresh token pair.
    """
    payload = {
        "user_id": str(user.id),
        "role": user.role,
        "token_type": "face_challenge",
        "iat": _now(),
        "exp": _now() + timedelta(minutes=ttl_minutes),
    }
    return _sign(payload)


def decode_token(token: str, expected_type: str = "access") -> dict:
    """Decode and verify a token; raise AuthenticationFailed on any problem."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SETTINGS["SECRET_KEY"],
            algorithms=[settings.JWT_SETTINGS["ALGORITHM"]],
        )
    except jwt.ExpiredSignatureError as exc:
        raise exceptions.AuthenticationFailed("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise exceptions.AuthenticationFailed("Invalid token.") from exc

    if payload.get("token_type") != expected_type:
        raise exceptions.AuthenticationFailed("Invalid token type for this endpoint.")
    return payload


class JWTAuthentication(BaseAuthentication):
    """DRF authentication backend that validates `Authorization: Bearer <jwt>`."""

    keyword = "Bearer"

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header:
            return None  # anonymous — permission classes decide the outcome

        parts = header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            return None

        try:
            payload = decode_token(parts[1], expected_type="access")
        except exceptions.AuthenticationFailed:
            # Public auth endpoints (login, register, refresh) shouldn't be blocked by invalid Bearer tokens
            path = (request.path or "").rstrip("/")
            if path in ("/api/auth/login", "/api/auth/register", "/api/auth/refresh"):
                return None
            raise

        user = User.objects(id=payload.get("user_id")).first()
        if user is None or not user.is_active:
            raise exceptions.AuthenticationFailed("User account is not active.")
        return (user, parts[1])

    def authenticate_header(self, request):
        """WWW-Authenticate value returned alongside 401 responses."""
        return self.keyword


class FaceRegistrationAuthentication(BaseAuthentication):
    """Accepts a standard access token OR a short-lived face-challenge token.

    Used by /api/auth/register-face/ so an approved validator/official whose
    face was reset by an admin can re-register their face during the login
    flow (before they own a real access token).
    """

    keyword = "Bearer"

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header:
            return None
        parts = header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            return None

        payload = None
        for expected_type in ("access", "face_challenge"):
            try:
                payload = decode_token(parts[1], expected_type=expected_type)
                break
            except exceptions.AuthenticationFailed:
                continue
        if payload is None:
            raise exceptions.AuthenticationFailed("Invalid or expired token.")

        user = User.objects(id=payload.get("user_id")).first()
        if user is None or not user.is_active:
            raise exceptions.AuthenticationFailed("User account is not active.")
        return (user, parts[1])

    def authenticate_header(self, request):
        return self.keyword
