"""Auth header extraction and role checking (priority 1: auth)."""
from flask import request

from errors import forbidden

ROLES = ("HouseManager", "CompanyRep", "BoxOfficeAgent")


def actor():
    """Return (user_id, role). Raises ERR_FORBIDDEN when headers are missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise forbidden("Missing X-User-ID or X-User-Role, or unrecognized role")
    return user_id, role


def require_roles(*allowed):
    """Ensure the caller's role is in allowed; returns (user_id, role)."""
    user_id, role = actor()
    if role not in allowed:
        raise forbidden("Role not authorized for this endpoint")
    return user_id, role


def company_of_production(store, production_id):
    p = store.productions.get(production_id)
    return p["company_id"] if p else None


def require_company_owns(store, user_id, company_id):
    """CompanyRep may only act on resources owned by their own company."""
    if user_id != company_id:
        raise forbidden("CompanyRep acting on a resource owned by another company")
