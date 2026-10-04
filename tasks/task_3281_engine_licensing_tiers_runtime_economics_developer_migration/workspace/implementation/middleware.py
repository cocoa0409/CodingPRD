"""Auth middleware: header extraction, role check, org ownership check."""
from flask import request

from db import db
from errors import (
    raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_FORBIDDEN_ORG,
    ERR_NOT_FOUND,
)

ROLES = {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor", "ReviewBoard"}


def authenticate():
    """Priority 1: headers present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-ID / X-User-Role headers")
    return uid, role


def authorize(role, allowed):
    """Priority 2: role permitted for this endpoint."""
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED, "Role not permitted for this endpoint")


def get_org_or_404(org_id):
    org = db.orgs.get(org_id)
    if org is None:
        raise_err(ERR_NOT_FOUND, "Organization not found")
    return org


def check_org_ownership(role, uid, org_id):
    """Priority 3: OrgOwner may only act on own org's resources.

    Called AFTER role authorization. For OrgOwner, existence of the org is
    checked here so that a foreign org id yields ERR_FORBIDDEN_ORG while a
    nonexistent id yields ERR_NOT_FOUND.
    """
    if role != "OrgOwner":
        return
    if org_id not in db.orgs:
        raise_err(ERR_NOT_FOUND, "Organization not found")
    if uid != org_id:
        raise_err(ERR_FORBIDDEN_ORG, "OrgOwner may not act on another org's resources")


def org_of_project(project):
    return project["org_id"]


def org_of_report(report):
    project = db.projects.get(report["project_id"])
    return project["org_id"] if project else None


def org_of_invoice(invoice):
    project = db.projects.get(invoice["project_id"])
    return project["org_id"] if project else None
