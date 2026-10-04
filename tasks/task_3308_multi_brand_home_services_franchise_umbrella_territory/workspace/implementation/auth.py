"""PRD 2.1 / 2.5 rungs 1-2: authentication, role authorization, ownership.

Every request carries `X-User-ID` and `X-User-Role`.  A missing pair, or an
`X-User-Role` that names no declared role, is ERR_UNAUTHENTICATED (401).  A
declared role that is not on the endpoint's list is ERR_UNAUTHORIZED (403).

Only `FranchiseeOperator` is entity-backed: for that role `X-User-ID` is the
`id` of the acting Franchisee.  For `FranchiseAdmin` and `ComplianceAuditor`
the identifier is opaque and is never compared to an entity's id.
"""
from flask import request

from config import ROLES
from errors import ApiError


def authenticate():
    """Rung 1.  Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return uid, role


def authorize(role, allowed):
    """Rung 2."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def guard(allowed):
    """Rungs 1+2 in one call.  Returns (user_id, role)."""
    uid, role = authenticate()
    authorize(role, allowed)
    return uid, role


def acting_franchisee(uid, role):
    """The Franchisee id the caller acts as, or None for opaque roles."""
    return uid if role == "FranchiseeOperator" else None


def require_receiving_franchisee(uid, role, agreement):
    """ERR_NOT_RECEIVING_FRANCHISEE -- referral/lead actions."""
    if role == "FranchiseeOperator" and uid != agreement.get("franchisee_id"):
        raise ApiError("ERR_NOT_RECEIVING_FRANCHISEE")


def require_performing_franchisee(uid, role, agreement):
    """ERR_NOT_PERFORMING_FRANCHISEE -- work-order actions."""
    if role == "FranchiseeOperator" and uid != agreement.get("franchisee_id"):
        raise ApiError("ERR_NOT_PERFORMING_FRANCHISEE")


def require_referral_party(uid, role, originating, receiving):
    """ERR_NOT_REFERRAL_PARTY -- a dispute by an uninvolved franchisee."""
    if role != "FranchiseeOperator":
        return
    parties = {originating.get("franchisee_id"), receiving.get("franchisee_id")}
    if uid not in parties:
        raise ApiError("ERR_NOT_REFERRAL_PARTY")