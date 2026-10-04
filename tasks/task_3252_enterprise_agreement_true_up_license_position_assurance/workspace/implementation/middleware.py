"""Auth: X-User-ID / X-User-Role headers, RBAC, CustomerAdmin ownership."""
import flask

import db
from helpers import err

ROLES = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")
ALL_ROLES = ROLES


def authenticate():
    user_id = flask.request.headers.get("X-User-ID")
    role = flask.request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and X-User-Role must be a declared role.",
            401)
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN", "Role %s is not permitted for this endpoint." % role, 403)


def check_ownership(user_id, role, owner_org_id):
    """CustomerAdmin is entity-backed: X-User-ID must equal the owning Organization id."""
    if role == "CustomerAdmin" and owner_org_id is not None and user_id != owner_org_id:
        err("ERR_FORBIDDEN", "CustomerAdmin does not own the target resource.", 403)


def org_of_agreement(agreement):
    return agreement.get("organization_id") if agreement else None


def get_agreement_or_404(agreement_id):
    ag = db.agreements.get(agreement_id)
    if ag is None:
        err("ERR_NOT_FOUND", "Agreement not found.", 404)
    return ag


def authorize_agreement_path(allowed_roles, agreement_id):
    """Authenticate, check role, resolve agreement (404), check CustomerAdmin ownership.
    Returns (user_id, role, agreement)."""
    user_id, role = authenticate()
    require_role(role, allowed_roles)
    ag = get_agreement_or_404(agreement_id)
    check_ownership(user_id, role, org_of_agreement(ag))
    return user_id, role, ag


def scope_filter_for(role, user_id, records, org_resolver):
    """For flat list endpoints: CustomerAdmin sees only own-organization records."""
    if role != "CustomerAdmin":
        return records
    return [r for r in records if org_resolver(r) == user_id]
