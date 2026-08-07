"""
Seed demo data so the application is immediately usable:
  • Four users (citizen / validator / official / super_admin)
  • Ten sample complaints covering every status in the workflow

Usage:
    python manage.py seed_data

Runs against whatever MongoDB is configured via MONGODB_URI. The command is
idempotent — re-running it replaces the demo records.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from apps.ai_services.mock_ai import MOCK_TRANSCRIPTS
from apps.authentication import face_auth
from apps.authentication.models import (
    ACCOUNT_STATUS_APPROVED,
    ACCOUNT_STATUS_ACTIVE,
    APPLICATION_STATUS_APPROVED,
    Application,
    User,
)
from apps.complaints.models import Complaint, TimelineEntry
from apps.complaints.services import (
    compute_sha256,
    generate_complaint_id,
    generate_pin,
)
from apps.core.utils import generate_code, now_utc

DEMO_USERS = [
    {"full_name": "Aarav Sharma", "email": "citizen@example.com", "username": "aarav",
     "phone": "+919876543210", "password": "Citizen@123", "role": "citizen",
     "account_status": ACCOUNT_STATUS_ACTIVE},
    {"full_name": "Priya Iyer", "email": "validator@example.com", "username": "priya",
     "phone": "+919812345670", "password": "Validator@123", "role": "validator",
     "account_status": ACCOUNT_STATUS_APPROVED, "department": "Urban Development",
     "employee_id": "UD-009812", "office_name": "Bengaluru Civic Office"},
    {"full_name": "Rohan Mehta", "email": "official@example.com", "username": "rohan",
     "phone": "+919845678901", "password": "Official@123", "role": "official",
     "account_status": ACCOUNT_STATUS_APPROVED, "department": "Public Works",
     "employee_id": "PW-004211", "office_name": "Municipal Corporation"},
    {"full_name": "Aditi Rao", "email": "admin@example.com", "username": "admin",
     "phone": "+919800000001", "password": "Admin@123", "role": "super_admin",
     "account_status": ACCOUNT_STATUS_ACTIVE},
]

SAMPLE_COMPLAINTS = [
    {
        "category": "Roads & Transport",
        "description": "There is a large pothole near the MG Road junction causing accidents every evening. It has been there for over a month.",
        "address": "MG Road Junction, Bengaluru, Karnataka 560001",
        "latitude": 12.9756, "longitude": 77.6044,
        "urgency": 8, "status": "PENDING_VALIDATION",
        "validator_remarks": "", "official_remarks": "",
        "created_days_ago": 0,
    },
    {
        "category": "Water Supply",
        "description": "No water supply in Sector 4 for the last 3 days. Residents are facing severe hardship.",
        "address": "Sector 4, HSR Layout, Bengaluru, Karnataka",
        "latitude": 12.9121, "longitude": 77.6446,
        "urgency": 9, "status": "PENDING_VALIDATION",
        "validator_remarks": "", "official_remarks": "",
        "created_days_ago": 1,
    },
    {
        "category": "Electricity",
        "description": "The street light near the children's park has not worked for 2 weeks, making the area unsafe at night.",
        "address": "Near Children's Park, Indiranagar, Bengaluru",
        "latitude": 12.9784, "longitude": 77.6408,
        "urgency": 6, "status": "PENDING_VALIDATION",
        "validator_remarks": "", "official_remarks": "",
        "created_days_ago": 2,
    },
    {
        "category": "Sanitation & Garbage",
        "description": "Garbage has not been collected from our street for over a week. The bins are overflowing.",
        "address": "12th Main Road, Koramangala, Bengaluru",
        "latitude": 12.9352, "longitude": 77.6245,
        "urgency": 7, "status": "VERIFIED",
        "validator_remarks": "Verified with location photos. Municipality area confirmed.",
        "official_remarks": "",
        "created_days_ago": 3,
    },
    {
        "category": "Public Health",
        "description": "Stagnant water in open drains is breeding mosquitoes. Cases of dengue are rising in the area.",
        "address": "Drain near Bus Stop, Jayanagar, Bengaluru",
        "latitude": 12.9250, "longitude": 77.5938,
        "urgency": 9, "status": "VERIFIED",
        "validator_remarks": "Verified. Health department notified.",
        "official_remarks": "",
        "created_days_ago": 4,
    },
    {
        "category": "Education",
        "description": "The roof of the government primary school leaks during rain and classes are disrupted.",
        "address": "Government Primary School, Rajajinagar, Bengaluru",
        "latitude": 12.9921, "longitude": 77.5531,
        "urgency": 5, "status": "VERIFIED",
        "validator_remarks": "Verified. School records match complaint.",
        "official_remarks": "",
        "created_days_ago": 5,
    },
    {
        "category": "Police & Safety",
        "description": "An abandoned vehicle has been blocking the narrow lane for a month. It is a safety hazard.",
        "address": "4th Cross Lane, Malleshwaram, Bengaluru",
        "latitude": 13.0035, "longitude": 77.5709,
        "urgency": 4, "status": "RESOLVED",
        "validator_remarks": "Verified and forwarded to traffic police.",
        "official_remarks": "Vehicle towed. Lane is now clear.",
        "created_days_ago": 6,
    },
    {
        "category": "Environment",
        "description": "Trees near the lake are being cut illegally. Please stop the deforestation immediately.",
        "address": "Ulsoor Lake Side, Bengaluru",
        "latitude": 12.9803, "longitude": 77.6205,
        "urgency": 8, "status": "RESOLVED",
        "validator_remarks": "Verified. Forest department involved.",
        "official_remarks": "Cutting stopped and offenders fined.",
        "created_days_ago": 7,
    },
    {
        "category": "Roads & Transport",
        "description": "The footpath tiles on the main road are broken and people keep tripping.",
        "address": "Main Road, Whitefield, Bengaluru",
        "latitude": 12.9698, "longitude": 77.7500,
        "urgency": 3, "status": "REJECTED",
        "validator_remarks": "Rejected: area falls under private layout maintenance, not civic body.",
        "official_remarks": "",
        "created_days_ago": 8,
    },
    {
        "category": "Electricity",
        "description": "Frequent power fluctuations are damaging home appliances in the colony.",
        "address": "Green Park Colony, Yeshwanthpur, Bengaluru",
        "latitude": 13.0287, "longitude": 77.5411,
        "urgency": 6, "status": "REJECTED",
        "validator_remarks": "Rejected: no evidence of fluctuation; residents advised to contact supply board directly.",
        "official_remarks": "",
        "created_days_ago": 9,
    },
]


def _status_flow(status: str, validator_name: str, official_name: str):
    """Return the ordered timeline entries for a complaint's lifecycle."""
    steps = [("SUBMITTED", "", "Citizen")]
    if status in ("VERIFIED", "RESOLVED"):
        steps.append(("VERIFIED", "", validator_name))
    if status == "RESOLVED":
        steps.append(("RESOLVED", "", official_name))
    if status == "REJECTED":
        steps.append(("REJECTED", "", validator_name))
    return steps


class Command(BaseCommand):
    help = "Seed demo users and sample complaints for JanSetu."

    def handle(self, *args, **options):
        self.stdout.write("Seeding JanSetu demo data …")
        try:
            self._seed_users()
            self._seed_complaints()
        except Exception as exc:  # e.g. Mongo not running
            raise CommandError(
                f"Could not connect to MongoDB ({type(exc).__name__}: {exc}). "
                "Start MongoDB locally or set MONGODB_URI to a running Atlas/local instance."
            )
        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))

    # ------------------------------------------------------------------
    def _seed_users(self):
        self.stdout.write("  → users")
        Application.objects().delete()
        for info in DEMO_USERS:
            User.objects(email=info["email"]).delete()
            user = User(
                full_name=info["full_name"],
                email=info["email"],
                username=info.get("username") or None,
                phone=info["phone"],
                role=info["role"],
                department=info.get("department", ""),
                employee_id=info.get("employee_id", ""),
                office_name=info.get("office_name", ""),
                account_status=info["account_status"],
                application_status=APPLICATION_STATUS_APPROVED if info.get("employee_id") else "",
            )
            user.set_password(info["password"])

            # Staff demo accounts carry a (fake) encrypted face so the face-auth
            # pipeline is exercisable. FACE_DEMO_MODE is ON by default in dev.
            if info["role"] in ("validator", "official"):
                user.face_embedding = face_auth.demo_embedding()
                user.face_registered = True
                user.face_images_count = 5
                user.approval_date = now_utc()
            user.save()

            # Back-filled approval record so the admin Applications tab has data.
            if info["role"] in ("validator", "official"):
                admin = User.objects(email="admin@example.com").first()
                Application(
                    application_id=generate_code("APP"),
                    user_id=user.id,
                    role_requested=info["role"],
                    full_name=info["full_name"],
                    email=info["email"],
                    phone=info["phone"],
                    department=info.get("department", ""),
                    employee_id=info.get("employee_id", ""),
                    office_name=info.get("office_name", ""),
                    government_id_document="/media/seed/government_id.png",
                    employee_card="/media/seed/employee_card.png",
                    profile_photo="/media/seed/profile_photo.png",
                    face_registered=True,
                    face_images_count=5,
                    application_status=APPLICATION_STATUS_APPROVED,
                    remarks="Pre-approved demo account",
                    applied_on=now_utc() - timedelta(days=2),
                    reviewed_on=now_utc() - timedelta(days=1),
                    reviewed_by=admin.id if admin else None,
                ).save()

    def _seed_complaints(self):
        self.stdout.write("  → complaints")
        citizen = User.objects(email="citizen@example.com").first()
        validator = User.objects(email="validator@example.com").first()
        official = User.objects(email="official@example.com").first()
        if not citizen or not validator or not official:
            raise CommandError("Seed users missing — run _seed_users first.")

        Complaint.objects(citizen_id=citizen.id).delete()

        for i, item in enumerate(SAMPLE_COMPLAINTS):
            complaint_id = generate_complaint_id()
            pin = generate_pin()
            description = item["description"]
            transcript = MOCK_TRANSCRIPTS.get(item["category"], description)
            created_at = now_utc() - timedelta(days=item["created_days_ago"])

            timeline = []
            for step_index, (action, _remarks, _actor) in enumerate(_status_flow(item["status"], validator.full_name, official.full_name)):
                step_remarks = ""
                if action == "SUBMITTED":
                    step_remarks = "Complaint submitted by citizen."
                elif action in ("VERIFIED", "REJECTED"):
                    step_remarks = item["validator_remarks"]
                elif action == "RESOLVED":
                    step_remarks = item["official_remarks"]
                timeline.append(TimelineEntry(
                    action=action,
                    remarks=step_remarks,
                    actor_name=_actor if step_index == 0 else (validator.full_name if action in ("VERIFIED", "REJECTED") else official.full_name),
                    actor_role="citizen" if action == "SUBMITTED" else ("validator" if action in ("VERIFIED", "REJECTED") else "official"),
                    timestamp=created_at + timedelta(hours=(step_index + 1) * 6),
                ))

            complaint = Complaint(
                complaint_id=complaint_id,
                citizen_id=citizen.id,
                category=item["category"],
                description=description,
                transcript=transcript,
                summary=f"Complaint about {item['category'].lower()} reported by a citizen in the area. {transcript[:120]}…",
                urgency_score=item["urgency"],
                address=item["address"],
                latitude=item["latitude"],
                longitude=item["longitude"],
                status=item["status"],
                validator_remarks=item["validator_remarks"],
                official_remarks=item["official_remarks"],
                complaint_pin=pin,
                sha256_hash=compute_sha256(complaint_id, pin, description),
                ai_processed=True,
                ai_source="mock",
                timeline=timeline,
                created_at=created_at,
                updated_at=created_at + timedelta(hours=6 * len(timeline)),
            )
            complaint.save()

        self.stdout.write(f"  → {len(SAMPLE_COMPLAINTS)} complaints created")
