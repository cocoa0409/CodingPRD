"""Authentication, role authorisation and donor-scoped access (PRD 2.1).

Checks 1-4 of the global rejection order live here:
  1. both auth headers present and non-empty      -> ERR_MISSING_AUTH_HEADERS
  2. the role is one of the eight declared roles  -> ERR_UNKNOWN_ROLE
  3. the role is authorised for this endpoint     -> ERR_ROLE_NOT_PERMITTED
  4. a Donor acts only within her own scope       -> ERR_DONOR_SCOPE_VIOLATION
"""

import functools

from flask import g, request

from errors import fail

DONOR = "Donor"
INTAKE_COORDINATOR = "IntakeCoordinator"
MEDICAL_DIRECTOR = "MedicalDirector"
PROCESSING_TECHNICIAN = "ProcessingTechnician"
QA_OFFICER = "QualityAssuranceOfficer"
DISPENSING_PHARMACIST = "DispensingPharmacist"
PRESCRIBER = "Prescriber"
ADMIN = "MilkBankAdmin"

ROLES = (
    DONOR,
    INTAKE_COORDINATOR,
    MEDICAL_DIRECTOR,
    PROCESSING_TECHNICIAN,
    QA_OFFICER,
    DISPENSING_PHARMACIST,
    PRESCRIBER,
    ADMIN,
)


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    if value.strip() == "":
        return None
    return value


def authenticate():
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")
    if user_id is None or role is None:
        fail("ERR_MISSING_AUTH_HEADERS",
             "Both X-User-ID and X-User-Role are required.")
    if role not in ROLES:
        fail("ERR_UNKNOWN_ROLE", "X-User-Role '%s' is not a known role." % role)
    return user_id, role


def guard(*roles):
    """Wrap a view with checks 1-3; stash the actor on flask.g."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in roles:
                fail("ERR_ROLE_NOT_PERMITTED",
                     "Role %s may not perform this operation." % role)
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return g.get("user_id")


def actor_role():
    return g.get("role")


def is_donor():
    return g.get("role") == DONOR


def require_own(owner_donor_id):
    """Reject a Donor addressing another donor's record."""
    if is_donor() and owner_donor_id != g.get("user_id"):
        fail("ERR_DONOR_SCOPE_VIOLATION",
             "A donor may only address her own records.")
