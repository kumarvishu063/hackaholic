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

    def test_liveness_relaxed_blink_or_head_turn(self):
        """Relaxed mode: a single gesture (blink OR head-turn) is enough."""
        from apps.authentication import face_auth
        # Blink only
        ok, _ = face_auth.validate_liveness({
            "liveness_score": 80, "blink_count": 1, "samples": 2, "head_turn_done": False,
        })
        self.assertTrue(ok)
        # Head-turn only
        ok, _ = face_auth.validate_liveness({
            "liveness_score": 80, "blink_count": 0, "samples": 2, "head_turn_done": True,
        })
        self.assertTrue(ok)
        # Neither gesture → rejected even with a high reported score
        bad, _ = face_auth.validate_liveness({
            "liveness_score": 90, "blink_count": 0, "samples": 2, "head_turn_done": False,
        })
        self.assertFalse(bad)

    def test_liveness_strict_requires_both(self):
        """Strict mode keeps the original blink AND head-turn requirement."""
        from apps.authentication import face_auth
        from django.test import override_settings
        with override_settings(FACE_LIVENESS_MODE="strict"):
            ok, _ = face_auth.validate_liveness({
                "liveness_score": 85, "blink_count": 2, "samples": 6, "head_turn_done": True,
            })
            self.assertTrue(ok)
            # Blink without head-turn fails in strict mode
            bad, _ = face_auth.validate_liveness({
                "liveness_score": 85, "blink_count": 2, "samples": 6, "head_turn_done": False,
            })
            self.assertFalse(bad)

    def test_analyze_frame_shape(self):
        """analyze_frame always returns the full result contract."""
        from apps.authentication import face_auth
        png = face_auth._png_bytes_from_raw(64, 64, 128)
        result = face_auth.analyze_frame(png)
        self.assertIn("ok", result)
        self.assertIn("faces", result)
        self.assertIn("error", result)
        self.assertIn("brightness", result)
        self.assertIsInstance(result["ok"], bool)
        self.assertIsInstance(result["faces"], int)
        # Contract: errored analyses carry a known error code and no embedding;
        # successful ones always yield an embedding.
        if result["ok"]:
            self.assertIsNotNone(result["embedding"])
        else:
            self.assertIn(result["error"], ("no_face", "multiple_faces", "low_light", "undecodable"))
            self.assertIsNone(result["embedding"])

    def test_engine_status_is_resolved(self):
        from apps.authentication import face_auth
        self.assertIn(face_auth.engine_status(), ("opencv", "mock", "deepface", "face_recognition"))

    def test_match_reports_dimension_mismatch(self):
        """A profile created with a different model must not silently pass."""
        from apps.authentication import face_auth
        blob = face_auth.encrypt_embedding([0.5] * 10)
        result = face_auth.match_embeddings(blob, [0.5] * 64)
        self.assertFalse(result["matched"])
        self.assertEqual(result["confidence"], 0.0)
        self.assertIn("re-register", result["reason"].lower())

    def test_demo_embedding_stable(self):
        from apps.authentication import face_auth
        a = face_auth.demo_embedding()
        b = face_auth.demo_embedding()
        # Fernet ciphertexts differ (timestamp salt) but decrypt to the same vector.
        self.assertEqual(face_auth.decrypt_embedding(a), face_auth.decrypt_embedding(b))
        self.assertIsNotNone(face_auth.decrypt_embedding(a))


class AuthEndpointStaleTokenTests(SimpleTestCase):
    """Ensure login and registration work even when a stale/invalid Authorization header is sent."""

    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()

    def test_login_with_invalid_bearer_token(self):
        # Create a user
        email = "stale.test@example.com"
        User.objects(email=email).delete()
        user = User(full_name="Stale Test", email=email, role="citizen", account_status="ACTIVE")
        user.set_password("Password123")
        user.save()

        try:
            # Set invalid Authorization header
            self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid.expired.token")
            response = self.client.post("/api/auth/login/", {"identifier": email, "password": "Password123"})
            self.assertEqual(response.status_code, 200)
            self.assertIn("access_token", response.data)
        finally:
            user.delete()

    def test_register_with_invalid_bearer_token(self):
        email = "stale.reg@example.com"
        User.objects(email=email).delete()

        try:
            # Set invalid Authorization header
            self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid.expired.token")
            response = self.client.post("/api/auth/register/", {
                "full_name": "Stale Reg",
                "email": email,
                "password": "Password123",
                "confirm_password": "Password123",
                "role": "citizen"
            })
            self.assertEqual(response.status_code, 201)
            self.assertIn("access_token", response.data)
        finally:
            User.objects(email=email).delete()

