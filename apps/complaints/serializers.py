"""Serialisation helpers for complaints (explicit, MongoEngine-safe)."""

from rest_framework import serializers

from apps.complaints.models import CATEGORY_CHOICES, SATISFACTION_CHOICES, Complaint, Feedback
from apps.core.utils import utc_to_ist


class ComplaintCreateSerializer(serializers.Serializer):
    """Validates a new-complaint payload (multipart: fields + optional files)."""

    category = serializers.ChoiceField(choices=CATEGORY_CHOICES)
    description = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    latitude = serializers.FloatField(required=False, min_value=-90, max_value=90)
    longitude = serializers.FloatField(required=False, min_value=-180, max_value=180)
    address = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, attrs):
        # A complaint must have *some* content: typed description or audio.
        description = (attrs.get("description") or "").strip()
        audio_present = bool(self.context.get("audio_present"))
        if not description and not audio_present:
            raise serializers.ValidationError(
                {"description": "Please describe the issue or record an audio note."}
            )
        attrs["description"] = description
        return attrs


class ValidateActionSerializer(serializers.Serializer):
    """Validator review payload."""

    action = serializers.ChoiceField(choices=["verify", "reject"])
    remarks = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class ResolveActionSerializer(serializers.Serializer):
    """Official resolution payload."""

    remarks = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class FeedbackCreateSerializer(serializers.Serializer):
    """Validates the citizen feedback payload for a resolved complaint."""

    complaint_id = serializers.CharField()
    rating = serializers.IntegerField(min_value=1, max_value=5)
    satisfaction = serializers.ChoiceField(choices=SATISFACTION_CHOICES)
    comment = serializers.CharField(min_length=20, max_length=500)
    issue_resolved = serializers.BooleanField(required=False, default=False)
    use_again = serializers.BooleanField(required=False, default=False)


# ---------------------------------------------------------------------------
# Output builders
# ---------------------------------------------------------------------------
def _base_payload(complaint: Complaint, citizen_name: str) -> dict:
    """Fields shared by list items and the detail view."""
    return {
        "complaint_id": complaint.complaint_id,
        "category": complaint.category,
        "description": complaint.description,
        "status": complaint.status,
        "status_label": complaint.status.replace("_", " ").title(),
        "urgency_score": complaint.urgency_score,
        "address": complaint.address,
        "latitude": complaint.latitude,
        "longitude": complaint.longitude,
        "audio_url": complaint.audio,
        "photo_url": complaint.photo,
        "citizen_name": citizen_name,
        "created_at": utc_to_ist(complaint.created_at),
        "updated_at": utc_to_ist(complaint.updated_at),
    }


def serialize_list_item(complaint: Complaint, citizen_name: str = "") -> dict:
    """Compact representation used in list responses."""
    return _base_payload(complaint, citizen_name)


def serialize_detail(complaint: Complaint, citizen_name: str = "", show_pin: bool = False) -> dict:
    """Full representation used in detail responses."""
    payload = _base_payload(complaint, citizen_name)
    payload.update({
        "transcript": complaint.transcript,
        "summary": complaint.summary,
        "ai_processed": complaint.ai_processed,
        "ai_source": complaint.ai_source,
        "validator_remarks": complaint.validator_remarks,
        "official_remarks": complaint.official_remarks,
        "timeline": complaint.timeline_dict(),
        # The PIN is only ever returned to the complaint's own citizen.
        "complaint_pin": complaint.complaint_pin if show_pin else None,
        "sha256_hash": complaint.sha256_hash,
    })
    return payload


def serialize_feedback(feedback: Feedback) -> dict:
    """Compact representation of a single citizen feedback record."""
    return {
        "feedback_id": feedback.feedback_id,
        "complaint_id": feedback.complaint_id,
        "rating": feedback.rating,
        "satisfaction": feedback.satisfaction,
        "comment": feedback.comment,
        "issue_resolved": feedback.issue_resolved,
        "use_again": feedback.use_again,
        "created_at": utc_to_ist(feedback.created_at),
    }
