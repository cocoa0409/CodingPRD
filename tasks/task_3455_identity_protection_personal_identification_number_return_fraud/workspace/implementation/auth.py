"""Authentication / role authorization / entity-backed ownership (PRD §2.1).

Validation priorities 1-3: authentication (401), role authorization (403),
ownership and segregation of duties (403).
"""
from flask import request

from errors import err

ROLES = {
    "Taxpayer",
    "TaxPreparer",
    "VerificationAgent",
    "FraudAnalyst",
    "TaxpayerAdvocate",
    "SystemAdmin",
}


def caller():
    """Priority 1: both identity headers must be present and non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or uid.strip() == "" or role.strip() == "":
        err("ERR_UNAUTHENTICATED")
    return uid, role


def require_roles(allowed):
    """Priorities 1-2: authenticate, then check the role against `allowed`."""
    uid, role = caller()
    if role not in allowed:
        err("ERR_UNAUTHORIZED")
    return uid, role


def forbid_other_taxpayer(uid, role, taxpayer_id):
    """Priority 3 ownership: a Taxpayer caller may act only on their own id."""
    if role == "Taxpayer" and uid != taxpayer_id:
        err("ERR_UNAUTHORIZED")
