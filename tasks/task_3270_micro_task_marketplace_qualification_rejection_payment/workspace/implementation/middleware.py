"""Authentication and authorisation (PRD §2.1, §2.10 steps 1-2).

Every request carries `X-User-ID` and `X-User-Role`. Both must be present and
must name a registered actor; a missing or unrecognised pairing is refused with
ERR_UNAUTHENTICATED. Identity semantics per role:

  Requester    -> X-User-ID is the id of the acting Requester row
  Worker       -> X-User-ID is the id of the acting Worker row
  PlatformAdmin-> X-User-ID is an opaque operator id, never compared to a row
  Anonymous    -> X-User-ID is opaque; only the two registration endpoints

Authorisation is a second gate: the acting role must be in the endpoint's
permitted set, and requester/worker-owned resources must be touched by their
owner. Failure is ERR_FORBIDDEN.
"""

from db import db
from errors import fail

ROLE_REQUESTER = "Requester"
ROLE_WORKER = "Worker"
ROLE_ADMIN = "PlatformAdmin"
ROLE_ANONYMOUS = "Anonymous"

ALL_ROLES = {ROLE_REQUESTER, ROLE_WORKER, ROLE_ADMIN, ROLE_ANONYMOUS}


def authenticate(headers) -> dict:
    """Resolve X-User-ID / X-User-Role into an acting principal."""
    user_id = headers.get("X-User-ID")
    role = headers.get("X-User-Role")
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED")

    if role == ROLE_REQUESTER:
        row = db.requesters.get(user_id)
        if row is None:
            fail("ERR_UNAUTHENTICATED")
    elif role == ROLE_WORKER:
        row = db.workers.get(user_id)
        if row is None:
            fail("ERR_UNAUTHENTICATED")
    # PlatformAdmin and Anonymous are opaque: nothing to resolve.

    return {"id": user_id, "role": role}


def require_role(principal: dict, allowed) -> None:
    """The role must appear in the endpoint's permitted role set."""
    if ROLE_ADMIN in allowed:
        if principal["role"] == ROLE_ADMIN:
            return
    if principal["role"] not in allowed:
        fail("ERR_FORBIDDEN")


def is_admin(principal: dict) -> bool:
    return principal["role"] == ROLE_ADMIN


def require_owner(principal: dict, owner_id: str) -> None:
    """Requester/worker-owned resources must be touched by their owner.

    PlatformAdmin is not ownership-scoped (PRD §2.4).
    """
    if principal["role"] == ROLE_ADMIN:
        return
    if principal["id"] != owner_id:
        fail("ERR_FORBIDDEN")


def require_owner_or_admin(principal: dict, owner_id: str) -> None:
    if principal["role"] == ROLE_ADMIN:
        return
    if principal["id"] != owner_id:
        fail("ERR_FORBIDDEN")


def resolve(req, allowed, auth_exempt: bool = False) -> dict:
    """Authenticate + authorise in the platform's fixed order (steps 1-2).

    `auth_exempt` covers the endpoints the auth check does not guard:
    requester registration, worker registration, and qualification-type
    creation / the clock controls, which carry their own role rules.
    """
    if auth_exempt:
        # Still resolve the actor when headers are present, so an endpoint can
        # distinguish Anonymous from an authenticated operator.
        headers = req.headers
        if not headers.get("X-User-ID") and not headers.get("X-User-Role"):
            return {"id": None, "role": ROLE_ANONYMOUS}
    principal = authenticate(req.headers)
    if allowed is not None:
        require_role(principal, allowed)
    return principal