"""Authentication, role authorization and ownership (PRD 2.1, 2.6 rungs 1-3)."""

from flask import request

from errors import ApiError

PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
CONFORMITY_REVIEWER = "ConformityReviewer"
MANUFACTURER = "Manufacturer"
TEST_LAB_OPERATOR = "TestLabOperator"
RETAILER = "Retailer"
CONSUMER = "Consumer"

ALL_ROLES = (
    PROGRAM_ADMINISTRATOR,
    CONFORMITY_REVIEWER,
    MANUFACTURER,
    TEST_LAB_OPERATOR,
    RETAILER,
    CONSUMER,
)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def caller(*allowed_roles):
    """Rung 1 (authentication) then rung 2 (role authorization)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role does not name a declared program role.")
    if allowed_roles and role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED", "Role %s may not invoke this operation." % role
        )
    return Caller(user_id, role)


def own(condition):
    """Rung 3 (ownership)."""
    if not condition:
        raise ApiError(
            "ERR_OWNERSHIP_VIOLATION",
            "The acting principal may only act within its own instance.",
        )


def sod(condition):
    """Rung 4 (segregation of duties)."""
    if not condition:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The acting user id performed an incompatible earlier step.",
        )
