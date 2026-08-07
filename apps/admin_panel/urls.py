"""Super Admin panel routes (mounted at /api/admin/)."""

from django.urls import path

from apps.admin_panel import views

urlpatterns = [
    # Dashboard
    path("dashboard/", views.AdminDashboardView.as_view(), name="admin-dashboard"),

    # Applications
    path("applications/", views.ApplicationsListView.as_view(), name="admin-applications"),
    # Flat spec-style aliases (id passed in the request body) must precede the
    # parameterised <application_id> route so "approve/" isn't captured as an id.
    path("applications/approve/", views.ApproveApplicationView.as_view(), name="admin-application-approve-flat"),
    path("applications/reject/", views.RejectApplicationView.as_view(), name="admin-application-reject-flat"),
    path("applications/<str:application_id>/", views.ApplicationDetailView.as_view(), name="admin-application-detail"),
    path("applications/<str:application_id>/approve/", views.ApproveApplicationView.as_view(), name="admin-application-approve"),
    path("applications/<str:application_id>/reject/", views.RejectApplicationView.as_view(), name="admin-application-reject"),

    # Users
    path("users/", views.AdminUsersView.as_view(), name="admin-users"),
    path("users/<str:user_id>/deactivate/", views.DeactivateUserView.as_view(), name="admin-user-deactivate"),
    path("users/<str:user_id>/activate/", views.ActivateUserView.as_view(), name="admin-user-activate"),
    path("users/<str:user_id>/reset-face/", views.ResetFaceView.as_view(), name="admin-user-reset-face"),
    path("users/<str:user_id>/reset-password/", views.ResetPasswordView.as_view(), name="admin-user-reset-password"),
    path("deactivate-user/", views.DeactivateUserView.as_view(), name="admin-deactivate-user-flat"),
    path("reset-face/", views.ResetFaceView.as_view(), name="admin-reset-face-flat"),

    # Complaints (registry)
    path("complaints/", views.AdminComplaintsView.as_view(), name="admin-complaints"),
    path("complaints/<str:complaint_id>/", views.AdminComplaintDetailView.as_view(), name="admin-complaint-detail"),

    # Reports & audit
    path("reports/", views.ReportsView.as_view(), name="admin-reports"),
    path("audit-logs/", views.AuditLogsView.as_view(), name="admin-audit-logs"),
    path("login-history/", views.LoginHistoryView.as_view(), name="admin-login-history"),
]
