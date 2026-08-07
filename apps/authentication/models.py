"""
JanSetu data model.

User — the single source of truth for authentication. Passwords are hashed
with bcrypt (12 rounds) and never stored in plain text; facial embeddings are
stored encrypted (see apps.authentication.face_auth). Validator / Official
accounts pass through an Admin approval workflow before they can log in, and
must complete Face Authentication on every login.

Application  — the approval application record submitted by a Validator or
               Official who wants an account (with uploaded documents).
Notification — in-app dashboard notification for a user.
LoginHistory — record of every login attempt (password + face).
AuditLog     — administrative audit trail (approve/reject/deactivate/reset…).
"""

import bcrypt
from mongoengine import (
    BooleanField,
    DateTimeField,
    DictField,
    Document,
    EmailField,
    FloatField,
    IntField,
    ObjectIdField,
    StringField,
)

from apps.core.utils import now_utc

# ---------------------------------------------------------------------------
# Role & status constants
# ---------------------------------------------------------------------------
ROLE_CHOICES = (
    ("citizen", "Citizen"),
    ("validator", "Validator"),
    ("official", "Official"),
    ("super_admin", "Super Admin"),
)

ROLES = [role for role, _label in ROLE_CHOICES]

# Account lifecycle for staff (validator / official) and everyone else.
ACCOUNT_STATUS_PENDING = "PENDING"          # application submitted, awaiting admin
ACCOUNT_STATUS_APPROVED = "APPROVED"        # admin approved, face auth still required at login
ACCOUNT_STATUS_ACTIVE = "ACTIVE"            # citizen: active immediately
ACCOUNT_STATUS_REJECTED = "REJECTED"        # application rejected
ACCOUNT_STATUS_SUSPENDED = "SUSPENDED"      # temporarily suspended by admin
ACCOUNT_STATUS_DEACTIVATED = "DEACTIVATED"  # permanently deactivated by admin

ACCOUNT_STATUS_CHOICES = [
    ACCOUNT_STATUS_PENDING,
    ACCOUNT_STATUS_APPROVED,
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_REJECTED,
    ACCOUNT_STATUS_SUSPENDED,
    ACCOUNT_STATUS_DEACTIVATED,
]

# Application-level lifecycle (mirrors account status for staff roles).
APPLICATION_STATUS_PENDING = "PENDING"
APPLICATION_STATUS_APPROVED = "APPROVED"
APPLICATION_STATUS_REJECTED = "REJECTED"

APPLICATION_STATUS_CHOICES = [
    APPLICATION_STATUS_PENDING,
    APPLICATION_STATUS_APPROVED,
    APPLICATION_STATUS_REJECTED,
]

# Roles that require the admin approval + face authentication workflow.
STAFF_ROLES = ("validator", "official")

# Departments a Validator/Official can belong to (registration dropdown).
DEPARTMENTS = (
    "Urban Development",
    "Public Works",
    "Water Supply",
    "Sanitation & Garbage",
    "Electricity",
    "Public Health",
    "Education",
    "Police & Safety",
    "Environment",
    "Roads & Transport",
)


class User(Document):
    """A citizen, validator, official or super admin on the JanSetu platform."""

    meta = {
        "collection": "users",
        "indexes": [
            {"fields": ["email"], "unique": True},
            {"fields": ["username"], "unique": True, "sparse": True},
            "role",
            "account_status",
            "-created_at",
        ],
        "ordering": ["-created_at"],
    }

    full_name = StringField(required=True, max_length=120, min_length=2)
    email = EmailField(required=True, unique=True)
    username = StringField(max_length=64, sparse=True)
    password_hash = StringField(required=True)
    phone = StringField(default="", max_length=20)
    role = StringField(required=True, choices=ROLE_CHOICES, default="citizen")
    is_active = BooleanField(default=True)

    # --- Staff / application profile --------------------------------------
    department = StringField(default="")
    employee_id = StringField(default="")
    office_name = StringField(default="")
    office_address = StringField(default="")

    # --- Facial authentication ---------------------------------------------
    face_embedding = StringField(default="")   # encrypted blob (Fernet) — never raw
    face_registered = BooleanField(default=False)
    face_images_count = IntField(default=0)

    # --- Admin approval workflow -------------------------------------------
    account_status = StringField(default=ACCOUNT_STATUS_ACTIVE, choices=ACCOUNT_STATUS_CHOICES)
    application_status = StringField(default="", choices=APPLICATION_STATUS_CHOICES + [""])
    approval_date = DateTimeField()
    approved_by = ObjectIdField()              # reference to the approving super admin
    rejection_reason = StringField(default="")

    # --- Security ------------------------------------------------------------
    failed_login_attempts = IntField(default=0)

    created_at = DateTimeField(default=now_utc)
    updated_at = DateTimeField(default=now_utc)

    # ------------------------------------------------------------------
    # Password management (bcrypt)
    # ------------------------------------------------------------------
    def set_password(self, raw_password: str) -> None:
        """Hash and store a plain-text password."""
        self.password_hash = bcrypt.hashpw(
            raw_password.encode("utf-8"), bcrypt.gensalt(rounds=12)
        ).decode("utf-8")

    def check_password(self, raw_password: str) -> bool:
        """Verify a plain-text password against the stored hash."""
        if not self.password_hash:
            return False
        try:
            return bcrypt.checkpw(
                raw_password.encode("utf-8"), self.password_hash.encode("utf-8")
            )
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Application workflow helpers
    # ------------------------------------------------------------------
    @property
    def is_staff_applicant(self) -> bool:
        """True for validators/officials (the approval workflow roles)."""
        return self.role in STAFF_ROLES

    @property
    def can_login_with_password_only(self) -> bool:
        """Citizens and super admins log in with password only.

        Validators and officials additionally need admin approval and face auth.
        """
        return self.role in ("citizen", "super_admin")

    def reset_login_failures(self) -> None:
        if self.failed_login_attempts:
            self.failed_login_attempts = 0
            self.save()

    # ------------------------------------------------------------------
    # DRF compatibility helpers
    # ------------------------------------------------------------------
    @property
    def is_authenticated(self):
        """Always True for real, loaded users (DRF checks this property)."""
        return True

    @property
    def is_anonymous(self):
        return False

    @property
    def is_staff(self):
        return self.role in ("validator", "official")

    @property
    def is_super_admin(self):
        return self.role == "super_admin"

    # ------------------------------------------------------------------
    def save(self, *args, **kwargs):
        self.updated_at = now_utc()
        return super().save(*args, **kwargs)

    def public_dict(self) -> dict:
        """Safe serialisable representation (never exposes secrets)."""
        return {
            "id": str(self.id),
            "full_name": self.full_name,
            "email": self.email,
            "username": self.username,
            "phone": self.phone,
            "role": self.role,
            "department": self.department,
            "employee_id": self.employee_id,
            "office_name": self.office_name,
            "account_status": self.account_status,
            "application_status": self.application_status,
            "face_registered": self.face_registered,
            "created_at": self.created_at,
        }

    def admin_dict(self) -> dict:
        """Fuller representation for the Super Admin dashboard."""
        data = self.public_dict()
        data.update({
            "office_address": self.office_address,
            "approval_date": self.approval_date,
            "rejection_reason": self.rejection_reason,
            "face_images_count": self.face_images_count,
            "failed_login_attempts": self.failed_login_attempts,
            "updated_at": self.updated_at,
        })
        return data

    def __str__(self):
        return f"{self.full_name} <{self.email}> ({self.role})"


class Application(Document):
    """Admin approval application for Validator / Official accounts."""

    meta = {
        "collection": "applications",
        "indexes": [
            {"fields": ["application_id"], "unique": True},
            "user_id",
            "role_requested",
            "application_status",
            "-applied_on",
        ],
        "ordering": ["-applied_on"],
    }

    application_id = StringField(required=True, unique=True)   # e.g. APP-4K9XM2P7
    user_id = ObjectIdField(required=True)
    role_requested = StringField(required=True, choices=STAFF_ROLES)

    # Snapshot of applicant details at submission time.
    full_name = StringField(required=True)
    email = EmailField(required=True)
    phone = StringField(default="")
    department = StringField(default="")
    employee_id = StringField(default="")
    office_name = StringField(default="")
    office_address = StringField(default="")

    # Uploaded verification documents (relative media URLs).
    government_id_document = StringField(default="")
    employee_card = StringField(default="")
    profile_photo = StringField(default="")

    # Face registration status.
    face_registered = BooleanField(default=False)
    face_images_count = IntField(default=0)

    # Review state.
    application_status = StringField(required=True, default=APPLICATION_STATUS_PENDING,
                                     choices=APPLICATION_STATUS_CHOICES)
    remarks = StringField(default="")            # rejection reason / review note
    applied_on = DateTimeField(default=now_utc)
    reviewed_on = DateTimeField()
    reviewed_by = ObjectIdField()                # approving/rejecting super admin

    def save(self, *args, **kwargs):
        if not self.application_id:
            from apps.core.utils import generate_code
            self.application_id = generate_code("APP")
        return super().save(*args, **kwargs)

    def to_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "user_id": str(self.user_id),
            "role_requested": self.role_requested,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "department": self.department,
            "employee_id": self.employee_id,
            "office_name": self.office_name,
            "office_address": self.office_address,
            "government_id_document": self.government_id_document,
            "employee_card": self.employee_card,
            "profile_photo": self.profile_photo,
            "face_registered": self.face_registered,
            "face_images_count": self.face_images_count,
            "application_status": self.application_status,
            "remarks": self.remarks,
            "applied_on": self.applied_on,
            "reviewed_on": self.reviewed_on,
            "reviewed_by": str(self.reviewed_by) if self.reviewed_by else None,
        }

    def __str__(self):
        return f"{self.application_id} {self.full_name} ({self.role_requested})"


class Notification(Document):
    """In-app dashboard notification delivered to a user."""

    meta = {
        "collection": "notifications",
        "indexes": ["user_id", "-created_at", "is_read"],
        "ordering": ["-created_at"],
    }

    user_id = ObjectIdField(required=True)
    title = StringField(default="")
    message = StringField(default="")
    kind = StringField(default="info")          # application_submitted/approved/rejected/face_reset/password_changed/info
    is_read = BooleanField(default=False)
    created_at = DateTimeField(default=now_utc)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "title": self.title,
            "message": self.message,
            "kind": self.kind,
            "is_read": self.is_read,
            "created_at": self.created_at,
        }


class LoginHistory(Document):
    """Record of every login attempt, including face authentication results."""

    meta = {
        "collection": "login_history",
        "indexes": ["user_id", "-created_at", "success"],
        "ordering": ["-created_at"],
    }

    user_id = ObjectIdField()
    email = StringField(default="")
    method = StringField(default="password")    # password / password+face
    success = BooleanField(default=False)
    face_score = FloatField()                    # similarity 0-1 when face used
    ip = StringField(default="")
    user_agent = StringField(default="")
    detail = StringField(default="")
    created_at = DateTimeField(default=now_utc)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "email": self.email,
            "method": self.method,
            "success": self.success,
            "face_score": self.face_score,
            "ip": self.ip,
            "user_agent": self.user_agent,
            "detail": self.detail,
            "created_at": self.created_at,
        }


class AuditLog(Document):
    """Administrative audit trail (RBAC-governed actions by admins)."""

    meta = {
        "collection": "audit_logs",
        "indexes": ["actor_id", "-created_at", "action"],
        "ordering": ["-created_at"],
    }

    actor_id = ObjectIdField()                   # super admin who performed the action
    actor_email = StringField(default="")
    action = StringField(default="")             # e.g. application.approve, user.deactivate
    target_type = StringField(default="")        # application / user / complaint
    target_id = StringField(default="")
    details = DictField(default=dict)            # arbitrary structured context
    created_at = DateTimeField(default=now_utc)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "actor_email": self.actor_email,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "details": self.details,
            "created_at": self.created_at,
        }
