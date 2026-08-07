"""Authentication endpoints.

POST /api/auth/register/           citizen (instant) OR validator/official application
POST /api/auth/login/              identifier + password → tokens or face challenge
POST /api/auth/refresh/            refresh token → new token pair
GET  /api/auth/me/                 current user profile
PUT  /api/auth/profile/            update full_name / phone / office fields
POST /api/auth/change-password/    change the account password
POST /api/auth/register-face/      capture & store an encrypted face embedding
POST /api/auth/verify-face/        live face → access/refresh tokens (staff login)
GET  /api/auth/notifications/      in-app notifications for the current user
POST /api/auth/notifications/read/ mark one or all notifications as read
"""

import base64
import io
import logging
import time

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication import face_auth
from apps.authentication.authentication import (
    FaceRegistrationAuthentication,
    create_access_token,
    create_face_challenge_token,
    create_refresh_token,
    decode_token,
)
from apps.authentication.models import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_APPROVED,
    ACCOUNT_STATUS_DEACTIVATED,
    ACCOUNT_STATUS_PENDING,
    ACCOUNT_STATUS_REJECTED,
    ACCOUNT_STATUS_SUSPENDED,
    APPLICATION_STATUS_PENDING,
    Notification,
    User,
)
from apps.authentication.serializers import (
    ApplicationRegisterSerializer,
    ChangePasswordSerializer,
    CitizenRegisterSerializer,
    FaceRegisterSerializer,
    FaceVerifySerializer,
    LoginSerializer,
    ProfileUpdateSerializer,
    RefreshSerializer,
)
from apps.authentication.services import (
    create_notification,
    log_audit,
    notify_application_approved,
    notify_application_rejected,
    notify_application_submitted,
    notify_password_changed,
)
from apps.core.utils import generate_code, get_client_ip, now_utc

logger = logging.getLogger(__name__)

STAFF_ROLE_LABELS = {"validator": "Validator", "official": "Official", "super_admin": "Super Admin"}


def _token_response(user: User) -> dict:
    """Build the standard authenticated response payload."""
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "user": user.public_dict(),
    }


def _record_login(user, method: str, success: bool, detail: str = "",
                  face_score=None, request=None):
    """Write a LoginHistory row (never raises)."""
    try:
        from apps.authentication.models import LoginHistory
        LoginHistory(
            user_id=user.id if user else None,
            email=user.email if user else "",
            method=method,
            success=success,
            face_score=face_score,
            ip=get_client_ip(request) if request else "",
            user_agent=request.headers.get("User-Agent", "")[:250] if request else "",
            detail=detail,
        ).save()
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not record login history: %s", exc)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
class RegisterView(APIView):
    """Create an account.

    * Citizens register with name/email/username/password → instant login.
    * Validators & Officials submit an application form → PENDING approval,
      no login until a Super Admin approves and they pass face auth.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        role = (request.data.get("role") or "citizen").strip().lower()

        if role == "citizen":
            return self._register_citizen(request)
        if role in ("validator", "official"):
            return self._submit_application(request, role)
        raise ValidationError({"role": "Invalid role selected."})

    # ------------------------------------------------------------------
    def _register_citizen(self, request):
        serializer = CitizenRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = User(
            full_name=data["full_name"],
            email=data["email"],
            username=data.get("username") or None,
            phone=data.get("phone", ""),
            role="citizen",
            account_status=ACCOUNT_STATUS_ACTIVE,
            application_status="",
        )
        user.set_password(data["password"])
        user.save()

        _record_login(user, "password", True, detail="citizen self-registration", request=request)
        payload = _token_response(user)
        payload["message"] = "Registration successful. Welcome to JanSetu!"
        payload["account_status"] = ACCOUNT_STATUS_ACTIVE
        return Response(payload, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------------
    def _submit_application(self, request, role: str):
        serializer = ApplicationRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 1. Create the user in a PENDING state — login is blocked until approval.
        user = User(
            full_name=data["full_name"],
            email=data["email"],
            username=data.get("username") or None,
            phone=data.get("phone", ""),
            role=role,
            department=data.get("department", ""),
            office_name=data.get("office_name", ""),
            account_status=ACCOUNT_STATUS_PENDING,
            application_status=APPLICATION_STATUS_PENDING,
        )
        user.set_password(data["password"])
        user.save()

        # 2. Persist uploaded verification documents.
        document_urls = _save_application_documents(request, user.id)
        government_id = document_urls.get("government_id_document", "")
        employee_card = document_urls.get("employee_card", "")
        profile_photo = document_urls.get("profile_photo", "")

        if not government_id:
            user.delete()
            raise ValidationError({"government_id_document": "Please upload your Government ID."})
        if not employee_card:
            user.delete()
            raise ValidationError({"employee_card": "Please upload your Employee ID card."})
        if not profile_photo:
            user.delete()
            raise ValidationError({"profile_photo": "Please upload a profile photograph."})

        # 3. Create the Application record.
        from apps.authentication.models import Application
        application = Application(
            application_id=generate_code("APP"),
            user_id=user.id,
            role_requested=role,
            full_name=data["full_name"],
            email=data["email"],
            phone=data.get("phone", ""),
            department=data.get("department", ""),
            office_name=data.get("office_name", ""),
            government_id_document=government_id,
            employee_card=employee_card,
            profile_photo=profile_photo,
            application_status=APPLICATION_STATUS_PENDING,
        )
        application.save()

        # 4. Face images captured during the form → encrypted embedding now.
        #    If no face can be extracted, roll back so no orphan records remain.
        face_images = request.FILES.getlist("face_images") or []
        if face_images:
            try:
                register_face_from_uploads(user, face_images)
            except ValidationError:
                application.delete()
                user.delete()
                raise
            application.face_registered = user.face_registered
            application.face_images_count = user.face_images_count
            application.save()

        # 5. Notify the applicant (email + in-app).
        notify_application_submitted(user, STAFF_ROLE_LABELS.get(role, role))

        _record_login(user, "password", True, detail="application submitted (pending)", request=request)
        return Response(
            {
                "message": "Your application has been submitted successfully. "
                           "Please wait for Admin verification.",
                "application_id": application.application_id,
                "account_status": ACCOUNT_STATUS_PENDING,
                "role": role,
                "face_registered": user.face_registered,
            },
            status=status.HTTP_201_CREATED,
        )


# Magic-byte signatures for allowed application documents.
_DOC_MAGIC = [
    (b"\xff\xd8\xff", ".jpg"),          # JPEG
    (b"\x89PNG\r\n\x1a\n", ".png"),     # PNG
    (b"RIFF", ".webp"),                 # WEBP (RIFF....WEBP)
    (b"GIF8", ".gif"),                  # GIF
    (b"%PDF", ".pdf"),                  # PDF
]


def _detect_document_ext(uploaded) -> str:
    """Return the file extension inferred from magic bytes (or '' if unknown)."""
    head = uploaded.read(16)
    uploaded.seek(0)
    for sig, ext in _DOC_MAGIC:
        if head.startswith(sig):
            return ext
    if head[8:12] == b"WEBP":
        return ".webp"
    return ""


def _save_application_documents(request, user_id: str) -> dict:
    """Persist uploaded application documents under MEDIA_ROOT/applications/<id>/."""
    import os
    from django.core.files.uploadedfile import UploadedFile

    from apps.core.utils import save_media_upload

    allowed_ext = {".jpg", ".jpeg", ".png", ".pdf", ".webp", ".gif"}
    results = {}
    for field in ("government_id_document", "employee_card", "profile_photo"):
        uploaded = request.FILES.get(field)
        if not isinstance(uploaded, UploadedFile):
            continue
        if uploaded.size > settings.MAX_DOC_SIZE:
            raise ValidationError({field: "Document exceeds the 10 MB limit."})
        name = (uploaded.name or "").lower()
        name_ext = os.path.splitext(name)[1]
        magic_ext = _detect_document_ext(uploaded)
        # Trust the extension when it is recognised; otherwise fall back to
        # the magic-byte signature (rejects renamed/unknown content).
        ext = name_ext if name_ext in allowed_ext else magic_ext
        if not ext:
            raise ValidationError({field: "Unsupported file type. Use JPG, PNG, WEBP or PDF."})
        url = save_media_upload(uploaded, f"applications/{user_id}", f"{field}{ext}")
        results[field] = url
    return results


def register_face_from_uploads(user: User, uploads, min_images: int | None = None) -> dict:
    """Compute an averaged, encrypted embedding from uploaded face images.

    Shared by the application flow and the register-face endpoint. Only the
    encrypted embedding is stored — raw face images are never persisted.

    In FACE_DEMO_MODE the strict "must contain a real face" gate is relaxed so
    the pipeline can be exercised without a webcam; in production every image
    must pass the OpenCV face detector.
    """
    min_images = min_images or getattr(settings, "FACE_REGISTER_MIN_IMAGES", 5)
    vectors = []
    for uploaded in uploads:
        # Rewind so shared/rewound file objects always read from the start.
        try:
            uploaded.seek(0)
        except Exception:
            pass
        raw = b"".join(uploaded.chunks()) or uploaded.read()
        if not raw:
            continue  # empty / exhausted upload — ignore
        if not face_auth.is_demo_mode() and not face_auth.detect_face(raw):
            continue
        vec = face_auth.extract_embedding(raw)
        # Keep only same-length embeddings so the mean stays well-defined.
        if vec and (not vectors or len(vec) == len(vectors[0])):
            vectors.append(vec)

    if not vectors:
        raise ValidationError(
            "No face could be detected in the captured images. "
            "Please ensure your face is clearly visible and well lit."
        )

    # Average the per-image vectors, then re-normalise.
    import numpy as np
    mean = np.mean(vectors, axis=0)
    norm = float(np.linalg.norm(mean)) or 1.0
    averaged = (mean / norm).tolist()

    user.face_embedding = face_auth.encrypt_embedding(averaged)
    user.face_images_count = len(vectors)
    user.face_registered = True
    user.save()

    return {
        "face_registered": True,
        "face_images_used": len(vectors),
        "engine": face_auth.engine_status(),
        "demo_mode": face_auth.is_demo_mode(),
    }


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class LoginView(APIView):
    """Exchange credentials for a JWT token pair (citizens) or a face
    challenge (approved validators / officials)."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"].strip().lower()
        password = serializer.validated_data["password"]

        user = User.objects(email=identifier).first() or User.objects(username=identifier).first()
        if user is None or not user.check_password(password):
            _record_login(user, "password", False, detail="invalid credentials", request=request)
            raise AuthenticationFailed("Invalid email/username or password.")

        # Brute-force protection.
        if user.failed_login_attempts >= getattr(settings, "MAX_LOGIN_ATTEMPTS", 5):
            _record_login(user, "password", False, detail="account locked", request=request)
            raise AuthenticationFailed(
                "Too many failed attempts. Your account has been locked — contact an Administrator."
            )

        # Account status gate.
        gate = self._status_gate(user)
        if gate is not None:
            _record_login(user, "password", False, detail=gate["code"], request=request)
            raise AuthenticationFailed(gate["message"])

        user.failed_login_attempts = 0
        user.save()

        # Citizens: full login immediately. Staff: password is step 1 of 2.
        if user.can_login_with_password_only:
            _record_login(user, "password", True, detail="citizen login", request=request)
            payload = _token_response(user)
            payload["requires_face"] = False
            payload["message"] = "Login successful."
            return Response(payload)

        _record_login(user, "password", True, detail="password ok, face required", request=request)
        return Response({
            "requires_face": True,
            "face_token": create_face_challenge_token(user),
            "face_registered": user.face_registered,
            "user": user.public_dict(),
            "message": "Password verified. Please complete Face Authentication.",
        })

    @staticmethod
    def _status_gate(user) -> dict | None:
        """Return an error payload when the account cannot log in."""
        if not user.is_active or user.account_status == ACCOUNT_STATUS_DEACTIVATED:
            return {"code": "deactivated", "message": "This account has been deactivated."}
        if user.account_status == ACCOUNT_STATUS_SUSPENDED:
            return {"code": "suspended", "message": "This account has been suspended by an Administrator."}
        if user.account_status == ACCOUNT_STATUS_PENDING:
            return {"code": "pending", "message": "Your application is under review. Please wait for Admin verification."}
        if user.account_status == ACCOUNT_STATUS_REJECTED:
            reason = user.rejection_reason or "No reason provided."
            return {"code": "rejected", "message": f"Your application was rejected. Reason: {reason}"}
        return None


class RefreshTokenView(APIView):
    """Rotate a refresh token into a fresh token pair."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = decode_token(serializer.validated_data["refresh_token"], expected_type="refresh")
        user = User.objects(id=payload.get("user_id")).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed("User account is not active.")
        if user.account_status in (ACCOUNT_STATUS_SUSPENDED, ACCOUNT_STATUS_DEACTIVATED):
            raise AuthenticationFailed("This account is not allowed to log in.")
        if user.is_staff_applicant and user.account_status != ACCOUNT_STATUS_APPROVED:
            raise AuthenticationFailed("Your account has not been approved yet.")

        return Response(_token_response(user))


class MeView(APIView):
    """Return the profile of the currently authenticated user."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"user": request.user.public_dict()})


class UpdateProfileView(APIView):
    """Update full_name / phone / office fields for the current user."""

    permission_classes = [IsAuthenticated]

    def put(self, request):
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        for field in ("full_name", "phone", "department", "office_name"):
            if field in serializer.validated_data:
                setattr(request.user, field, serializer.validated_data[field])
        request.user.save()
        return Response({"message": "Profile updated.", "user": request.user.public_dict()})


class ChangePasswordView(APIView):
    """Change the password of the current user (old password required)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not request.user.check_password(data["current_password"]):
            raise AuthenticationFailed("Current password is incorrect.")

        request.user.set_password(data["new_password"])
        request.user.failed_login_attempts = 0
        request.user.save()
        notify_password_changed(request.user)
        return Response({"message": "Password changed successfully."})


# ---------------------------------------------------------------------------
# Face registration & verification
# ---------------------------------------------------------------------------
class RegisterFaceView(APIView):
    """Capture 5-10 webcam images and store an encrypted face embedding.

    Used by validators/officials during the application flow or (re)registration
    after an admin reset. Only the encrypted embedding is persisted.
    """

    authentication_classes = [
        # Accept a real access token OR the face-challenge token from login, so
        # a user whose face was reset can re-register during the login step.
        FaceRegistrationAuthentication,
    ]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.is_staff_applicant:
            raise PermissionDenied("Only Validator/Official accounts register a face.")

        face_images = request.FILES.getlist("images") or request.FILES.getlist("face_images")
        if face_images:
            result = register_face_from_uploads(user, face_images)
            log_audit(user, "face.register", "user", str(user.id),
                      {"count": result["face_images_used"], "engine": result["engine"]})
            return Response(result, status=status.HTTP_201_CREATED)

        serializer = FaceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vectors = []
        for payload in serializer.validated_data["images"]:
            raw = _b64decode_image(payload)
            if raw is None:
                continue
            if not face_auth.is_demo_mode() and not face_auth.detect_face(raw):
                continue
            vec = face_auth.extract_embedding(raw)
            # Keep only same-length embeddings so the mean stays well-defined.
            if vec and (not vectors or len(vec) == len(vectors[0])):
                vectors.append(vec)

        if not vectors:
            raise ValidationError(
                "No face could be detected in the captured images. "
                "Please ensure your face is clearly visible and well lit."
            )

        import numpy as np
        mean = np.mean(vectors, axis=0)
        norm = float(np.linalg.norm(mean)) or 1.0
        averaged = (mean / norm).tolist()

        user.face_embedding = face_auth.encrypt_embedding(averaged)
        user.face_images_count = len(vectors)
        user.face_registered = True
        user.save()

        log_audit(user, "face.register", "user", str(user.id),
                  {"count": len(vectors), "engine": face_auth.engine_status()})
        return Response({
            "face_registered": True,
            "face_images_used": len(vectors),
            "engine": face_auth.engine_status(),
            "demo_mode": face_auth.is_demo_mode(),
        }, status=status.HTTP_201_CREATED)


def _b64decode_image(payload: str) -> bytes | None:
    """Decode a base64 image payload into raw bytes (None on failure)."""
    try:
        payload += "=" * (-len(payload) % 4)
        return base64.b64decode(payload)
    except Exception:
        return None


class VerifyFaceView(APIView):
    """Redeem a face challenge: ONE live frame + liveness → JWT token pair.

    Optimised single-frame flow:
        decode token ──► fetch ONLY the user's face fields ──► liveness gate
        ──► analyze_frame (detect + lighting + embed in one pass) ──► match

    Enforces: valid short-lived face_token, a detectable face in the frame,
    lighting + single-face checks, lightweight liveness evidence, and — unless
    FACE_DEMO_MODE — a cosine-similarity match ≥ 90%. The response includes
    `processing_ms` so clients can verify the sub-500 ms goal.
    """

    # No header authentication — the face-challenge token travels in the body.
    authentication_classes = []
    permission_classes = [AllowAny]

    # Project only the fields this endpoint touches (token response needs the
    # public profile, audit needs email). Everything else on the User document
    # (history, docs, notifications) stays off the wire.
    _FACE_FIELDS = (
        "id", "role", "account_status", "is_active",
        "face_registered", "face_embedding", "failed_login_attempts",
        "full_name", "email", "username", "phone", "department",
        "employee_id", "office_name", "application_status", "created_at",
    )

    def post(self, request):
        t0 = time.perf_counter()
        serializer = FaceVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 1. Validate the short-lived face challenge token.
        payload = decode_token(data["face_token"], expected_type="face_challenge")
        user = User.objects(id=payload.get("user_id")).only(*self._FACE_FIELDS).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed("User account is not active.")
        if not user.is_staff_applicant:
            raise AuthenticationFailed("Face authentication is only required for staff accounts.")
        if user.account_status not in (ACCOUNT_STATUS_APPROVED, ACCOUNT_STATUS_ACTIVE):
            raise AuthenticationFailed(
                "Your account has not been approved yet. Please wait for Admin verification."
            )
        if not user.face_registered or not user.face_embedding:
            raise AuthenticationFailed(
                "No face is registered on this account. Please register your face first."
            )

        # 2. Liveness gate (server-side) — relaxed: blink OR head-turn.
        liveness_ok, liveness_score = face_auth.validate_liveness(data)
        if not liveness_ok:
            _record_login(user, "password+face", False,
                          detail="liveness check failed", request=request)
            raise AuthenticationFailed("Liveness check failed. Please try again.")

        # 3. Single-pass frame analysis (decode → detect → lighting → embed).
        raw = _b64decode_image(data["image"])
        if raw is None:
            raise ValidationError({"image": "Could not decode the face image."})

        analysis = face_auth.analyze_frame(raw)
        demo = face_auth.is_demo_mode()

        if analysis["error"] == "undecodable":
            raise ValidationError({"image": "Could not decode the face image."})
        if analysis["error"] == "multiple_faces":
            _record_login(user, "password+face", False,
                          detail="multiple faces detected", request=request)
            raise ValidationError({"face": "Multiple faces detected. Please ensure only you are in the frame."})
        if analysis["error"] == "low_light":
            _record_login(user, "password+face", False,
                          detail="poor lighting", request=request)
            raise ValidationError({"face": "Lighting too low. Please move to a brighter area and try again."})
        if analysis["error"] == "no_face" and not demo:
            _record_login(user, "password+face", False,
                          detail="no face detected", request=request)
            raise AuthenticationFailed("No face was detected in the frame. Please look at the camera.")

        # Embedding: prefer the single-pass vector; in demo mode fall back to a
        # computed vector so confidence reporting stays meaningful.
        live_vec = analysis.get("embedding")
        if live_vec is None:
            live_vec = face_auth.extract_embedding(raw) if demo else None
        if live_vec is None:
            raise AuthenticationFailed("Could not extract a face embedding. Please try again.")

        # 4. Biometric comparison (skipped in FACE_DEMO_MODE).
        result = face_auth.match_embeddings(user.face_embedding, live_vec)
        if demo:
            result = {
                **result,
                "matched": True,
                "confidence": max(result["confidence"], 92.0),
                "reason": "demo mode — strict match skipped",
            }
        if not result["matched"]:
            _record_login(user, "password+face", False,
                          detail=f"match failed ({result['confidence']}%)",
                          face_score=result["confidence"] / 100.0, request=request)
            raise AuthenticationFailed(
                f"Face verification failed. Confidence was {result['confidence']:.1f}% "
                f"(minimum {result['threshold']:.0f}%). Please try again."
            )

        # 5. Success — issue real tokens (targeted update, no full-doc save).
        if user.failed_login_attempts:
            User.objects(id=user.id).update_one(set__failed_login_attempts=0)
        _record_login(user, "password+face", True,
                      detail=f"face match {result['confidence']:.1f}%",
                      face_score=result["confidence"] / 100.0, request=request)

        payload_out = _token_response(user)
        payload_out["requires_face"] = True
        payload_out["face_confidence"] = result["confidence"]
        payload_out["processing_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        payload_out["message"] = "Face authentication successful. Welcome back!"
        return Response(payload_out)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
class NotificationsListView(APIView):
    """List the current user's in-app notifications with an unread count."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = list(Notification.objects(user_id=request.user.id)[:50])
        unread = Notification.objects(user_id=request.user.id, is_read=False).count()
        return Response({
            "notifications": [n.to_dict() for n in notifications],
            "unread_count": unread,
        })


class MarkNotificationsReadView(APIView):
    """Mark one notification (or all) as read."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        notification_id = request.data.get("notification_id") or ""
        if notification_id:
            Notification.objects(id=notification_id, user_id=request.user.id).update_one(
                set__is_read=True
            )
        else:
            Notification.objects(user_id=request.user.id, is_read=False).update(
                set__is_read=True
            )
        return Response({"message": "Notifications updated."})
