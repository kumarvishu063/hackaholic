"""Centralised exception handling.

Maps MongoEngine / validation errors to clean JSON responses so the frontend
always receives a predictable `{ error: "message" }` shape.
"""

import logging

from django.http import JsonResponse
from mongoengine import errors as mongo_errors
from rest_framework import status
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """DRF entry point: normalise DRF exceptions and re-map MongoEngine ones."""

    # Let DRF handle its own exceptions first (ValidationError, PermissionDenied…)
    response = drf_exception_handler(exc, context)
    if response is not None:
        return response

    # --- MongoEngine-specific errors ---------------------------------------
    if isinstance(exc, mongo_errors.NotUniqueError):
        return JsonResponse(
            {"error": "A record with the same unique value already exists."},
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, mongo_errors.ValidationError):
        return JsonResponse(
            {"error": f"Invalid data: {exc.message if hasattr(exc, 'message') else str(exc)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(exc, mongo_errors.DoesNotExist):
        return JsonResponse(
            {"error": "The requested record was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Unexpected server errors — log the full traceback for diagnostics but
    # return a generic message to the client.
    logger.exception("Unhandled exception in API: %s", exc)
    return JsonResponse(
        {"error": "An unexpected error occurred. Please try again later."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
