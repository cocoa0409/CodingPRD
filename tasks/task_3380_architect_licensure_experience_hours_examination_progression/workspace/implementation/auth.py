"""Authentication / authorization helpers (PRD sections 2.1 and 2.6)."""
from flask import request

from errors import fail

ROLES = {"Anonymous", "Candidate", "Supervisor", "BoardAdministrator", "NcarbAdministrator"}


def get_body():
    """JSON request body as a dict; absent/non-object bodies become {}."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def current_caller():
    """Tier 1: both identity headers present and the role is declared."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "missing or invalid X-User-Role / X-User-ID headers")
    return uid, role


def require_roles(*roles):
    """Tiers 1-2: authenticated and the role is in the endpoint's role list."""
    uid, role = current_caller()
    if role not in roles:
        fail("ERR_UNAUTHORIZED", "caller role is not permitted for this endpoint")
    return uid, role


def require_candidate_identity(uid, candidate_id):
    """Tier 2 ownership: Candidate callers act only on their own resources."""
    if uid != candidate_id:
        fail("ERR_UNAUTHORIZED", "candidates may act only on their own resources")
