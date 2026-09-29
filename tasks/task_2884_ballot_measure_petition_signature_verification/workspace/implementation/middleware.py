"""Auth header extraction, role recognition, endpoint authorisation, ownership.

Priority 1 -> X-User-ID and X-User-Role both present and non-empty.
Priority 2 -> X-User-Role is one of the seven recognised roles.
Priority 3 -> the role appears on the endpoint's permitted list.
Priority 7 -> ownership / identity binding.
"""

from flask import g, request

from errors import ApiError

ROLES = (
    "SosAdmin",
    "ElectionsExaminer",
    "TitleExaminer",
    "Proponent",
    "CountyClerk",
    "CirculatorAgent",
    "Challenger",
)


def require_auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES:
        raise ApiError("ERR_INVALID_ROLE")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.role = role
    return user_id, role


# ---------------------------------------------------------------------------
# ownership helpers (priority 7)
# ---------------------------------------------------------------------------
def require_petition_owner(petition, user_id, role):
    """A Proponent may act on a petition only when it is theirs."""
    if role == "Proponent" and petition["proponent_user_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_circulator_self(circulator, user_id, role):
    if role == "CirculatorAgent" and circulator["id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_county_match(county_id, user_id, role):
    """A CountyClerk's X-User-ID is a County.id."""
    if role == "CountyClerk" and county_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_batch_owner(batch, user_id, role):
    """Ownership of a batch: clerk by county, agent by circulator, proponent by petition."""
    from db import db
    if role == "CountyClerk" and batch["county_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if role == "CirculatorAgent" and batch["circulator_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if role == "Proponent":
        petition = db.petitions.get(batch["petition_id"])
        if petition is not None and petition["proponent_user_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_challenge_owner(challenge, user_id, role):
    if role == "Challenger" and challenge["challenger_user_id"] != user_id:
        raise ApiError("ERR_NOT_CHALLENGE_OWNER")
