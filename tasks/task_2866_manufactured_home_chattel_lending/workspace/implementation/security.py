"""Actors, role-based access control and ownership (PRD 2.1, 2.7 rungs 1-3)."""

from flask import request

import store
from errors import ApiError

PLATFORM_ADMIN = "PlatformAdmin"
CREDIT_ANALYST = "CreditAnalyst"
CLOSING_AGENT = "ClosingAgent"
SERVICER = "Servicer"
RECOVERY_MANAGER = "RecoveryManager"
COMMUNITY_OPERATOR = "CommunityOperator"
BORROWER = "Borrower"

ALL_ROLES = (PLATFORM_ADMIN, CREDIT_ANALYST, CLOSING_AGENT, SERVICER,
             RECOVERY_MANAGER, COMMUNITY_OPERATOR, BORROWER)

STAFF = (PLATFORM_ADMIN, CREDIT_ANALYST, CLOSING_AGENT, SERVICER, RECOVERY_MANAGER)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_staff(self):
        return self.role in STAFF

    @property
    def is_operator(self):
        return self.role == COMMUNITY_OPERATOR

    @property
    def is_borrower(self):
        return self.role == BORROWER


def authenticate():
    """Rung 1: both headers present and X-User-Role a declared role."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if not user_id.strip() or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return Actor(user_id, role)


def require(*roles):
    """Rungs 1 and 2: authenticate, then authorize the endpoint's role list."""
    actor = authenticate()
    if actor.role not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return actor


def deny_ownership():
    raise ApiError("ERR_NOT_RESOURCE_OWNER")


# --------------------------------------------------------------------------
# ownership (rung 3). Opaque operator identities are never subject to it.
# --------------------------------------------------------------------------

def owns_community(actor, community_id):
    return actor.user_id == community_id


def owns_borrower(actor, borrower_id):
    return actor.user_id == borrower_id


def borrower_owns_unit(actor, unit):
    if unit.get("land_owner_borrower_id") == actor.user_id:
        return True
    for loan in store.loans.values():
        if loan["unit_id"] == unit["id"] and loan["borrower_id"] == actor.user_id:
            return True
    return False


def check_community_scope(actor, community_id):
    if actor.is_operator and not owns_community(actor, community_id):
        deny_ownership()


def check_unit_scope(actor, unit):
    if actor.is_operator:
        if unit.get("community_id") != actor.user_id:
            deny_ownership()
    elif actor.is_borrower:
        if not borrower_owns_unit(actor, unit):
            deny_ownership()


def check_loan_scope(actor, loan):
    if actor.is_borrower and loan["borrower_id"] != actor.user_id:
        deny_ownership()
    if actor.is_operator:
        unit = store.units.get(loan["unit_id"])
        if unit is None or unit.get("community_id") != actor.user_id:
            deny_ownership()


def check_borrower_scope(actor, borrower_id):
    if actor.is_borrower and not owns_borrower(actor, borrower_id):
        deny_ownership()


def narrow_units(actor, records):
    if actor.is_operator:
        return [u for u in records if u.get("community_id") == actor.user_id]
    if actor.is_borrower:
        return [u for u in records if borrower_owns_unit(actor, u)]
    return records


def narrow_loans(actor, records):
    if actor.is_borrower:
        return [l for l in records if l["borrower_id"] == actor.user_id]
    if actor.is_operator:
        out = []
        for loan in records:
            unit = store.units.get(loan["unit_id"])
            if unit is not None and unit.get("community_id") == actor.user_id:
                out.append(loan)
        return out
    return records


def narrow_by_loan(actor, records):
    """Narrow rows that hang off a loan (policies, payments, recovery cases)."""
    if not (actor.is_borrower or actor.is_operator):
        return records
    out = []
    for row in records:
        loan = store.loans.get(row.get("loan_id"))
        if loan is None:
            continue
        if actor.is_borrower:
            if loan["borrower_id"] == actor.user_id:
                out.append(row)
        else:
            unit = store.units.get(loan["unit_id"])
            if unit is not None and unit.get("community_id") == actor.user_id:
                out.append(row)
    return out
