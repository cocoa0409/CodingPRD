"""Authentication, authorization and Shipper ownership (PRD 2.1, rungs 1, 2 and 6)."""
from flask import request

import config
import store
from errors import ApiError


def authenticate():
    """Rung 1: both headers present, non-empty, and a declared role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role are required.")
    if user_id == "" or role == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role must be non-empty.")
    if role not in config.ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role %r." % role)
    return user_id, role


def authorize(role, allowed_roles):
    """Rung 2: the acting role appears among the endpoint's authorized roles."""
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)


def require(allowed_roles):
    """Run rungs 1 and 2 together; returns (user_id, role)."""
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return user_id, role


def is_shipper(role):
    return role == config.ROLE_SHIPPER


def check_contract_ownership(contract, user_id, role):
    """Rung 6: a Shipper may only touch contracts whose shipper_id is its own id."""
    if role != config.ROLE_SHIPPER:
        return
    if contract is None or contract["shipper_id"] != user_id:
        raise ApiError("ERR_CONTRACT_NOT_OWNED", "This contract belongs to another shipper.")


def contract_of_nomination(nomination):
    return store.contracts.get(nomination["contract_id"])


def contract_of_ticket(ticket):
    nomination = store.nominations.get(ticket["nomination_id"])
    if nomination is None:
        return None
    return store.contracts.get(nomination["contract_id"])


def visible_contract_ids(user_id, role):
    """The contract ids a Shipper may see; None means 'no narrowing'."""
    if role != config.ROLE_SHIPPER:
        return None
    return {c["id"] for c in store.contracts_of_shipper(user_id)}
