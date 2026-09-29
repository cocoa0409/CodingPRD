"""Identity headers, RBAC, professional resolution, licence and discipline
gating (PRD 2.1, 2.9 and precedence positions 1-3, 14-15)."""
from flask import request

import store
from errors import ApiError

ROLES = (
    "UtilityAdmin",
    "ProfessionalEngineer",
    "Hydrogeologist",
    "StatisticalReviewer",
    "ComplianceOfficer",
    "Regulator",
    "PublicViewer",
)

ENTITY_BACKED = ("ProfessionalEngineer", "Hydrogeologist", "StatisticalReviewer")

ALL_STAFF = (
    "UtilityAdmin",
    "ComplianceOfficer",
    "Regulator",
    "ProfessionalEngineer",
    "Hydrogeologist",
    "StatisticalReviewer",
)


class Actor(object):
    __slots__ = ("user_id", "role", "professional")

    def __init__(self, user_id, role, professional):
        self.user_id = user_id
        self.role = role
        self.professional = professional


def authenticate(allowed_roles):
    """Positions 1-3 of the refusal chain."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    # A header sent as the empty string counts exactly as if never sent.
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    professional = None
    if role in ENTITY_BACKED:
        professional = store.professionals.get(user_id)
        if professional is None:
            raise ApiError("ERR_PROFESSIONAL_NOT_FOUND",
                           "The acting professional identity does not exist.")
    return Actor(user_id, role, professional)


def require_license_active(actor):
    """Position 14."""
    if actor.professional is None:
        return
    if actor.professional["license_status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE",
                       "The acting professional's licence is not ACTIVE.")


def require_discipline(actor, admitted):
    """Position 15."""
    if actor.professional is None:
        return
    if actor.professional["discipline"] not in admitted:
        raise ApiError("ERR_DISCIPLINE_NOT_QUALIFIED",
                       "The acting professional's discipline may not sign this artifact.")
