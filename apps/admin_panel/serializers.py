"""Request validation for the Super Admin panel."""

from rest_framework import serializers


class ReviewSerializer(serializers.Serializer):
    """Approval payload — optional note/remarks."""

    remarks = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class RejectionSerializer(serializers.Serializer):
    """Rejection payload — remarks (reason) is mandatory."""

    remarks = serializers.CharField(min_length=5, max_length=2000, error_messages={
        "min_length": "Please provide a reason for rejection (at least 5 characters).",
    })
