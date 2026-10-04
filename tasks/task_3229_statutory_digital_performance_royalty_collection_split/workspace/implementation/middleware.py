"""Auth middleware per PRD 2.1 / scaffold validations priorities 1-3."""

from flask import request

from errors import err_missing_context, err_unauthorized, err_segregation

VALID_ROLES = {
    "Admin",
    "Licensee",
    "RoyaltyOps",
    "PayeeAdmin",
    "StatutoryBoard",
    "RoyaltyAuditor",
    "MatchingAgent",
}


def get_context():
    """Returns (user_id, role). Raises err_missing_context when headers absent."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise err_missing_context()
    return user_id, role


def require_roles(allowed):
    user_id, role = get_context()
    if role not in VALID_ROLES or role not in allowed:
        raise err_unauthorized()
    return user_id, role


def check_segregation(audit, user_id):
    if audit.get("opened_by") is not None and audit["opened_by"] == user_id:
        raise err_segregation()
