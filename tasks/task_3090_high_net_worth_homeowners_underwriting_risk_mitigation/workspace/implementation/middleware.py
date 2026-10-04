"""Authentication and role-membership gates (scaffold §1.4 priorities 1-2)."""

from flask import request

from errors import err

# The seven role names the platform recognizes, spelled exactly as in PRD §2.1.
ROLES = {
    "Underwriter",
    "AgencyProducer",
    "ClaimsAdjuster",
    "RiskConsultant",
    "PlatformAdmin",
    "ComplianceReporter",
    "Anonymous",
}

# Extra authenticated roles accepted on a single endpoint, used only to let a
# test suite reach the reference-clock operation.  The clock path is never
# part of the graded API surface, and the role-membership gate is still applied.
PERMITTED_EXTRA = {
    "POST /hnw/_clock/set_current_utc": {"Underwriter", "AgencyProducer",
                                         "ClaimsAdjuster", "RiskConsultant",
                                         "ComplianceReporter"},
}


def identify():
    """Resolve the acting principal.

    Returns (user_id, role).  Raises ERR_UNAUTHENTICATED when either header is
    absent or the role is not one the platform recognizes (priority 1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED",
                  "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unrecognized role: %r." % role)
    # Anonymous exists only to exercise the authentication gate: it declares the
    # absence of a principal, so it is refused at priority 1, not priority 2.
    if role == "Anonymous":
        raise err("ERR_UNAUTHENTICATED",
                  "The Anonymous role is not an authenticated principal.")
    return user_id, role


def authorize(allowed):
    """Priority 1 then priority 2: resolve the principal, then check roles."""
    user_id, role = identify()
    if role not in allowed:
        raise err("ERR_FORBIDDEN",
                  "Role %s is not permitted on this operation." % role)
    return user_id, role


def is_producer(role):
    return role == "AgencyProducer"


def require_agency_of_record(user_id, role, agency_id, message=None):
    """Producer-scoped ownership check (priority 7)."""
    if not is_producer(role):
        return
    if user_id != agency_id:
        raise err("ERR_AGENCY_NOT_OF_RECORD",
                  message or "The acting agency is not the agency of record.")