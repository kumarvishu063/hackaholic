"""
Unit tests for the authentication app.

These touch MongoDB, so run them against the in-memory mongomock engine:

    MONGODB_URI=mongomock://localhost/jansetu_test python manage.py test
"""

from datetime import datetime

from django.test import SimpleTestCase
from mongoengine import errors as mongo_errors
from rest_framework import exceptions

from apps.authentication.authentication import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from apps.authentication.models import User


class UserModelTests(SimpleTestCase):
    """Document-level behaviour: hashing, uniqueness, serialisation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.email = "test.user@example.com"
        User.objects(email=cls.email).delete()

    def test_password_roundtrip(self):
        user = User(full_name="Test User", email=self.email, role="citizen")
        user.set_password("Secret123")
        assert user.check_password("Secret123") is True
        assert user.check_password("wrong") is False
        assert user.password_hash.startswith("$2")  # bcrypt prefix
        user.delete()

    def test_duplicate_email_rejected(self):
        user = User(full_name="First", email=self.email, role="citizen")
        user.set_password("Secret123")
        user.save()
        dup = User(full_name="Second", email=self.email, role="citizen")
        dup.set_password("Secret123")
        with self.assertRaises(mongo_errors.NotUniqueError):
            dup.save()
        user.delete()

    def test_public_dict_excludes_hash(self):
        user = User(full_name="Test User", email=self.email, role="citizen")
        user.set_password("Secret123")
        data = user.public_dict()
        assert "password_hash" not in data
        assert data["role"] == "citizen"
        assert data["id"]


class JwtTests(SimpleTestCase):
    """Token creation, decoding and expiry guard-rails."""

    def setUp(self):
        self.user = User(full_name="JWT Tester", email="jwt@example.com", role="validator")
        self.user.set_password("Secret123")

    def test_access_token_roundtrip(self):
        token = create_access_token(self.user)
        payload = decode_token(token, expected_type="access")
        assert payload["user_id"] == str(self.user.id)
        assert payload["role"] == "validator"
        assert payload["token_type"] == "access"

    def test_refresh_token_cannot_be_used_as_access(self):
        token = create_refresh_token(self.user)
        with self.assertRaises(exceptions.AuthenticationFailed):
            decode_token(token, expected_type="access")

    def test_invalid_token_rejected(self):
        with self.assertRaises(exceptions.AuthenticationFailed):
            decode_token("not.a.jwt", expected_type="access")

    def test_expired_token_rejected(self):
        from apps.authentication import authentication as auth
        from datetime import timedelta, timezone

        original = auth._now
        auth._now = lambda: datetime.now(timezone.utc) - timedelta(days=1)
        try:
            token = create_access_token(self.user)  # already expired at creation
        finally:
            auth._now = original
        with self.assertRaises(exceptions.AuthenticationFailed):
            decode_token(token, expected_type="access")


class FaceAuthServiceTests(SimpleTestCase):
    """Embedding encryption, comparison and liveness gate guard-rails."""

    def test_embedding_encrypt_decrypt_roundtrip(self):
        from apps.authentication import face_auth
        vec = [0.1, -0.2, 0.3, 0.0]
        blob = face_auth.encrypt_embedding(vec)
        out = face_auth.decrypt_embedding(blob)
        self.assertEqual(len(out), len(vec))
        for a, b in zip(vec, out):
            self.assertAlmostEqual(a, b, places=6)
        # Raw vector must never appear in the stored payload.
        self.assertNotIn("0.1", blob)

    def test_decrypt_corrupt_blob_returns_none(self):
        from apps.authentication import face_auth
        self.assertIsNone(face_auth.decrypt_embedding("not-an-encrypted-blob"))

    def test_self_match_is_confident(self):
        from apps.authentication import face_auth
        vec = [0.5] * 10
        blob = face_auth.encrypt_embedding(vec)
        result = face_auth.match_embeddings(blob, [0.5] * 10)
        self.assertTrue(result["matched"])
        self.assertGreaterEqual(result["confidence"], 90)

    def test_opposite_vector_fails(self):
        from apps.authentication import face_auth
        vec = [0.5] * 10
        blob = face_auth.encrypt_embedding(vec)
        result = face_auth.match_embeddings(blob, [-0.5] * 10)
        self.assertFalse(result["matched"])

    def test_liveness_gate(self):
        from apps.authentication import face_auth
        ok, score = face_auth.validate_liveness({
            "liveness_score": 85, "blink_count": 2, "samples": 6, "head_turn_done": True,
        })
        self.assertTrue(ok)
        bad, _ = face_auth.validate_liveness({
            "liveness_score": 10, "blink_count": 0, "samples": 1, "head_turn_done": False,
        })
        self.assertFalse(bad)

    def test_demo_embedding_stable(self):
        from apps.authentication import face_auth
        a = face_auth.demo_embedding()
        b = face_auth.demo_embedding()
        # Fernet ciphertexts differ (timestamp salt) but decrypt to the same vector.
        self.assertEqual(face_auth.decrypt_embedding(a), face_auth.decrypt_embedding(b))
        self.assertIsNotNone(face_auth.decrypt_embedding(a))
