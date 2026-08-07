"""AI services URL routes (mounted at /api/)."""

from django.urls import path

from apps.ai_services import views

urlpatterns = [
    path("chat/", views.ChatbotView.as_view(), name="chat"),
    path("chat/transcribe/", views.ChatbotTranscribeView.as_view(), name="chat-transcribe"),
]
