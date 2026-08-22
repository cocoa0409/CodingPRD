"""Operator identity and role-based access control (PRD 2.1)."""

import functools

from flask import g, request

from errors import ApiError

ROLES = (
    "PlanAdmin",
    "NetworkManager",
    "ClaimsIntake",
    "ClaimsExaminer",
    "UtilizationReviewer",
    "MedicalDirector",
    "ProviderRep",
)

# Every role except ProviderRep may read configuration and claim resources.
ALL_OPERATORS = (
    "PlanAdmin",
    "NetworkManager",
    "ClaimsIntake",
    "ClaimsExaminer",
    "UtilizationReviewer",
    "MedicalDirector",
)

# NetworkManager is deliberately denied every claim-side read.
CLAIM_READERS = (
    "PlanAdmin",
    "ClaimsIntake",
    "ClaimsExaminer",
    "UtilizationReviewer",
    "MedicalDirector",
    "ProviderRep",
)


def endpoint(roles):
    """Authentication (check 1) then role authorization (check 2) of PRD 2.8."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def is_provider_rep():
    return getattr(g, "role", None) == "ProviderRep"


def enforce_claim_scope(claim):
    """A ProviderRep may only reach claims it billed (PRD 2.1)."""
    if is_provider_rep() and claim["provider_id"] != g.user_id:
        raise ApiError("ERR_PROVIDER_SCOPE_VIOLATION")
