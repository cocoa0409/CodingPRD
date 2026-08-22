"""Authentication and role authorisation (PRD 2.1, order-of-rejection steps 1-2)."""
from flask import request

from errors import ApiError

ROLE_TAO = "TransferAgentOperator"
ROLE_FA = "FundAccountant"
ROLE_CO = "ComplianceOfficer"
ROLE_DEALER = "DealerOperations"
ROLE_HOLDER = "AccountHolder"

ALL_ROLES = (ROLE_TAO, ROLE_FA, ROLE_CO, ROLE_DEALER, ROLE_HOLDER)
KNOWN_ROLES = set(ALL_ROLES)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_holder(self):
        return self.role == ROLE_HOLDER

    @property
    def is_dealer(self):
        return self.role == ROLE_DEALER


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Valid X-User-ID and X-User-Role headers are required.")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return Caller(user_id, role)
