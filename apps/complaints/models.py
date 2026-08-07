"""
Complaint document and embedded timeline model.

Workflow:  SUBMITTED → PENDING_VALIDATION → VERIFIED → RESOLVED
                                              └→ REJECTED
"""

from mongoengine import (
    BooleanField,
    DateTimeField,
    Document,
    EmbeddedDocument,
    EmbeddedDocumentField,
    FloatField,
    IntField,
    ListField,
    ObjectIdField,
    StringField,
)

from apps.core.utils import now_utc

# Canonical complaint categories (validated by AI too).
CATEGORY_CHOICES = [
    "Roads & Transport",
    "Water Supply",
    "Electricity",
    "Sanitation & Garbage",
    "Public Health",
    "Education",
    "Police & Safety",
    "Environment",
    "Other",
]

# Status lifecycle.
STATUS_PENDING = "PENDING_VALIDATION"
STATUS_VERIFIED = "VERIFIED"
STATUS_REJECTED = "REJECTED"
STATUS_RESOLVED = "RESOLVED"

STATUS_CHOICES = [STATUS_PENDING, STATUS_VERIFIED, STATUS_REJECTED, STATUS_RESOLVED]

# Human friendly labels used by the frontend (also translated client-side).
STATUS_LABELS = {
    STATUS_PENDING: "Pending Validation",
    STATUS_VERIFIED: "Verified",
    STATUS_REJECTED: "Rejected",
    STATUS_RESOLVED: "Resolved",
}

# Timeline actions.
ACTION_SUBMITTED = "SUBMITTED"
ACTION_VERIFIED = "VERIFIED"
ACTION_REJECTED = "REJECTED"
ACTION_RESOLVED = "RESOLVED"


class TimelineEntry(EmbeddedDocument):
    """A single event in the complaint lifecycle."""

    action = StringField(required=True)      # SUBMITTED / VERIFIED / REJECTED / RESOLVED
    remarks = StringField(default="")
    actor_name = StringField(default="")
    actor_role = StringField(default="")     # citizen / validator / official
    timestamp = DateTimeField(default=now_utc)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "remarks": self.remarks,
            "actor_name": self.actor_name,
            "actor_role": self.actor_role,
            "timestamp": self.timestamp,
        }


class Complaint(Document):
    """A citizen grievance tracked through validation and resolution."""

    meta = {
        "collection": "complaints",
        "indexes": [
            {"fields": ["complaint_id"], "unique": True},
            "citizen_id",
            "status",
            "category",
            "urgency_score",
            "-created_at",
        ],
        "ordering": ["-created_at"],
    }

    complaint_id = StringField(required=True, unique=True)   # e.g. JST-4K9XM2P7
    citizen_id = ObjectIdField(required=True)                # reference to User
    category = StringField(required=True, choices=CATEGORY_CHOICES)
    description = StringField(default="")

    # AI artefacts
    audio = StringField(default="")          # relative URL, e.g. /media/complaints/.. /audio.webm
    transcript = StringField(default="")     # AI transcription (or mock)
    summary = StringField(default="")        # AI summary
    urgency_score = IntField(min_value=1, max_value=10, default=5)

    # Evidence & location
    photo = StringField(default="")
    latitude = FloatField(min_value=-90, max_value=90)
    longitude = FloatField(min_value=-180, max_value=180)
    address = StringField(default="")

    # Workflow
    status = StringField(required=True, default=STATUS_PENDING, choices=STATUS_CHOICES)
    validator_remarks = StringField(default="")
    official_remarks = StringField(default="")

    # Integrity
    complaint_pin = StringField(required=True)                # 6-digit citizen PIN
    sha256_hash = StringField(required=True)                  # integrity hash

    # AI bookkeeping
    ai_processed = BooleanField(default=False)
    ai_source = StringField(default="")      # "gemini" | "mock"

    # History
    timeline = ListField(EmbeddedDocumentField(TimelineEntry), default=list)

    created_at = DateTimeField(default=now_utc)
    updated_at = DateTimeField(default=now_utc)

    # ------------------------------------------------------------------
    # Workflow helpers
    # ------------------------------------------------------------------
    def add_timeline_entry(self, action: str, remarks: str = "", actor=None,
                           new_status: str | None = None) -> None:
        """Record a lifecycle event and (optionally) advance the status."""
        entry = TimelineEntry(action=action, remarks=remarks, timestamp=now_utc())
        if actor is not None:
            entry.actor_name = actor.full_name
            entry.actor_role = actor.role
        self.timeline.append(entry)
        if new_status:
            self.status = new_status
        self.updated_at = now_utc()

    def timeline_dict(self) -> list:
        return [entry.to_dict() for entry in self.timeline]

    def save(self, *args, **kwargs):
        self.updated_at = now_utc()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.complaint_id} [{self.status}] {self.category}"
