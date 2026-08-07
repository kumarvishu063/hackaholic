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
    TimelineEntry,
)
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
