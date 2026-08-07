"""
Notification & audit services.

send_email            — transactional email (console backend when SMTP unset).
create_notification   — in-app dashboard notification stored in MongoDB.
log_audit             — administrative audit trail.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send a plain-text transactional email.

    When EMAIL_HOST is not configured the Django console backend prints the
    message to the terminal instead, so the whole application remains fully
    functional in development with zero SMTP setup.
    """
    if not to_email:
        return False
    try:
        from django.core.mail import send_mail
        if settings.EMAIL_HOST:
            # Explicitly switch to SMTP only when credentials are present.
            from django.core import mail
            from django.core.mail.backends.smtp import EmailBackend
            connection = EmailBackend(
                host=settings.EMAIL_HOST,
                port=settings.EMAIL_PORT,
                username=settings.EMAIL_HOST_USER,
                password=settings.EMAIL_HOST_PASSWORD,
                use_tls=settings.EMAIL_USE_TLS,
                fail_silently=False,
            )
            sent = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
                             [to_email], connection=connection, fail_silently=False)
        else:
            sent = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email])
        logger.info("Email '%s' -> %s (sent=%s)", subject, to_email, sent)
        return bool(sent)
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to send email to %s: %s", to_email, exc)
        return False


# ---------------------------------------------------------------------------
# In-app notifications
# ---------------------------------------------------------------------------
def create_notification(user_id, title: str, message: str, kind: str = "info") -> None:
    """Persist a dashboard notification for a user."""
    from apps.authentication.models import Notification
    try:
        Notification(user_id=user_id, title=title, message=message, kind=kind).save()
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not create notification for %s: %s", user_id, exc)


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
def log_audit(actor, action: str, target_type: str = "", target_id: str = "",
              details: dict | None = None) -> None:
    """Record an administrative action for the audit log."""
    from apps.authentication.models import AuditLog
    try:
        AuditLog(
            actor_id=actor.id if actor else None,
            actor_email=getattr(actor, "email", ""),
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
        ).save()
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not write audit log: %s", exc)


# ---------------------------------------------------------------------------
# Pre-built notification templates
# ---------------------------------------------------------------------------
def notify_application_submitted(user, role_label: str) -> None:
    create_notification(
        user.id,
        "Application submitted",
        f"Your application to register as a {role_label} has been submitted successfully. "
        "Please wait for Admin verification.",
        kind="application_submitted",
    )
    send_email(
        user.email,
        "JanSetu — Application submitted",
        f"Hi {user.full_name},\n\n"
        f"Your application to register as a {role_label} has been received.\n"
        "Application status: PENDING APPROVAL\n\n"
        "You will be able to log in only after an Administrator approves your "
        "application and you complete face authentication.\n\n"
        "— JanSetu Team",
    )


def notify_application_approved(user, role_label: str) -> None:
    create_notification(
        user.id,
        "Application approved",
        f"Congratulations! Your registration as a {role_label} has been approved. "
        "You can now log in and complete face authentication.",
        kind="application_approved",
    )
    send_email(
        user.email,
        "JanSetu — Your registration has been approved",
        f"Hi {user.full_name},\n\n"
        f"Your registration as a {role_label} has been approved by the Administrator. "
        "You can now log in. On your first login you will be asked to complete "
        "face authentication.\n\n"
        "— JanSetu Team",
    )


def notify_application_rejected(user, role_label: str, reason: str) -> None:
    create_notification(
        user.id,
        "Application rejected",
        f"Your application to register as a {role_label} has been rejected. "
        f"Reason: {reason}",
        kind="application_rejected",
    )
    send_email(
        user.email,
        "JanSetu — Your application was not approved",
        f"Hi {user.full_name},\n\n"
        f"Thank you for applying to register as a {role_label}.\n\n"
        f"Unfortunately your application could not be approved.\nReason: {reason}\n\n"
        "— JanSetu Team",
    )


def notify_face_reset(user) -> None:
    create_notification(
        user.id,
        "Face authentication reset",
        "An Administrator has reset your face authentication. "
        "Please re-register your face before logging in again.",
        kind="face_reset",
    )
    send_email(
        user.email,
        "JanSetu — Face authentication reset",
        f"Hi {user.full_name},\n\n"
        "An Administrator has reset your face authentication. Please register "
        "your face again the next time you log in.\n\n— JanSetu Team",
    )


def notify_password_changed(user) -> None:
    create_notification(
        user.id,
        "Password changed",
        "Your account password was successfully changed.",
        kind="password_changed",
    )
    send_email(
        user.email,
        "JanSetu — Password changed",
        f"Hi {user.full_name},\n\nYour JanSetu account password was changed. "
        "If you did not make this change, please contact the Administrator "
        "immediately.\n\n— JanSetu Team",
    )
