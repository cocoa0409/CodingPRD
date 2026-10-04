"""Auth: context headers, role checks, identity resolution, access grants."""
from flask import request
import db
from errors import ApiError

ROLES = {"PlatformAdmin", "CompanyUser", "AccountantUser"}


def get_context():
    """Priority 1+2+3 checks. Returns (role, identity_dict or None)."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid:
        raise ApiError("ERR_MISSING_OR_INVALID_CONTEXT_HEADER", 400,
                       "X-User-Role or X-User-ID header missing")
    if role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_CONTEXT_HEADER", 400,
                       "Malformed role header")
    identity = None
    if role == "CompanyUser":
        identity = db.TABLES["CompanyUser"].get(uid)
        if identity is None:
            raise ApiError("ERR_IDENTITY_MISMATCH", 403,
                           "CompanyUser id not persisted")
    elif role == "AccountantUser":
        identity = db.TABLES["AccountantUser"].get(uid)
        if identity is None:
            raise ApiError("ERR_IDENTITY_MISMATCH", 403,
                           "AccountantUser id not persisted")
    return role, identity


def require_role(allowed):
    role, identity = get_context()
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403,
                       "Role not permitted for this endpoint")
    return role, identity


def require_company_scope(identity, company_id):
    """For CompanyUser role: identity.company_id must match the path company."""
    if identity is None:
        return
    if identity.get("company_id") != company_id:
        raise ApiError("ERR_IDENTITY_MISMATCH", 403,
                       "CompanyUser acting on a company other than their own")


def require_firm_scope(identity, firm_id):
    if identity is None:
        return
    if identity.get("firm_id") != firm_id:
        raise ApiError("ERR_IDENTITY_MISMATCH", 403,
                       "AccountantUser acting for another firm")


def active_grant(identity, company_id, levels):
    """AccountantUser must hold an ACTIVE AccessGrant on company at one of levels.
    Returns the grant; raises ERR_FORBIDDEN_FOR_ROLE otherwise."""
    if identity is None:
        return None
    for g in db.TABLES["AccessGrant"].values():
        if (g["accountant_user_id"] == identity["id"]
                and g["company_id"] == company_id
                and g["grant_status"] == "ACTIVE"
                and g["access_level"] in levels):
            return g
    raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403,
                   "No ACTIVE AccessGrant authorizes this action")
