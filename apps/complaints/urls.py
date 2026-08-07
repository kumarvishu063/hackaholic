"""Complaint URL routes (mounted at /api/)."""

from django.urls import path

from apps.complaints import views

urlpatterns = [
    path("complaints/", views.ComplaintListCreateView.as_view(), name="complaint-list-create"),
    path("complaints/<str:complaint_id>/", views.ComplaintDetailView.as_view(), name="complaint-detail"),
    path("complaints/<str:complaint_id>/validate/", views.ValidateComplaintView.as_view(), name="complaint-validate"),
    path("complaints/<str:complaint_id>/resolve/", views.ResolveComplaintView.as_view(), name="complaint-resolve"),
    path("feedback/", views.FeedbackCreateView.as_view(), name="feedback-create"),
    path("feedback/<str:complaint_id>/", views.FeedbackDetailView.as_view(), name="feedback-detail"),
    path("analytics/", views.AnalyticsView.as_view(), name="analytics"),
]
