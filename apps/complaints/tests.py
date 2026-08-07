"""
Unit tests for the complaints app.

Database-touching tests run against the in-memory mongomock engine:
    MONGODB_URI=mongomock://localhost/jansetu_test python manage.py test
"""

import hashlib
import re

from bson import ObjectId
from django.test import SimpleTestCase

from apps.complaints.models import (
    STATUS_PENDING,
    STATUS_RESOLVED,
    STATUS_VERIFIED,
    Complaint,
    Feedback,
    TimelineEntry,
)
from apps.complaints.serializers import FeedbackCreateSerializer
from apps.complaints.services import compute_sha256, generate_complaint_id, generate_pin


class IdentifierTests(SimpleTestCase):

    def test_complaint_id_format(self):
        cid = generate_complaint_id()
        assert re.fullmatch(r"JST-[A-Z0-9]{8}", cid)

    def test_complaint_ids_are_unique(self):
        ids = {generate_complaint_id() for _ in range(200)}
        assert len(ids) == 200

    def test_pin_is_six_digits(self):
        pin = generate_pin()
        assert re.fullmatch(r"\d{6}", pin)

    def test_sha256_deterministic(self):
        h1 = compute_sha256("JST-ABC123", "123456", "pothole near junction")
        h2 = compute_sha256("JST-ABC123", "123456", "pothole near junction")
        h3 = compute_sha256("JST-ABC123", "123456", "different text")
        assert h1 == h2 == hashlib.sha256(b"JST-ABC123|123456|pothole near junction").hexdigest()
        assert h1 != h3


class ComplaintModelTests(SimpleTestCase):

    def test_workflow_advances_status_and_timeline(self):
        complaint = Complaint(
            complaint_id=generate_complaint_id(),
            citizen_id=ObjectId(),
            category="Water Supply",
            description="No water for three days",
            complaint_pin=generate_pin(),
            sha256_hash="abc",
            status=STATUS_PENDING,
        )
        complaint.save()

        complaint.add_timeline_entry("SUBMITTED", new_status=STATUS_PENDING)
        complaint.add_timeline_entry("VERIFIED", remarks="Looks genuine", new_status=STATUS_VERIFIED)
        complaint.add_timeline_entry("RESOLVED", remarks="Fixed", new_status=STATUS_RESOLVED)
        complaint.save()

        assert complaint.status == STATUS_RESOLVED
        assert len(complaint.timeline) == 3
        assert complaint.timeline[1].remarks == "Looks genuine"
        assert complaint.timeline_dict()[2]["action"] == "RESOLVED"
        complaint.delete()

    def test_default_status_is_pending(self):
        complaint = Complaint(
            complaint_id=generate_complaint_id(),
            citizen_id=ObjectId(),
            category="Other",
            complaint_pin="000000",
            sha256_hash="abc",
        )
        assert complaint.status == STATUS_PENDING


class FeedbackModelTests(SimpleTestCase):

    def _make(self):
        return Feedback(
            complaint_id="JST-TESTFDBK",
            citizen_id=ObjectId(),
            rating=4,
            satisfaction="Good",
            comment="Very prompt resolution of my water supply issue, thank you.",
        )

    def test_save_generates_feedback_id(self):
        fb = self._make()
        fb.save()
        assert fb.feedback_id.startswith("FBK-")
        assert fb.issue_resolved is False
        assert fb.use_again is False
        fb.delete()

    def test_round_trip(self):
        fb = self._make()
        fb.rating = 5
        fb.issue_resolved = True
        fb.save()
        reloaded = Feedback.objects(complaint_id="JST-TESTFDBK").first()
        assert reloaded is not None
        assert reloaded.rating == 5
        assert reloaded.issue_resolved is True
        assert reloaded.satisfaction == "Good"
        reloaded.delete()


class FeedbackSerializerTests(SimpleTestCase):

    VALID = {
        "complaint_id": "JST-ABCD1234",
        "rating": 5,
        "satisfaction": "Excellent",
        "comment": "Fast and transparent resolution, great experience overall.",
        "issue_resolved": True,
        "use_again": True,
    }

    def test_valid_payload(self):
        serializer = FeedbackCreateSerializer(data=self.VALID)
        assert serializer.is_valid(), serializer.errors

    def test_comment_too_short_is_invalid(self):
        data = dict(self.VALID, comment="short")
        serializer = FeedbackCreateSerializer(data=data)
        assert not serializer.is_valid()
        assert "comment" in serializer.errors

    def test_rating_out_of_range_is_invalid(self):
        data = dict(self.VALID, rating=6)
        serializer = FeedbackCreateSerializer(data=data)
        assert not serializer.is_valid()
        assert "rating" in serializer.errors

    def test_defaults_for_optional_questions(self):
        data = {k: v for k, v in self.VALID.items() if k not in ("issue_resolved", "use_again")}
        serializer = FeedbackCreateSerializer(data=data)
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["issue_resolved"] is False
        assert serializer.validated_data["use_again"] is False
