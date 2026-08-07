"""Authentication URL routes (mounted at /api/auth/)."""

from django.urls import path

from apps.authentication import views

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="auth-register"),
    path("login/", views.LoginView.as_view(), name="auth-login"),
    path("refresh/", views.RefreshTokenView.as_view(), name="auth-refresh"),
    path("me/", views.MeView.as_view(), name="auth-me"),
    path("profile/", views.UpdateProfileView.as_view(), name="auth-profile"),
    path("change-password/", views.ChangePasswordView.as_view(), name="auth-change-password"),
    # --- Face authentication --------------------------------------------------
    path("register-face/", views.RegisterFaceView.as_view(), name="auth-register-face"),
    path("verify-face/", views.VerifyFaceView.as_view(), name="auth-verify-face"),
    # --- In-app notifications -------------------------------------------------
    path("notifications/", views.NotificationsListView.as_view(), name="auth-notifications"),
    path("notifications/read/", views.MarkNotificationsReadView.as_view(), name="auth-notifications-read"),
]
