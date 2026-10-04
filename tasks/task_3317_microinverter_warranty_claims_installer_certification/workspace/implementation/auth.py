"""Authentication, authorization and the shared lookup helpers.

Auth is settled before anything else in the request is inspected (PRD 2.1 and
2.5): the two headers must be present and the role must be one of the four
declared roles, then the role must be permitted for the operation.
"""

from functools import wraps

from flask import g, request

import db
from errors import fail

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_INSTALLER = "Installer"
ROLE_MONITORING = "MonitoringService"
ROLE_HOMEOWNER = "Homeowner"

ROLES = (ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_MONITORING, ROLE_HOMEOWNER)

HEADER_ROLE = "X-User-Role"
HEADER_ID = "X-User-ID"


def principal():
    """Read and validate the two headers; cached per request."""
    if getattr(g, "_principal", None) is not None:
        return g._principal
    role = request.headers.get(HEADER_ROLE)
    user_id = request.headers.get(HEADER_ID)
    if role is None or user_id is None:
        fail("ERR_UNAUTHENTICATED")
    role = role.strip()
    user_id = user_id.strip()
    if role not in ROLES or user_id == "":
        fail("ERR_UNAUTHENTICATED")
    g._principal = (role, user_id)
    return g._principal


def require(*roles, any_role=False):
    """Declare the roles permitted for a route.

    `any_role=True` marks a read reachable by every authenticated role.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            role, _user_id = principal()
            if not any_role and role not in roles:
                fail("ERR_UNAUTHORIZED")
            return view(*args, **kwargs)

        wrapper.__prd_roles__ = roles
        wrapper.__prd_any_role__ = any_role
        return wrapper

    return decorator


def acting_installer_id():
    """X-User-ID when the caller is an Installer; None for opaque roles."""
    role, user_id = principal()
    if role == ROLE_INSTALLER:
        return user_id
    return None


def acting_installer():
    """The Installer row named by X-User-ID, or None if it does not resolve."""
    installer_id = acting_installer_id()
    if installer_id is None:
        return None
    return db.DB.installers.get(installer_id)


# ------------------------------------------------------------------- lookups


def get_installer(installer_id):
    row = db.DB.installers.get(installer_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no installer with id %s" % installer_id)
    return row


def get_design_project(project_id):
    row = db.DB.design_projects.get(project_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no design project with id %s" % project_id)
    return row


def get_lot(lot_id):
    row = db.DB.production_lots.get(lot_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no production lot with id %s" % lot_id)
    return row


def get_system(system_id):
    row = db.DB.systems.get(system_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no system registration with id %s" % system_id)
    return row


def get_unit(unit_id):
    row = db.DB.units.get(unit_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no unit with id %s" % unit_id)
    return row


def get_claim(claim_id):
    row = db.DB.claims.get(claim_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no warranty claim with id %s" % claim_id)
    return row


def get_reimbursement(reimbursement_id):
    row = db.DB.reimbursements.get(reimbursement_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no labor reimbursement with id %s" % reimbursement_id)
    return row


def get_transfer(transfer_id):
    row = db.DB.transfers.get(transfer_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no warranty transfer with id %s" % transfer_id)
    return row


def get_campaign(campaign_id):
    row = db.DB.campaigns.get(campaign_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no proactive campaign with id %s" % campaign_id)
    return row


def get_order(order_id):
    row = db.DB.replacement_orders.get(order_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no replacement order with id %s" % order_id)
    return row


def resolve_body_fk(value, lookup, label):
    """Body-referenced foreign keys are checked as a group (PRD 2.5, priority 5)."""
    if value is None:
        return None
    if lookup(value) is None:
        fail("ERR_RESOURCE_NOT_FOUND", "%s %s does not exist" % (label, value))
    return value