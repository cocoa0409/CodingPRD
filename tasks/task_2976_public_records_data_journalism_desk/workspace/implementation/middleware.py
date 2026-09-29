"""Authentication and RBAC (PRD sections 2.1 and 2.11 rungs 1-3)."""
from flask import request

from errors import ApiError

ROLE_RECORDS_COORDINATOR = "RecordsCoordinator"
ROLE_DATA_REPORTER = "DataReporter"
ROLE_PEER_REVIEWER = "PeerReviewer"
ROLE_EXPERT_REVIEWER = "ExpertReviewer"
ROLE_MANAGING_EDITOR = "ManagingEditor"
ROLE_LEGAL_COUNSEL = "LegalCounsel"

ALL_ROLES = (
    ROLE_RECORDS_COORDINATOR,
    ROLE_DATA_REPORTER,
    ROLE_PEER_REVIEWER,
    ROLE_EXPERT_REVIEWER,
    ROLE_MANAGING_EDITOR,
    ROLE_LEGAL_COUNSEL,
)

USER_ID_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


def authenticate(allowed_roles):
    """Rungs 1-3 of the rejection ladder.

    1. Both headers must be present and non-empty  -> ERR_UNAUTHENTICATED
    2. The role must be one of the six known roles -> ERR_UNAUTHENTICATED
    3. The role must be permitted on this endpoint -> ERR_ROLE_NOT_PERMITTED

    Returns (user_id, role).
    """
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if user_id is None or role is None or user_id == "" or role == "":
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Both %s and %s headers are required and must be non-empty." % (USER_ID_HEADER, ROLE_HEADER),
        )
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unrecognized role '%s'." % role)
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role '%s' is not permitted to perform this operation." % role,
        )
    return user_id, role
