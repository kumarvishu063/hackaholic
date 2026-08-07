"""
Complaint REST endpoints.

GET  /api/complaints/               role-aware list (search/filter/sort/paginate)
POST /api/complaints/               citizen submits a new complaint (multipart)
GET  /api/complaints/<id>/          full details (timeline, AI output, hash)
POST /api/complaints/<id>/validate/ validator verifies or rejects
POST /api/complaints/<id>/resolve/  official marks complaint resolved
GET  /api/analytics/                dashboard statistics per role
"""

import os
import re
from datetime import date, datetime, time, timedelta, timezone

from django.conf import settings
from mongoengine.queryset.visitor import Q
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_services.service import process_complaint
from apps.authentication.models import User
from apps.authentication.permissions import IsCitizen, IsOfficial, IsValidator
from apps.complaints.models import (
    ACTION_REJECTED,
    ACTION_RESOLVED,
    ACTION_SUBMITTED,
    ACTION_VERIFIED,
    CATEGORY_CHOICES,
    STATUS_CHOICES,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_RESOLVED,
    STATUS_VERIFIED,
    Complaint,
    TimelineEntry,
)
from apps.complaints.serializers import (
    ComplaintCreateSerializer,
    ResolveActionSerializer,
    ValidateActionSerializer,
    serialize_detail,
    serialize_list_item,
)
from apps.complaints.services import compute_sha256, generate_complaint_id, generate_pin
from apps.core.pagination import StandardResultsSetPagination
from apps.core.utils import now_utc

# Sort keys exposed to clients (safe allowlist, no injection possible).
# Values are the real document fields; `-` prefixes are handled in the view.
SORT_FIELDS = {
    "created_at": "created_at",
    "urgency": "urgency_score",
    "urgency_score": "urgency_score",
    "status": "status",
}

# Minimal magic-byte checks so a file renamed to `.jpg`/`.wav` can't slip in.
_MAGIC_AUDIO = (b"RIFF", b"OggS", b"ID3", b"\x1aE\xdf\xa3", b"fLaC", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
_MAGIC_PHOTO = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF8", b"RIFF", b"\x00\x00\x01")

AUDIO_EXTENSIONS = (".webm", ".wav", ".mp3", ".ogg", ".m4a", ".mp4")
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _get_complaint_or_404(complaint_id: str) -> Complaint:
    complaint = Complaint.objects(complaint_id=complaint_id).first()
    if complaint is None:
        raise NotFound("Complaint not found.")
    return complaint


def _citizen_names(complaints) -> dict:
    """Map citizen ObjectIds → full names with a single query."""
    ids = {c.citizen_id for c in complaints}
    if not ids:
        return {}
    users = User.objects(id__in=list(ids)).only("id", "full_name")
    return {str(u.id): u.full_name for u in users}


def _save_upload(uploaded_file, relative_dir: str, filename: str) -> str:
    """Persist an uploaded file under MEDIA_ROOT and return its public URL."""
    dest_dir = settings.MEDIA_ROOT / relative_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    with dest.open("wb+") as handle:
        for chunk in uploaded_file.chunks():
            handle.write(chunk)
    return f"{settings.MEDIA_URL}{relative_dir}/{filename}"


def _parse_date(value) -> date | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def apply_complaint_filters(qs, params):
    """Shared free-text / status / category / urgency / date / sort filtering.

    Used by both the role-scoped complaint list and the Super Admin registry.
    """
    # Free-text search across the human readable fields. `icontains`
    # escapes regex metacharacters automatically (no pattern injection).
    query = (params.get("q") or "").strip()
    if query:
        qs = qs(
            Q(complaint_id__icontains=query)
            | Q(description__icontains=query)
            | Q(summary__icontains=query)
            | Q(address__icontains=query)
            | Q(transcript__icontains=query)
        )

    # Exact filters.
    filter_args = {}
    raw_status = (params.get("status") or "").strip().upper()
    if raw_status in STATUS_CHOICES:
        filter_args["status"] = raw_status
    raw_category = (params.get("category") or "").strip()
    if raw_category in CATEGORY_CHOICES:
        filter_args["category"] = raw_category
    if params.get("min_urgency", "").strip().isdigit():
        filter_args["urgency_score__gte"] = int(params["min_urgency"])
    if params.get("max_urgency", "").strip().isdigit():
        filter_args["urgency_score__lte"] = int(params["max_urgency"])
    if filter_args:
        qs = qs(**filter_args)

    # Date range (interpreted in IST, converted to UTC for storage).
    date_from = _parse_date(params.get("date_from"))
    date_to = _parse_date(params.get("date_to"))
    if date_from or date_to:
        try:
            from zoneinfo import ZoneInfo
            ist = ZoneInfo("Asia/Kolkata")
            utc = timezone.utc
            range_args = {}
            if date_from:
                range_args["created_at__gte"] = datetime.combine(date_from, time.min, tzinfo=ist).astimezone(utc)
            if date_to:
                range_args["created_at__lte"] = datetime.combine(date_to, time.max, tzinfo=ist).astimezone(utc)
            qs = qs(**range_args)
        except Exception:
            pass  # never break the list because of a bad timezone

    # Sorting (allowlist — the sort key is rebuilt from the map, so a
    # `-` prefix can never be combined with an arbitrary field name).
    sort_param = (params.get("sort") or "-created_at").strip()
    descending = sort_param.startswith("-")
    field = SORT_FIELDS.get(sort_param[1:] if descending else sort_param)
    if field:
        qs = qs.order_by(f"-{field}" if descending else field)

    return qs


# ---------------------------------------------------------------------------
# List / Create
# ---------------------------------------------------------------------------
class ComplaintListCreateView(APIView):
    """Role-aware listing plus citizen complaint submission."""

    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        # Submissions are citizens-only; listing is open to every role.
        if self.request.method == "POST":
            return [IsCitizen()]
        return [IsAuthenticated()]

    # ------------------------------------------------------------------
    # GET — list
    # ------------------------------------------------------------------
    def get(self, request):
        qs = self._scoped_queryset(request.user)
        qs = apply_complaint_filters(qs, request.query_params)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        items = list(page) if page is not None else []

        names = _citizen_names(items)
        data = [
            serialize_list_item(complaint, names.get(str(complaint.citizen_id), ""))
            for complaint in items
        ]
        return paginator.get_paginated_response(data)

    def _scoped_queryset(self, user):
        """Each role only ever sees the complaints it is allowed to see."""
        qs = Complaint.objects()
        if user.role == "citizen":
            return qs(citizen_id=user.id)
        if user.role == "validator":
            return qs(status=STATUS_PENDING)
        if user.role == "official":
            # Officials manage verified, resolved and rejected complaints.
            return qs(status__in=[STATUS_VERIFIED, STATUS_RESOLVED, STATUS_REJECTED])
        # Super Admin and any other role see the full registry.
        return qs

    # ------------------------------------------------------------------
    # POST — create (multipart)
    # ------------------------------------------------------------------
    def post(self, request):
        audio_file = request.FILES.get("audio")
        photo_file = request.FILES.get("photo")

        self._validate_upload(audio_file, AUDIO_EXTENSIONS, settings.MAX_AUDIO_SIZE, "audio")
        self._validate_upload(photo_file, PHOTO_EXTENSIONS, settings.MAX_PHOTO_SIZE, "photo")

        serializer = ComplaintCreateSerializer(
            data=request.data,
            context={"audio_present": bool(audio_file)},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        complaint_id = generate_complaint_id()
        pin = generate_pin()

        # 1. Persist uploads first so Gemini can read the audio from disk.
        #    Keep the real extension so the served content-type matches.
        audio_url = ""
        if audio_file:
            _, audio_ext = os.path.splitext(audio_file.name)
            audio_url = _save_upload(audio_file, f"complaints/{complaint_id}", f"audio{audio_ext.lower() or '.webm'}")
        photo_url = ""
        if photo_file:
            _, ext = os.path.splitext(photo_file.name)
            photo_url = _save_upload(photo_file, f"complaints/{complaint_id}", f"photo{ext.lower() or '.jpg'}")

        audio_path = None
        if audio_url:
            audio_path = str(settings.MEDIA_ROOT / audio_url.replace(settings.MEDIA_URL, "", 1))

        # 2. AI processing (Gemini with automatic mock fallback).
        ai = process_complaint(
            description=data.get("description", ""),
            category=data["category"],
            audio_path=audio_path,
        )

        # 3. Build the complaint with integrity artefacts.
        description = data.get("description", "")
        complaint = Complaint(
            complaint_id=complaint_id,
            citizen_id=request.user.id,
            category=ai["category"] or data["category"],
            description=description,
            audio=audio_url,
            photo=photo_url,
            transcript=ai["transcript"],
            summary=ai["summary"],
            urgency_score=ai["urgency_score"],
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            address=data.get("address", ""),
            status=STATUS_PENDING,
            complaint_pin=pin,
            sha256_hash=compute_sha256(complaint_id, pin, description),
            ai_processed=True,
            ai_source=ai["ai_source"],
        )
        complaint.add_timeline_entry(ACTION_SUBMITTED, actor=request.user)
        complaint.save()

        return Response(
            serialize_detail(complaint, citizen_name=request.user.full_name, show_pin=True),
            status=status.HTTP_201_CREATED,
        )

    def _validate_upload(self, uploaded_file, extensions, size_limit, kind):
        """Reject files that are too large or have an unexpected type.

        Checks both the filename extension and the file's magic bytes, so a
        renamed script/HTML file cannot be stored and served as media.
        """
        if uploaded_file is None:
            return
        if uploaded_file.size > size_limit:
            raise ValidationError(
                {kind: f"{kind.title()} file exceeds the {size_limit // (1024 * 1024)} MB limit."}
            )
        name = (uploaded_file.name or "").lower()
        if not name.endswith(extensions):
            raise ValidationError(
                {kind: f"Unsupported {kind} file type. Allowed: {', '.join(extensions)}"}
            )
        head = uploaded_file.read(12)
        uploaded_file.seek(0)
        magic = _MAGIC_AUDIO if kind == "audio" else _MAGIC_PHOTO
        if not any(head.startswith(sig) for sig in magic):
            raise ValidationError({kind: f"{kind.title()} file content does not match its type."})


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------
class ComplaintDetailView(APIView):
    """Full complaint details with timeline, AI output and integrity hash."""

    permission_classes = [IsAuthenticated]

    def get(self, request, complaint_id):
        complaint = _get_complaint_or_404(complaint_id)

        # Citizens may only view their own complaints.
        if request.user.role == "citizen" and complaint.citizen_id != request.user.id:
            raise PermissionDenied("You can only view your own complaints.")

        citizen = User.objects(id=complaint.citizen_id).first()
        return Response(
            serialize_detail(
                complaint,
                citizen_name=citizen.full_name if citizen else "",
                show_pin=request.user.role == "citizen",
            )
        )


# ---------------------------------------------------------------------------
# Validation (validator role)
# ---------------------------------------------------------------------------
class ValidateComplaintView(APIView):
    """Verify or reject a pending complaint and attach remarks."""

    permission_classes = [IsValidator]

    def post(self, request, complaint_id):
        complaint = _get_complaint_or_404(complaint_id)
        if complaint.status != STATUS_PENDING:
            raise ValidationError("Only complaints in 'Pending Validation' can be reviewed.")

        serializer = ValidateActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]
        remarks = (serializer.validated_data.get("remarks") or "").strip()

        if action == "verify":
            complaint.add_timeline_entry(ACTION_VERIFIED, remarks=remarks, actor=request.user, new_status=STATUS_VERIFIED)
        else:
            complaint.add_timeline_entry(ACTION_REJECTED, remarks=remarks, actor=request.user, new_status=STATUS_REJECTED)
        complaint.validator_remarks = remarks
        complaint.save()

        citizen = User.objects(id=complaint.citizen_id).first()
        return Response(
            serialize_detail(complaint, citizen_name=citizen.full_name if citizen else "", show_pin=False)
        )


# ---------------------------------------------------------------------------
# Resolution (official role)
# ---------------------------------------------------------------------------
class ResolveComplaintView(APIView):
    """Mark a verified complaint as resolved."""

    permission_classes = [IsOfficial]

    def post(self, request, complaint_id):
        complaint = _get_complaint_or_404(complaint_id)
        if complaint.status != STATUS_VERIFIED:
            raise ValidationError("Only verified complaints can be marked as resolved.")

        serializer = ResolveActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        remarks = (serializer.validated_data.get("remarks") or "").strip()

        complaint.official_remarks = remarks
        complaint.add_timeline_entry(ACTION_RESOLVED, remarks=remarks, actor=request.user, new_status=STATUS_RESOLVED)
        complaint.save()

        citizen = User.objects(id=complaint.citizen_id).first()
        return Response(
            serialize_detail(complaint, citizen_name=citizen.full_name if citizen else "", show_pin=False)
        )


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
class AnalyticsView(APIView):
    """Dashboard statistics scoped to the requesting user's role."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        role = request.user.role

        # Citizens only see their own complaints; other roles see the registry.
        scope = Complaint.objects()
        if role == "citizen":
            scope = scope(citizen_id=request.user.id)

        # Validators review the pending queue, but their dashboard also shows
        # system-wide verified/rejected counts — so status counts come from the
        # full scope, while queue-specific metrics come from the pending set.
        queue = scope(status=STATUS_PENDING) if role == "validator" else scope

        total = queue.count()
        by_status = {s: scope(status=s).count() for s in STATUS_CHOICES}

        # Category breakdown (distinct + per-category counts).
        categories = list(queue.distinct("category"))
        by_category = {c: queue(category=c).count() for c in categories}

        # Average urgency of the visible queue (fetch only the score column).
        scores = [c.urgency_score for c in queue.only("urgency_score")]
        avg_urgency = round(sum(scores) / len(scores), 1) if scores else 0

        # Last-7-days trend (arrivals to the visible queue).
        trend = {}
        today = now_utc().date()
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            start = datetime.combine(day, time.min, tzinfo=timezone.utc)
            trend[day.isoformat()] = queue(created_at__gte=start, created_at__lt=start + timedelta(days=1)).count()

        return Response({
            "role": role,
            "total": total,
            "by_status": by_status,
            "by_category": by_category,
            "avg_urgency": avg_urgency,
            "trend": trend,
            "generated_at": now_utc(),
        })
