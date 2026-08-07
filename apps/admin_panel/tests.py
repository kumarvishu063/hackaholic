"""
Integration tests for the Super Admin approval + face authentication workflow.

Run against the in-memory mongomock engine:
    MONGODB_URI=mongomock://localhost/jansetu_test python manage.py test apps.admin_panel
"""

import base64
import io
import struct
import zlib

from django.core.management import call_command
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.authentication import face_auth
from apps.authentication.authentication import create_access_token
from apps.authentication.models import User


def _tiny_png_bytes(value: int = 128) -> bytes:
    """Minimal valid PNG (not a real face — FACE_DEMO_MODE relaxes detection)."""
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 64, 64, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([value]) * 64 for _ in range(64))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _data_uri(value: int = 128) -> str:
    return "data:image/png;base64," + base64.b64encode(_tiny_png_bytes(value)).decode()


class ApprovalWorkflowTests(APITestCase):
    """End-to-end: citizen/admin access, applications, approve/reject, face."""

    def setUp(self):
        call_command("seed_data", verbosity=0)
        self.png = _tiny_png_bytes()
        self.uri = _data_uri()
        self.client = APIClient()
        login = self.client.post("/api/auth/login/",
                                 {"identifier": "admin@example.com", "password": "Admin@123"})
        self.admin_token = login.data["access_token"]

    # ------------------------------------------------------------------ apps
    def test_admin_dashboard_stats(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.admin_token)
        r = self.client.get("/api/admin/dashboard/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(r.data["total_citizens"], 1)
        self.assertIn("pending_validators", r.data)

    def test_admin_required(self):
        # A citizen must not reach admin endpoints.
        login = self.client.post("/api/auth/login/",
                                 {"identifier": "citizen@example.com", "password": "Citizen@123"})
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + login.data["access_token"])
        r = self.client.get("/api/admin/dashboard/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_application_lifecycle(self):
        # 1. Submit a validator application (with documents + face frames).
        r = self.client.post("/api/auth/register/", {
            "full_name": "App Validator", "email": "appv@example.com", "username": "appv",
            "phone": "+919800000050", "role": "validator", "department": "Water Supply",
            "employee_id": "WV-01", "office_name": "Civic Office", "office_address": "Pune",
            "password": "Passw0rd123", "confirm_password": "Passw0rd123",
            "government_id_document": io.BytesIO(self.png),
            "employee_card": io.BytesIO(self.png),
            "profile_photo": io.BytesIO(self.png),
            "face_images": [io.BytesIO(self.png) for _ in range(5)],
        }, format="multipart")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["account_status"], "PENDING")
        application_id = r.data["application_id"]
        self.assertTrue(r.data["face_registered"])

        # 2. Pending applicant cannot log in.
        r = self.client.post("/api/auth/login/",
                             {"identifier": "appv@example.com", "password": "Passw0rd123"})
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("under review", r.data["detail"].lower())

        # 3. Admin lists applications (filters) and approves.
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.admin_token)
        r = self.client.get("/api/admin/applications/?status=PENDING")
        ids = {a["application_id"] for a in r.data["results"]}
        self.assertIn(application_id, ids)

        r = self.client.get(f"/api/admin/applications/{application_id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["face_registered"], True)

        r = self.client.patch(f"/api/admin/applications/{application_id}/approve/", {"remarks": "ok"})
        self.assertEqual(r.status_code, status.HTTP_200_OK)

        # 4. Approved user logs in → face challenge → face verify → tokens.
        self.client.credentials()
        r = self.client.post("/api/auth/login/",
                             {"identifier": "appv@example.com", "password": "Passw0rd123"})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["requires_face"])
        face_token = r.data["face_token"]

        r = self.client.post("/api/auth/verify-face/", {
            "face_token": face_token, "image": self.uri,
            "liveness_score": 90, "blink_count": 2, "head_turn_done": True, "samples": 6,
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["access_token"])

    def test_application_rejection_requires_reason(self):
        r = self.client.post("/api/auth/register/", {
            "full_name": "Reject Me", "email": "rej@example.com", "username": "rej",
            "role": "official", "department": "Public Health", "employee_id": "H-9", "office_name": "MOH",
            "password": "Passw0rd123", "confirm_password": "Passw0rd123",
            "government_id_document": io.BytesIO(self.png),
            "employee_card": io.BytesIO(self.png),
            "profile_photo": io.BytesIO(self.png),
        }, format="multipart")
        application_id = r.data["application_id"]

        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.admin_token)
        # Missing remarks → 400.
        r = self.client.patch(f"/api/admin/applications/{application_id}/reject/", {})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

        r = self.client.patch(f"/api/admin/applications/{application_id}/reject/",
                              {"remarks": "Documents could not be verified."})
        self.assertEqual(r.status_code, status.HTTP_200_OK)

        self.client.credentials()
        r = self.client.post("/api/auth/login/",
                             {"identifier": "rej@example.com", "password": "Passw0rd123"})
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("rejected", r.data["detail"].lower())

    # ------------------------------------------------------------------ face
    def test_face_register_and_reset(self):
        # Seed data makes a real validator available for face ops.
        validator = User.objects(email="validator@example.com").first()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.admin_token)
        uid = str(validator.id)

        r = self.client.patch(f"/api/admin/users/{uid}/reset-face/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        validator.reload()
        self.assertFalse(validator.face_registered)

        # Re-register using the face-challenge token (login flow after reset).
        self.client.credentials()
        r = self.client.post("/api/auth/login/",
                             {"identifier": "validator@example.com", "password": "Validator@123"})
        face_token = r.data["face_token"]

        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + face_token)
        r = self.client.post("/api/auth/register-face/",
                             {"images": [self.uri] * 6}, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertTrue(r.data["face_registered"])

        validator.reload()
        self.assertTrue(validator.face_registered)
        self.assertEqual(validator.face_images_count, 6)

    # ------------------------------------------------------------- users
    def test_user_management_actions(self):
        citizen = User.objects(email="citizen@example.com").first()
        uid = str(citizen.id)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.admin_token)

        r = self.client.patch(f"/api/admin/users/{uid}/deactivate/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        citizen.reload()
        self.assertFalse(citizen.is_active)

        r = self.client.patch(f"/api/admin/users/{uid}/activate/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        citizen.reload()
        self.assertTrue(citizen.is_active)

        r = self.client.patch(f"/api/admin/users/{uid}/reset-password/",
                              {"temporary_password": "Temp@12345"})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        citizen.reload()
        self.assertTrue(citizen.check_password("Temp@12345"))

    # ------------------------------------------------------------- reports
    def test_reports_and_audit(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.admin_token)
        r = self.client.get("/api/admin/reports/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("complaints_by_status", r.data)
        self.assertIn("users_by_role", r.data)

        r = self.client.get("/api/admin/audit-logs/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

        r = self.client.get("/api/admin/login-history/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

        r = self.client.get("/api/admin/complaints/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(r.data["count"], 10)
