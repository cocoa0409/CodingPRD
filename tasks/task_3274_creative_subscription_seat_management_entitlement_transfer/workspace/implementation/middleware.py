"""Auth: header validation, role authorization, entity-backed identity scoping."""

from flask import request

from db import db
from errors import (
    err_forbidden_role,
    err_identity_mismatch,
    err_unauthenticated,
)

VALID_ROLES = {"SystemAdmin", "OrgAdmin", "DeploymentAdmin", "ResellerAgent", "EndUser"}

# Role kinds per §3.1: OrgAdmin = SYSTEM_ADMIN or PRODUCT_ADMIN; DeploymentAdmin = DEPLOYMENT_ADMIN
ORG_ADMIN_KINDS = {"SYSTEM_ADMIN", "PRODUCT_ADMIN"}
DEPLOYMENT_ADMIN_KIND = "DEPLOYMENT_ADMIN"


class Identity:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        # resolved entity for entity-backed roles
        self.admin = None       # Admin record when role in (OrgAdmin, DeploymentAdmin)
        self.end_user = None    # EndUser record when role == EndUser
        self.reseller = None    # Reseller record when role == ResellerAgent


def get_identity():
    """Priority 1: header presence/well-formedness."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or not isinstance(user_id, str) or not isinstance(role, str):
        raise err_unauthenticated()
    if role not in VALID_ROLES:
        raise err_unauthenticated("Malformed X-User-Role")
    return Identity(user_id, role)


def require_role(identity, allowed_roles):
    """Priority 2: role authorization."""
    if identity.role not in allowed_roles:
        raise err_forbidden_role()


def resolve_identity(identity):
    """Priority 3: entity-backed identity resolution.

    For OrgAdmin/DeploymentAdmin: X-User-ID must be an existing Admin.id whose kind
    matches the declared role (OrgAdmin -> SYSTEM_ADMIN/PRODUCT_ADMIN, DeploymentAdmin
    -> DEPLOYMENT_ADMIN). Org scoping vs target resource is performed by
    require_org_scope once the target org is known.
    For EndUser: X-User-ID must be an existing EndUser.id.
    For ResellerAgent: X-User-ID must be an existing Reseller.id.
    SystemAdmin: opaque.
    """
    if identity.role == "SystemAdmin":
        return
    if identity.role in ("OrgAdmin", "DeploymentAdmin"):
        admin = db["admins"].get(identity.user_id)
        if admin is None:
            raise err_identity_mismatch("Unknown admin identity")
        if identity.role == "OrgAdmin":
            if admin["admin_kind"] not in ORG_ADMIN_KINDS:
                raise err_identity_mismatch("Admin kind does not match OrgAdmin role")
        else:
            if admin["admin_kind"] != DEPLOYMENT_ADMIN_KIND:
                raise err_identity_mismatch("Admin kind does not match DeploymentAdmin role")
        identity.admin = admin
        return
    if identity.role == "EndUser":
        user = db["end_users"].get(identity.user_id)
        if user is None:
            raise err_identity_mismatch("Unknown end user identity")
        identity.end_user = user
        return
    if identity.role == "ResellerAgent":
        reseller = db["resellers"].get(identity.user_id)
        if reseller is None:
            raise err_identity_mismatch("Unknown reseller identity")
        identity.reseller = reseller
        return


def require_org_scope(identity, org_id):
    """For entity-backed admin roles, the admin's org must match the target org."""
    if identity is None or org_id is None:
        return
    if identity.role in ("OrgAdmin", "DeploymentAdmin"):
        if identity.admin is None or identity.admin["org_id"] != org_id:
            raise err_identity_mismatch("Admin not in resource's organization")
