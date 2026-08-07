"""Request validation for the authentication API.

Two registration paths:
  * citizens  → CitizenRegisterSerializer (instant access, password login).
  * validators / officials → ApplicationRegisterSerializer (admin approval +
    face authentication required before login).
"""

from rest_framework import serializers

from apps.authentication.models import DEPARTMENTS, STAFF_ROLES, User
from apps.core.utils import normalize_phone, validate_password_strength


class _PasswordMixin(serializers.Serializer):
    """Shared password validation for the two registration forms."""

    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def _validate_passwords(self, attrs):
        if attrs["password"] != attrs.get("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        problems = validate_password_strength(attrs["password"])
        if problems:
            raise serializers.ValidationError({"password": problems})
        return attrs


class CitizenRegisterSerializer(_PasswordMixin):
    """Validates citizen self-registration payloads (instant access)."""

    full_name = serializers.CharField(max_length=120, min_length=2, error_messages={
        "min_length": "Full name must be at least 2 characters.",
    })
    email = serializers.EmailField()
    username = serializers.CharField(required=False, allow_blank=True, max_length=64)
    phone = serializers.CharField(required=False, allow_blank=True, default="", max_length=20)
    role = serializers.ChoiceField(choices=["citizen"], default="citizen", required=False)
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects(email=value).first():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_username(self, value):
        value = (value or "").strip()
        if not value:
            return value
        if User.objects(username=value).first():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_phone(self, value):
        return normalize_phone(value)

    def validate(self, attrs):
        return self._validate_passwords(attrs)


class ApplicationRegisterSerializer(_PasswordMixin):
    """Validates the Validator/Official application form.

    These users do NOT get instant access — their account starts in a
    PENDING state and a Super Admin must approve the application.
    """

    full_name = serializers.CharField(max_length=120, min_length=2, error_messages={
        "min_length": "Full name must be at least 2 characters.",
    })
    email = serializers.EmailField()
    username = serializers.CharField(required=False, allow_blank=True, max_length=64)
    phone = serializers.CharField(required=False, allow_blank=True, default="", max_length=20)
    role = serializers.ChoiceField(choices=list(STAFF_ROLES))
    department = serializers.ChoiceField(
        choices=[(d, d) for d in DEPARTMENTS],
        error_messages={"invalid_choice": "Please select a valid department."},
    )
    office_name = serializers.CharField(max_length=120, allow_blank=True, default="")
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects(email=value).first():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_username(self, value):
        value = (value or "").strip()
        if not value:
            return value
        if User.objects(username=value).first():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_phone(self, value):
        return normalize_phone(value)

    def validate(self, attrs):
        if not (attrs.get("office_name") or "").strip():
            raise serializers.ValidationError({"office_name": "Office name is required."})
        return self._validate_passwords(attrs)


class LoginSerializer(serializers.Serializer):
    """Validates login payloads (identifier = email or username)."""

    identifier = serializers.CharField(max_length=200)
    password = serializers.CharField(write_only=True)


class RefreshSerializer(serializers.Serializer):
    """Validates token-refresh payloads."""

    refresh_token = serializers.CharField()


class ProfileUpdateSerializer(serializers.Serializer):
    """Validates profile updates (full_name / phone / office fields)."""

    full_name = serializers.CharField(max_length=120, min_length=2, required=False)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)
    department = serializers.CharField(required=False, allow_blank=True, max_length=120)
    office_name = serializers.CharField(required=False, allow_blank=True, max_length=120)

    def validate_phone(self, value):
        return normalize_phone(value)


class ChangePasswordSerializer(serializers.Serializer):
    """Validates password-change payloads."""

    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs.get("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        problems = validate_password_strength(attrs["new_password"])
        if problems:
            raise serializers.ValidationError({"new_password": problems})
        return attrs


class FaceRegisterSerializer(serializers.Serializer):
    """Validates face-registration payloads (one or more webcam frames)."""

    images = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=12,
        error_messages={"min_length": "At least one face image is required."},
    )

    def validate_images(self, value):
        cleaned = []
        for item in value:
            item = (item or "").strip()
            if item.startswith("data:"):
                # data:image/jpeg;base64,....
                try:
                    header, payload = item.split(",", 1)
                except ValueError:
                    continue
                if "base64" in header and payload:
                    cleaned.append(payload)
            elif item:
                cleaned.append(item)
        if not cleaned:
            raise serializers.ValidationError("No valid face images were provided.")
        return cleaned


class FaceVerifySerializer(serializers.Serializer):
    """Validates the face-verification payload.

    The client sends the short-lived `face_token` obtained from login plus a
    live frame and the liveness evidence collected during capture.
    """

    face_token = serializers.CharField()
    image = serializers.CharField(help_text="Base64 (or data-URI) JPEG of the live face.")
    liveness_score = serializers.FloatField(required=False, min_value=0, max_value=100, default=0)
    blink_count = serializers.IntegerField(required=False, min_value=0, default=0)
    head_turn_done = serializers.BooleanField(required=False, default=False)
    samples = serializers.IntegerField(required=False, min_value=0, default=1)

    def validate_image(self, value):
        value = (value or "").strip()
        if value.startswith("data:"):
            try:
                value = value.split(",", 1)[1]
            except IndexError:
                raise serializers.ValidationError("Invalid image payload.")
        if not value:
            raise serializers.ValidationError("A live face image is required.")
        return value


class RejectionSerializer(serializers.Serializer):
    """Admin rejection payload — remarks are mandatory."""

    remarks = serializers.CharField(min_length=5, max_length=2000, error_messages={
        "min_length": "Please provide a reason for rejection (at least 5 characters).",
    })


class ReviewSerializer(serializers.Serializer):
    """Admin approval payload — optional note."""

    remarks = serializers.CharField(required=False, allow_blank=True, max_length=2000)
