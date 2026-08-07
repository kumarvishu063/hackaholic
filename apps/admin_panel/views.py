"""
Super Admin panel endpoints (all require the `super_admin` role).

Applications:  list / detail / approve / reject
Users:         list / deactivate / activate / reset-face / reset-password
Complaints:    registry (every complaint + detail)
Reports:       aggregates + login history + audit log
"""

import logging

from django.conf import settings
from mongoengine.queryset.visitor import Q
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_panel.serializers import RejectionSerializer, ReviewSerializer
from apps.authentication.models import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_APPROVED,
    ACCOUNT_STATUS_DEACTIVATED,
    ACCOUNT_STATUS_PENDING,
    ACCOUNT_STATUS_REJECTED,
    ACCOUNT_STATUS_SUSPENDED,
    APPLICATION_STATUS_APPROVED,
    APPLICATION_STATUS_PENDING,
    APPLICATION_STATUS_REJECTED,
    Application,
    AuditLog,
    LoginHistory,
    Notification,
    User,
)
from apps.authentication.permissions import IsSuperAdmin
from apps.authentication.services import (
    create_notification,
    log_audit,
    notify_application_approved,
    notify_application_rejected,
    notify_face_reset,
)
from apps.complaints.models import STATUS_CHOICES, Complaint
from apps.core.pagination import StandardResultsSetPagination
from apps.core.utils import now_utc

logger = logging.getLogger(__name__)

STAFF_ROLE_LABELS = {"validator": "Validator", "official": "Official"}


def _get_application_or_404(application_id: str) -> Application:
    application = Application.objects(application_id=application_id).first()
    if application is None:
        raise NotFound("Application not found.")
    return application


def _get_user_or_404(user_id: str) -> User:
    user = User.objects(id=user_id).first()
    if user is None:
        raise NotFound("User not found.")
    return user


def _id_from(request, url_value, param: str) -> str:
    """Return the id from the URL path or fall back to the request body.

    Lets the same view serve both RESTful (`/users/<id>/reset-face/`) and the
    spec's flat (`PATCH /reset-face/ {user_id}`) URL shapes.
    """
    if url_value:
        return url_value
    body_id = (request.data.get(param) or request.data.get("id") or "").strip()
    if not body_id:
        raise ValidationError(f"{param} is required.")
    return body_id


# ---------------------------------------------------------------------------
# Dashboard statistics
# ---------------------------------------------------------------------------
class AdminDashboardView(APIView):
    """Aggregate statistics for the Super Admin home page."""

    permission_classes = [IsSuperAdmin]

    def get(self, request):
        by_role = {
            role: User.objects(role=role).count()
            for role in ("citizen", "validator", "official", "super_admin")
        }
        pending_validators = User.objects(role="validator", account_status=ACCOUNT_STATUS_PENDING).count()
        pending_officials = User.objects(role="official", account_status=ACCOUNT_STATUS_PENDING).count()
        approved_validators = User.objects(role="validator", account_status=ACCOUNT_STATUS_APPROVED).count()
        approved_officials = User.objects(role="official", account_status=ACCOUNT_STATUS_APPROVED).count()
        rejected = User.objects(account_status=ACCOUNT_STATUS_REJECTED).count()
        suspended = User.objects(account_status__in=[ACCOUNT_STATUS_SUSPENDED, ACCOUNT_STATUS_DEACTIVATED]).count()

        complaint_by_status = {
            s: Complaint.objects(status=s).count() for s in STATUS_CHOICES
        }
        total_complaints = Complaint.objects().count()

        pending_applications = Application.objects(
            application_status=APPLICATION_STATUS_PENDING
        ).count()

        # Recent signups & activity for the admin feed.
        recent_users = list(
            User.objects().order_by("-created_at").limit(6)
        )
        recent_audit = list(AuditLog.objects().limit(8))

        return Response({
            "total_citizens": by_role.get("citizen", 0),
            "total_validators": by_role.get("validator", 0),
            "total_officials": by_role.get("official", 0),
            "total_super_admins": by_role.get("super_admin", 0),
            "pending_validators": pending_validators,
            "pending_officials": pending_officials,
            "pending_applications": pending_applications,
            "approved_validators": approved_validators,
            "approved_officials": approved_officials,
            "rejected_applications": rejected,
            "suspended_accounts": suspended,
            "total_complaints": total_complaints,
            "resolved_complaints": complaint_by_status.get("RESOLVED", 0),
            "pending_complaints": complaint_by_status.get("PENDING_VALIDATION", 0),
            "verified_complaints": complaint_by_status.get("VERIFIED", 0),
            "rejected_complaints": complaint_by_status.get("REJECTED", 0),
            "complaints_by_status": complaint_by_status,
            "recent_users": [u.admin_dict() for u in recent_users],
            "recent_audit": [a.to_dict() for a in recent_audit],
            "generated_at": now_utc(),
        })


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
class ApplicationsListView(APIView):
    """List approval applications, filterable by status, role and query."""

    permission_classes = [IsSuperAdmin]
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        qs = Application.objects()

        raw_status = (request.query_params.get("status") or "").strip().upper()
        if raw_status in (APPLICATION_STATUS_PENDING, APPLICATION_STATUS_APPROVED,
                          APPLICATION_STATUS_REJECTED):
            qs = qs(application_status=raw_status)

        raw_role = (request.query_params.get("role") or "").strip().lower()
        if raw_role in ("validator", "official"):
            qs = qs(role_requested=raw_role)

        query = (request.query_params.get("q") or "").strip()
        if query:
            qs = qs(Q(full_name__icontains=query) | Q(email__icontains=query)
                    | Q(employee_id__icontains=query) | Q(application_id__icontains=query))

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        items = list(page) if page is not None else []
        return paginator.get_paginated_response([a.to_dict() for a in items])


class ApplicationDetailView(APIView):
    """Full detail for one application (documents, face status, review state)."""

    permission_classes = [IsSuperAdmin]

    def get(self, request, application_id=None):
        application_id = _id_from(request, application_id, "application_id")
        application = _get_application_or_404(application_id)
        user = User.objects(id=application.user_id).first()
        payload = application.to_dict()
        payload["user"] = user.admin_dict() if user else None
        return Response(payload)


class ApproveApplicationView(APIView):
    """Approve a pending application → account becomes active + notifications."""

    permission_classes = [IsSuperAdmin]

    def patch(self, request, application_id=None):
        application_id = _id_from(request, application_id, "application_id")
        application = _get_application_or_404(application_id)
        if application.application_status != APPLICATION_STATUS_PENDING:
            raise ValidationError("Only pending applications can be approved.")

        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = (serializer.validated_data.get("remarks") or "").strip()

        user = User.objects(id=application.user_id).first()
        if user is None:
            raise NotFound("The applicant account no longer exists.")

        user.account_status = ACCOUNT_STATUS_APPROVED
        user.application_status = APPLICATION_STATUS_APPROVED
        user.approval_date = now_utc()
        user.approved_by = request.user.id
        user.rejection_reason = ""
        user.save()

        application.application_status = APPLICATION_STATUS_APPROVED
        application.remarks = note
        application.reviewed_on = now_utc()
        application.reviewed_by = request.user.id
        application.save()

        notify_application_approved(user, STAFF_ROLE_LABELS.get(application.role_requested, ""))
        log_audit(request.user, "application.approve", "application",
                  application.application_id, {"email": user.email, "role": user.role})

        return Response({
            "message": f"Application approved. {user.full_name} can now log in.",
            "application": application.to_dict(),
        })


class RejectApplicationView(APIView):
    """Reject a pending application with a mandatory reason."""

    permission_classes = [IsSuperAdmin]

    def patch(self, request, application_id=None):
        application_id = _id_from(request, application_id, "application_id")
        application = _get_application_or_404(application_id)
        if application.application_status != APPLICATION_STATUS_PENDING:
            raise ValidationError("Only pending applications can be rejected.")

        serializer = RejectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data["remarks"].strip()

        user = User.objects(id=application.user_id).first()
        if user is None:
            raise NotFound("The applicant account no longer exists.")

        user.account_status = ACCOUNT_STATUS_REJECTED
        user.application_status = APPLICATION_STATUS_REJECTED
        user.rejection_reason = reason
        user.save()

        application.application_status = APPLICATION_STATUS_REJECTED
        application.remarks = reason
        application.reviewed_on = now_utc()
        application.reviewed_by = request.user.id
        application.save()

        notify_application_rejected(user, STAFF_ROLE_LABELS.get(application.role_requested, ""), reason)
        log_audit(request.user, "application.reject", "application",
                  application.application_id, {"email": user.email, "reason": reason})

        return Response({
            "message": f"Application rejected. {user.full_name} has been notified.",
            "application": application.to_dict(),
        })


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------
class AdminUsersView(APIView):
    """List users (filter by role / status / free-text)."""

    permission_classes = [IsSuperAdmin]
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        qs = User.objects()
        raw_role = (request.query_params.get("role") or "").strip().lower()
        if raw_role in ("citizen", "validator", "official", "super_admin"):
            qs = qs(role=raw_role)
        raw_status = (request.query_params.get("status") or "").strip().upper()
        if raw_status:
            qs = qs(account_status=raw_status)
        query = (request.query_params.get("q") or "").strip()
        if query:
            qs = qs(Q(full_name__icontains=query) | Q(email__icontains=query)
                    | Q(employee_id__icontains=query))

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        items = list(page) if page is not None else []
        return paginator.get_paginated_response([u.admin_dict() for u in items])


class DeactivateUserView(APIView):
    """Deactivate / suspend a user account (no login until re-activated)."""

    permission_classes = [IsSuperAdmin]

    def patch(self, request, user_id=None):
        user_id = _id_from(request, user_id, "user_id")
        user = _get_user_or_404(user_id)
        if user.is_super_admin:
            raise ValidationError("You cannot deactivate a Super Admin account.")

        suspended = request.data.get("suspended", True)
        user.account_status = ACCOUNT_STATUS_SUSPENDED if suspended else ACCOUNT_STATUS_DEACTIVATED
        user.is_active = False
        user.save()

        create_notification(user.id, "Account suspended" if suspended else "Account deactivated",
                            "An Administrator has restricted access to your account.",
                            kind="info")
        log_audit(request.user, "user.deactivate" if not suspended else "user.suspend",
                  "user", str(user.id), {"email": user.email})
        return Response({"message": "User account deactivated.", "user": user.admin_dict()})


class ActivateUserView(APIView):
    """Re-activate a suspended/deactivated account."""

    permission_classes = [IsSuperAdmin]

    def patch(self, request, user_id=None):
        user_id = _id_from(request, user_id, "user_id")
        user = _get_user_or_404(user_id)
        if user.is_staff_applicant:
            user.account_status = ACCOUNT_STATUS_APPROVED
        else:
            user.account_status = ACCOUNT_STATUS_ACTIVE
        user.is_active = True
        user.failed_login_attempts = 0
        user.save()

        create_notification(user.id, "Account reactivated",
                            "Your account has been reactivated. You can log in again.",
                            kind="info")
        log_audit(request.user, "user.activate", "user", str(user.id), {"email": user.email})
        return Response({"message": "User account reactivated.", "user": user.admin_dict()})


class ResetFaceView(APIView):
    """Reset a user's face authentication (must be re-registered on next login)."""

    permission_classes = [IsSuperAdmin]

    def patch(self, request, user_id=None):
        user_id = _id_from(request, user_id, "user_id")
        user = _get_user_or_404(user_id)
        if not user.face_registered:
            raise ValidationError("This account has no registered face.")

        user.face_embedding = ""
        user.face_registered = False
        user.face_images_count = 0
        user.save()

        notify_face_reset(user)
        log_audit(request.user, "face.reset", "user", str(user.id), {"email": user.email})
        return Response({"message": "Face authentication reset. The user must re-register their face."})


class ResetPasswordView(APIView):
    """Administratively reset a user's password to a temporary value."""

    permission_classes = [IsSuperAdmin]

    def patch(self, request, user_id=None):
        user_id = _id_from(request, user_id, "user_id")
        user = _get_user_or_404(user_id)
        if user.is_super_admin and str(user.id) != str(request.user.id):
            raise ValidationError("Only the Super Admin themselves may reset their own password.")

        temporary = (request.data.get("temporary_password") or "").strip()
        if not (8 <= len(temporary) <= 128):
            raise ValidationError(
                "temporary_password is required and must be at least 8 characters."
            )

        user.set_password(temporary)
        user.failed_login_attempts = 0
        user.save()

        create_notification(user.id, "Password reset by admin",
                            "An Administrator reset your password. Use the temporary password to log in.",
                            kind="password_changed")
        log_audit(request.user, "user.reset_password", "user", str(user.id), {"email": user.email})
        return Response({"message": "Password reset successfully. The user has been notified."})


# ---------------------------------------------------------------------------
# Complaints (registry)
# ---------------------------------------------------------------------------
class AdminComplaintsView(APIView):
    """Super Admin sees every complaint in the system."""

    permission_classes = [IsSuperAdmin]
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        from apps.complaints.views import apply_complaint_filters
        qs = Complaint.objects()
        qs = apply_complaint_filters(qs, request.query_params)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        items = list(page) if page is not None else []

        # Resolve citizen names for the registry.
        from apps.complaints.views import _citizen_names
        names = _citizen_names(items)
        from apps.complaints.serializers import serialize_list_item
        data = [serialize_list_item(c, names.get(str(c.citizen_id), "")) for c in items]
        return paginator.get_paginated_response(data)


class AdminComplaintDetailView(APIView):
    """Full complaint detail (timeline, AI output) for the Super Admin."""

    permission_classes = [IsSuperAdmin]

    def get(self, request, complaint_id):
        from apps.complaints.serializers import serialize_detail
        from apps.complaints.views import _get_complaint_or_404
        complaint = _get_complaint_or_404(complaint_id)
        citizen = User.objects(id=complaint.citizen_id).first()
        return Response(serialize_detail(
            complaint, citizen_name=citizen.full_name if citizen else "", show_pin=True
        ))


# ---------------------------------------------------------------------------
# Reports & audit
# ---------------------------------------------------------------------------
class ReportsView(APIView):
    """Administrative reports: status/category breakdowns, role counts, trends."""

    permission_classes = [IsSuperAdmin]

    def get(self, request):
        from apps.complaints.models import CATEGORY_CHOICES
        categories = list(CATEGORY_CHOICES)
        by_category = {c: Complaint.objects(category=c).count() for c in categories}
        by_status = {s: Complaint.objects(status=s).count() for s in STATUS_CHOICES}

        role_counts = {
            role: User.objects(role=role).count()
            for role in ("citizen", "validator", "official", "super_admin")
        }
        status_counts = {
            s: User.objects(account_status=s).count() for s in (
                ACCOUNT_STATUS_PENDING, ACCOUNT_STATUS_APPROVED, ACCOUNT_STATUS_ACTIVE,
                ACCOUNT_STATUS_REJECTED, ACCOUNT_STATUS_SUSPENDED, ACCOUNT_STATUS_DEACTIVATED,
            )
        }

        # Applications processed per admin.
        applications_by_reviewer = {}
        for app in Application.objects(application_status__in=[APPLICATION_STATUS_APPROVED,
                                                               APPLICATION_STATUS_REJECTED]):
            key = str(app.reviewed_by) if app.reviewed_by else "unknown"
            applications_by_reviewer[key] = applications_by_reviewer.get(key, 0) + 1

        # Last-14-day user signup trend.
        from datetime import datetime, time, timedelta, timezone
        trend = {}
        for offset in range(13, -1, -1):
            day = now_utc().date() - timedelta(days=offset)
            start = datetime.combine(day, time.min, tzinfo=timezone.utc)
            trend[day.isoformat()] = User.objects(
                created_at__gte=start, created_at__lt=start + timedelta(days=1)
            ).count()

        return Response({
            "complaints_by_status": by_status,
            "complaints_by_category": by_category,
            "total_complaints": sum(by_status.values()),
            "users_by_role": role_counts,
            "users_by_status": status_counts,
            "total_users": User.objects().count(),
            "applications_by_reviewer": applications_by_reviewer,
            "signup_trend_14d": trend,
            "generated_at": now_utc(),
        })


class AuditLogsView(APIView):
    """Audit log entries with filters."""

    permission_classes = [IsSuperAdmin]
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        qs = AuditLog.objects()
        action = (request.query_params.get("action") or "").strip()
        if action:
            qs = qs(action=action)
        query = (request.query_params.get("q") or "").strip()
        if query:
            qs = qs(Q(actor_email__icontains=query) | Q(details__contains=query))

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        items = list(page) if page is not None else []
        return paginator.get_paginated_response([a.to_dict() for a in items])


class LoginHistoryView(APIView):
    """Recent login attempts (password + face), including failures."""

    permission_classes = [IsSuperAdmin]
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        qs = LoginHistory.objects()
        query = (request.query_params.get("q") or "").strip()
        if query:
            qs = qs(Q(email__icontains=query) | Q(detail__icontains=query))
        success = request.query_params.get("success", "")
        if success in ("true", "false"):
            qs = qs(success=success == "true")

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        items = list(page) if page is not None else []
        return paginator.get_paginated_response([h.to_dict() for h in items])
