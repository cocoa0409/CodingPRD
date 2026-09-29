"""Authentication and role authorisation (PRD sections 2.1 and 2.10 steps 1-2)."""

from flask import request

from errors import ApiError

ROLES = (
    "ManufacturerAdmin",
    "DesignConsultant",
    "ComplianceOfficer",
    "ClientRepresentative",
    "InstallerOperator",
    "SafetyAuditor",
)

ALL_ROLES = list(ROLES)

READ_ROLES = list(ROLES)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Header presence, role recognition, then endpoint authorisation."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unrecognised role '{}'.".format(role))
    if role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role '{}' is not authorised for this operation.".format(role),
        )
    return Caller(user_id, role)
