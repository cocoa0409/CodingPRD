"""Ladder steps 1-6: authentication, authorization, path resolution, identity scope.

PRD §2.1 / §2.7.  Headers are exactly `X-User-ID` and `X-User-Role`.
"""

import functools

from flask import request

from errors import ApiError
from store import db

ROLES = (
    "GpoAdmin",
    "RebateAnalyst",
    "DisputeArbiter",
    "MemberOperator",
    "DistributorFeed",
    "ManufacturerRep",
)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Ladder steps 1-3.  Returns a Caller or raises."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    # step 1 - both headers present and non-empty
    if user_id is None or role is None or user_id == "" or role == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    # step 2 - role is one of the six declared names, exact case
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    # step 3 - role appears in the endpoint's authorized role list
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return Caller(user_id, role)


def endpoint(*allowed_roles):
    """Decorator applying ladder steps 1-3 and injecting the caller."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            caller = authenticate(allowed_roles)
            return fn(caller, *args, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# step 4 - path identifier resolution, left to right
# --------------------------------------------------------------------------

_COLLECTIONS = {
    "tier": ("program_tiers", "ERR_PROGRAM_TIER_NOT_FOUND"),
    "distributor": ("distributors", "ERR_DISTRIBUTOR_NOT_FOUND"),
    "member": ("members", "ERR_MEMBER_NOT_FOUND"),
    "letter": ("letters", "ERR_LETTER_NOT_FOUND"),
    "deal": ("deals", "ERR_DEAL_NOT_FOUND"),
    "item": ("items", "ERR_CONTRACTED_ITEM_NOT_FOUND"),
    "rate_card": ("rate_cards", "ERR_RATE_CARD_NOT_FOUND"),
    "batch": ("batches", "ERR_BATCH_NOT_FOUND"),
    "line": ("lines", "ERR_PURCHASE_LINE_NOT_FOUND"),
    "accrual": ("accruals", "ERR_ACCRUAL_NOT_FOUND"),
    "claim": ("claims", "ERR_CLAIM_NOT_FOUND"),
    "dispute": ("disputes", "ERR_DISPUTE_NOT_FOUND"),
    "review": ("reviews", "ERR_COMPLIANCE_REVIEW_NOT_FOUND"),
}


def collection(kind):
    return getattr(db, _COLLECTIONS[kind][0])


def find(kind, record_id):
    if not isinstance(record_id, str):
        return None
    return collection(kind).get(record_id)


def resolve(kind, record_id):
    """Resolve an identifier or raise the not-found code belonging to its type."""
    rec = find(kind, record_id)
    if rec is None:
        raise ApiError(_COLLECTIONS[kind][1])
    return rec


# --------------------------------------------------------------------------
# steps 5 and 6 - identity scoping for the two entity-backed roles
# --------------------------------------------------------------------------

def require_member_scope(caller, owning_member_id):
    if caller.role == "MemberOperator" and caller.user_id != owning_member_id:
        raise ApiError("ERR_MEMBER_SCOPE_VIOLATION")


def require_distributor_scope(caller, owning_distributor_id):
    if caller.role == "DistributorFeed" and caller.user_id != owning_distributor_id:
        raise ApiError("ERR_DISTRIBUTOR_SCOPE_VIOLATION")
