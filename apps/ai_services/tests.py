"""Unit tests for the mock AI pipeline and the chatbot (no network)."""

from django.test import Client, SimpleTestCase

from apps.ai_services.chatbot import extract_complaint_id, mock_chat_response
from apps.ai_services.mock_ai import (
    mock_remove_pii,
    mock_summary,
    mock_transcript,
    mock_urgency,
    mock_validate_category,
)
from apps.ai_services.service import process_complaint
from apps.complaints.models import Complaint


class MockAiTests(SimpleTestCase):

    def test_transcript_for_known_category(self):
        text = mock_transcript("Water Supply")
        assert "water" in text.lower()
        assert len(text) > 20

    def test_pii_removal(self):
        dirty = "My name is Raj Kumar and my phone is 9876543210, email raj@example.com"
        clean = mock_remove_pii(dirty)
        assert "9876543210" not in clean
        assert "raj@example.com" not in clean
        assert "[PHONE]" in clean and "[EMAIL]" in clean

    def test_summary_is_concise(self):
        summary = mock_summary("The pothole is very deep and dangerous near the junction.", "Roads & Transport")
        assert len(summary) < 300
        assert "pothole" in summary.lower()

    def test_category_validation(self):
        assert mock_validate_category("street lights are dead for weeks", "Electricity") == "Electricity"
        assert mock_validate_category("unknown issue text", "Other") == "Other"

    def test_urgency_range(self):
        for _ in range(50):
            score = mock_urgency("there was an accident and people are unsafe", "Roads & Transport")
            assert 1 <= score <= 10

    def test_full_pipeline_never_raises(self):
        result = process_complaint("There is a huge pothole near the junction causing accidents.", "Roads & Transport")
        assert result["transcript"]
        assert result["summary"]
        assert result["category"] == "Roads & Transport"
        assert 1 <= result["urgency_score"] <= 10
        assert result["ai_source"] in ("gemini", "mock")


class ChatbotEngineTests(SimpleTestCase):
    """Knowledge-base engine (pure Python, no network)."""

    def test_submit_question_answers_from_kb(self):
        reply = mock_chat_response("How do I file a complaint?")
        assert "Complaint ID" in reply and "Submit Complaint" in reply

    def test_track_question_prompts_for_id(self):
        reply = mock_chat_response("Where is my complaint?")
        assert "JST-" in reply

    def test_localized_answer(self):
        reply = mock_chat_response("शिकायत कैसे दर्ज करें?", language="hi")
        assert "शिकायत" in reply

    def test_status_meanings_quick_question(self):
        reply = mock_chat_response("Complaint status meanings")
        assert "Pending Validation" in reply and "Resolved" in reply

    def test_greeting_keyword(self):
        assert "Hello" in mock_chat_response("Hello")
        assert "मदद" in mock_chat_response("नमस्ते", language="hi")

    def test_extract_complaint_id(self):
        assert extract_complaint_id("Please check JST-AB12CD34 for me") == "JST-AB12CD34"
        assert extract_complaint_id("no id here") is None


class ChatbotApiTests(SimpleTestCase):
    """Live API tests (mongomock engine, no Gemini key in tests)."""

    def setUp(self):
        from bson import ObjectId
        from apps.complaints.models import STATUS_PENDING
        from apps.complaints.services import generate_pin
        self.client = Client()
        self.complaint = Complaint(
            complaint_id="JST-TEST0001",
            citizen_id=ObjectId(),
            category="Water Supply",
            description="No water for three days",
            summary="Water supply disrupted in the area for three days.",
            urgency_score=7,
            status=STATUS_PENDING,
            complaint_pin=generate_pin(),
            sha256_hash="abc",
        )
        self.complaint.save()

    def tearDown(self):
        self.complaint.delete()

    def test_status_lookup_returns_real_data(self):
        resp = self.client.post(
            "/api/chat/",
            data={"message": "What is the status of JST-TEST0001?", "language": "en"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "data"
        assert "JST-TEST0001" in body["reply"]
        assert "Pending Validation" in body["reply"]

    def test_status_lookup_unknown_id(self):
        resp = self.client.post(
            "/api/chat/",
            data={"message": "Track JST-NOPE1234 please", "language": "en"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "data"
        assert "couldn't find" in body["reply"]

    def test_mock_fallback_reply(self):
        resp = self.client.post(
            "/api/chat/",
            data={"message": "How does urgency scoring work?", "language": "en"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "mock"
        assert "1" in body["reply"] and "10" in body["reply"]

    def test_missing_message_is_rejected(self):
        resp = self.client.post(
            "/api/chat/",
            data={"message": "   "},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_hindi_status_lookup(self):
        resp = self.client.post(
            "/api/chat/",
            data={"message": "JST-TEST0001 की स्थिति बताओ", "language": "hi"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert "JST-TEST0001" in resp.json()["reply"]
        assert "सत्यापन लंबित" in resp.json()["reply"]

    def test_transcribe_endpoint_returns_text(self):
        # A tiny valid RIFF/WAVE header is enough for the mock path.
        from django.core.files.uploadedfile import SimpleUploadedFile
        wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00" + b"\x00" * 20
        resp = self.client.post(
            "/api/chat/transcribe/",
            data={"audio": SimpleUploadedFile("voice.wav", wav, content_type="audio/wav")},
            format="multipart",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"].strip()
        assert body["source"] == "mock"

    def test_transcribe_rejects_missing_and_foreign_files(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = self.client.post("/api/chat/transcribe/", data={}, format="multipart")
        assert resp.status_code == 400

        fake = SimpleUploadedFile("evil.wav", b"<script>alert(1)</script>", content_type="audio/wav")
        resp = self.client.post(
            "/api/chat/transcribe/", data={"audio": fake}, format="multipart"
        )
        assert resp.status_code == 400  # magic bytes do not match audio

        empty = SimpleUploadedFile("empty.wav", b"", content_type="audio/wav")
        resp = self.client.post(
            "/api/chat/transcribe/", data={"audio": empty}, format="multipart"
        )
        assert resp.status_code == 400  # empty files are rejected

    def test_stale_or_invalid_token_is_treated_as_anonymous(self):
        # A public widget must never 401 on a bad JWT (it would log the user out).
        from datetime import datetime, timedelta, timezone
        import jwt as pyjwt
        from django.conf import settings

        payload = {
            "user_id": "000000000000000000000000",  # does not exist in the DB
            "role": "citizen",
            "token_type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = pyjwt.encode(payload, settings.JWT_SETTINGS["SECRET_KEY"], algorithm="HS256")

        resp = self.client.post(
            "/api/chat/",
            data={"message": "How do I file a complaint?", "language": "en"},
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + token,
        )
        assert resp.status_code == 200
        assert resp.json()["source"] == "mock"
