"""Authentication, role gating and participant row-scoping (PRD 2.1 and 2.6)."""

from flask import request

from errors import ApiError

ROLES = (
    "PlanAdministrator",
    "BoardMember",
    "DelegatedOfficer",
    "ComplianceOfficer",
    "Participant",
    "Auditor",
)

# Role names used as convenience constants.
PLAN_ADMIN = "PlanAdministrator"
BOARD = "BoardMember"
DELEGATED = "DelegatedOfficer"
COMPLIANCE = "ComplianceOfficer"
PARTICIPANT = "Participant"
AUDITOR = "Auditor"


class Actor(object):
    __slots__ = ("user_id", "role", "body")

    def __init__(self, user_id, role, body):
        self.user_id = user_id
        self.role = role
        self.body = body


def _body():
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def authenticate():
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = request.headers.get("X-Role")
    if role is None:
        role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return Actor(user_id, role, _body())


def begin(*roles):
    """Authenticate, then apply the role gate before any path resolution."""
    actor = authenticate()
    if roles and actor.role not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return actor


def scope(actor, participant_id):
    """Row-level scoping: a Participant may only reach their own records."""
    if actor.role == PARTICIPANT and participant_id is not None:
        if actor.user_id != participant_id:
            raise ApiError("ERR_PARTICIPANT_SCOPE_VIOLATION")
