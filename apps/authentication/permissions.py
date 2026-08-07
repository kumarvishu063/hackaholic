"""Role-based permission classes.

Used on every API view so only users with the matching role can perform an
action (e.g. only validators can verify complaints).
"""

from rest_framework import permissions


def _has_role(request, roles) -> bool:
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and getattr(user, "role", None) in roles)


class IsCitizen(permissions.BasePermission):
    """Allow access only to users with the `citizen` role."""

    message = "Only citizens can perform this action."

    def has_permission(self, request, view):
        return _has_role(request, {"citizen"})


class IsValidator(permissions.BasePermission):
    """Allow access only to users with the `validator` role."""

    message = "Only validators can perform this action."

    def has_permission(self, request, view):
        return _has_role(request, {"validator"})


class IsOfficial(permissions.BasePermission):
    """Allow access only to users with the `official` role."""

    message = "Only officials can perform this action."

    def has_permission(self, request, view):
        return _has_role(request, {"official"})


class IsValidatorOrOfficial(permissions.BasePermission):
    """Allow access to validators and officials (complaint review/detail)."""

    message = "Only validators or officials can perform this action."

    def has_permission(self, request, view):
        return _has_role(request, {"validator", "official"})


class IsSuperAdmin(permissions.BasePermission):
    """Allow access only to Super Admin accounts."""

    message = "Only Super Admin can perform this action."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and user.is_super_admin)
