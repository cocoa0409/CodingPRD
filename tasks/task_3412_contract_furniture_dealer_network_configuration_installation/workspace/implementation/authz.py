# Auth middleware + ownership scope (PRD 2.1, 2.9 steps 1/2/4).
from flask import request

import constants
import errors
import state


def authenticate():
    """Step 1: X-User-ID and X-User-Role present, role known -> (role, user_id)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or role not in constants.ROLES:
        errors.unauthenticated()
    return role, user_id


def require_roles(role, allowed):
    """Step 2: role authorization against the endpoint's role list."""
    if role not in allowed:
        errors.unauthorized_role()


def check_dealer_ownership(resource_dealer_id, role, user_id):
    """Step 4 for DealerRep-scoped resources (PRD 2.1)."""
    if role == "DealerRep" and resource_dealer_id != user_id:
        errors.forbidden_ownership()


def check_order_ownership(order, role, user_id):
    """Ownership of an order: DealerRep matches order.dealer_id; EndUserRep matches
    the end_user_id of the order's volume agreement (PRD 2.1)."""
    if role == "DealerRep":
        if order["dealer_id"] != user_id:
            errors.forbidden_ownership()
    elif role == "EndUserRep":
        agreement = state.agreements.get(order["volume_agreement_id"])
        if agreement is None or agreement["end_user_id"] != user_id:
            errors.forbidden_ownership()
    # ManufacturerAdmin: opaque identity, never scoped.


def check_phase_ownership(phase, role, user_id):
    order = state.orders.get(phase["project_order_id"])
    if order is None:
        errors.forbidden_ownership()
    check_order_ownership(order, role, user_id)


def check_window_ownership(window, role, user_id):
    phase = state.phases.get(window["installation_phase_id"])
    if phase is None:
        errors.forbidden_ownership()
    check_phase_ownership(phase, role, user_id)


def check_punch_ownership(ticket, role, user_id):
    phase = state.phases.get(ticket["installation_phase_id"])
    if phase is None:
        errors.forbidden_ownership()
    check_phase_ownership(phase, role, user_id)


def check_claim_ownership(claim, role, user_id):
    order = state.orders.get(claim["project_order_id"])
    if order is None:
        errors.forbidden_ownership()
    check_order_ownership(order, role, user_id)


def order_visible_to(order, role, user_id):
    """Boolean scope predicate for list endpoints (scoping, not 403)."""
    if role == "ManufacturerAdmin":
        return True
    if role == "DealerRep":
        return order["dealer_id"] == user_id
    agreement = state.agreements.get(order["volume_agreement_id"])
    return agreement is not None and agreement["end_user_id"] == user_id
