"""Authentication, role authorization and ownership (PRD 2.1, 2.10)."""

import functools

from flask import g, request

from errors import fail

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

# PRD 2.1 -- exactly seven roles, spelled exactly like this.
ROLES = (
    "Rheumatologist",
    "PriorAuthCoordinator",
    "PayerReviewer",
    "InfusionNurse",
    "BenefitsCounselor",
    "RegistryAdmin",
    "Patient",
)

ALL_ROLES = list(ROLES)


def authenticate():
    """PRD 2.10 rule 1: the very first thing the server checks."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id == "" or role is None or role == "":
        fail("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def authorize(allowed_roles):
    """PRD 2.10 rule 2: unknown role, or role not authorized here -> 403."""
    if g.role not in ROLES:
        fail("ERR_FORBIDDEN_ROLE", "Unrecognised role '%s'." % g.role)
    if g.role not in allowed_roles:
        fail(
            "ERR_FORBIDDEN_ROLE",
            "Role '%s' is not authorized for this operation." % g.role,
        )


def endpoint(roles):
    """Decorator applying rules 1 and 2 of the rejection ladder in order."""
    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(allowed)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def acting_user_id():
    return g.user_id


def acting_role():
    return g.role


def require_patient_ownership(patient_id_in_request):
    """PRD 2.1 / 2.10 rule 4 -- the patient-ownership comparison.

    A caller acting as ``Patient`` must address their own patient id; a caller
    in any other role is not subject to the comparison at all.
    """
    if g.role == "Patient" and patient_id_in_request != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
