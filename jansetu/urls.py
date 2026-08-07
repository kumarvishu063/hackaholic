"""
JanSetu — Root URL configuration.

Maps every frontend page to a template and mounts the REST API namespaces:
    /api/auth/*   → registration, login, tokens, profile
    /api/*        → complaints, validation, resolution, analytics
"""

from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import TemplateView

# Simple page routes (all frontend logic lives in static/ JavaScript).
page = TemplateView.as_view

urlpatterns = [
    # --- Public pages -------------------------------------------------------
    path("", page(template_name="index.html"), name="home"),
    path("login/", page(template_name="login.html"), name="login"),
    path("register/", page(template_name="register.html"), name="register"),

    # --- Role dashboards ----------------------------------------------------
    path("dashboard/citizen/", page(template_name="dashboard-citizen.html"), name="citizen-dashboard"),
    path("dashboard/validator/", page(template_name="dashboard-validator.html"), name="validator-dashboard"),
    path("dashboard/official/", page(template_name="dashboard-official.html"), name="official-dashboard"),
    path("dashboard/admin/", page(template_name="dashboard-admin.html"), name="admin-dashboard"),

    # --- Super Admin pages --------------------------------------------------
    path("admin/applications/", page(template_name="admin-applications.html"), name="admin-applications-page"),
    path("admin/users/", page(template_name="admin-users.html"), name="admin-users-page"),
    path("admin/complaints/", page(template_name="admin-complaints.html"), name="admin-complaints-page"),
    path("admin/reports/", page(template_name="admin-reports.html"), name="admin-reports-page"),
    path("admin/audit/", page(template_name="admin-audit.html"), name="admin-audit-page"),
    path("admin/login-history/", page(template_name="admin-login-history.html"), name="admin-login-history-page"),

    # --- Shared pages -------------------------------------------------------
    path("complaint/", page(template_name="complaint-details.html"), name="complaint-details"),
    path("profile/", page(template_name="profile.html"), name="profile"),
    path("settings/", page(template_name="settings.html"), name="settings"),

    # --- REST API -----------------------------------------------------------
    path("api/auth/", include("apps.authentication.urls")),
    path("api/admin/", include("apps.admin_panel.urls")),
    path("api/", include("apps.complaints.urls")),
    path("api/", include("apps.ai_services.urls")),
]

# Serve user-uploaded media in development.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
