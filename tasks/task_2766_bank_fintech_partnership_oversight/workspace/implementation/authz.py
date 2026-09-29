"""Authentication, role authorisation (ladder ranks 1/2/5) and partner scope (rank 12)."""
from functools import wraps

from flask import g, request

from errors import fail

ROLES = ("ProgramOfficer", "ComplianceOfficer", "RiskCommittee", "InternalAudit",
         "FintechPartner")


def authenticate(allowed_roles):
    """Rank 1 header presence, rank 2 role recognition, rank 5 role authorisation."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not str(user_id).strip() or not str(role).strip():
        fail("ERR_MISSING_AUTH_HEADERS", "X-User-ID and X-User-Role are required")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ROLES:
        fail("ERR_UNKNOWN_ROLE", "unrecognised role: %s" % role)
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "role %s may not call this endpoint" % role)
    g.user_id = user_id
    g.role = role


def auth(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            authenticate(allowed_roles)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def is_partner():
    return g.role == "FintechPartner"


def scope_partner_id(partner_id):
    """Rank 12: a FintechPartner may only touch rows bearing its own partner id."""
    if is_partner() and partner_id != g.user_id:
        fail("ERR_PARTNER_SCOPE_VIOLATION", "resource belongs to another partner")


def scope_rows(records, field="partner_id"):
    if not is_partner():
        return records
    return [r for r in records if r.get(field) == g.user_id]


def sod(originator_user_id):
    """Rank 14: the deciding user must differ from the originator."""
    if originator_user_id is not None and g.user_id == originator_user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "decider must differ from the originator")
