"""Auth header extraction, role permission checks and ownership enforcement.

Header names, role names and the split of exclusive/shared operations come from
SCAFFOLD.yaml validations[] (category auth) and roles[], and from PRD 2.1.
"""

from flask import request

import core
from core import ApiError
from db import STORE

ANONYMOUS_PATHS = {"POST /learners"}

ROLE_PERMISSIONS = {
    "Learner": {
        "GET /learners/{id}",
        "PATCH /learners/{id}",
        "GET /course-units/{id}/nodes",
        "GET /lesson-nodes",
        "GET /lesson-nodes/{id}",
        "POST /lesson-nodes/{id}/practice",
        "PUT /lesson-nodes/{id}/review",
        "GET /practice-attempts",
        "GET /practice-attempts/{id}",
        "GET /streak-states",
        "POST /streak-states/{id}/freezes",
        "POST /streak-states/{id}/repair",
        "GET /learners/{id}/family-memberships",
        "GET /subscriptions/{id}/family-memberships",
        "GET /family-memberships",
        "POST /placement-tests",
        "GET /placement-tests",
        "GET /placement-tests/{id}",
        "PUT /placement-tests/{id}",
        "GET /subscriptions",
        "GET /subscriptions/{id}",
        "POST /subscriptions",
        "PUT /subscriptions/{id}",
        "POST /leagues",
        "GET /leagues/{id}",
        "GET /leagues/{id}/standings",
        "GET /leagues/{id}/all-standings",
        "GET /league-standings",
        "GET /league-standings/{id}",
        "POST /certification-exams",
        "GET /certification-exams",
        "GET /certification-exams/{id}",
        "PUT /certification-exams/{id}",
        "GET /engagement-offers",
    },
    "CertificationProctor": {
        "GET /certification-exams/{id}",
        "PUT /certification-exams/{id}",
        "POST /certification-exams/{id}/reports",
        "GET /score-reports",
        "GET /score-reports/{id}",
    },
    "PlatformAdmin": {
        "GET /learners/{id}",
        "PATCH /learners/{id}",
        "POST /course-units",
        "GET /course-units/{id}/nodes",
        "POST /course-units/{id}/nodes",
        "GET /lesson-nodes",
        "GET /lesson-nodes/{id}",
        "GET /practice-attempts",
        "GET /practice-attempts/{id}",
        "GET /streak-states",
        "POST /streak-states/{id}/freezes",
        "GET /learners/{id}/family-memberships",
        "GET /subscriptions/{id}/family-memberships",
        "GET /family-memberships",
        "GET /placement-tests",
        "GET /placement-tests/{id}",
        "GET /subscriptions",
        "GET /subscriptions/{id}",
        "POST /leagues",
        "PUT /leagues/{id}",
        "GET /leagues/{id}",
        "GET /leagues/{id}/standings",
        "GET /leagues/{id}/all-standings",
        "GET /league-standings",
        "GET /league-standings/{id}",
        "GET /certification-exams",
        "GET /certification-exams/{id}",
        "GET /score-reports",
        "GET /score-reports/{id}",
        "POST /engagement-offers",
        "GET /engagement-offers",
        "POST /_clock/set_current_utc",
        "POST /_events/auto-transition",
        "POST /_inject/payment_outcome",
        "POST /_inject/gems",
    },
    "Anonymous": {
        "POST /learners",
    },
}

ROLE_NAMES = ["Learner", "CertificationProctor", "PlatformAdmin", "Anonymous"]


def resolve_role(role_value):
    """Case-insensitive role header, tolerating separators between the words."""
    if role_value is None:
        return None
    compact = "".join(ch for ch in str(role_value).lower() if ch.isalnum())
    for name in ROLE_NAMES:
        if "".join(ch for ch in name.lower() if ch.isalnum()) == compact:
            return name
    return None


def authenticate(route_key):
    """Priority 1: X-User-ID present and non-empty (except registration).
    Priority 2: X-User-Role permitted for the operation."""
    if route_key in ANONYMOUS_PATHS:
        return {"role": "Anonymous", "user_id": request.headers.get("X-User-ID") or ""}
    user_id = request.headers.get("X-User-ID")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError(core.ERR_UNAUTHENTICATED)
    role = resolve_role(request.headers.get("X-User-Role"))
    if role is None:
        raise ApiError(core.ERR_UNAUTHORIZED)
    if route_key not in ROLE_PERMISSIONS.get(role, set()):
        raise ApiError(core.ERR_UNAUTHORIZED)
    return {"role": role, "user_id": str(user_id).strip()}


def is_learner(actor):
    return actor["role"] == "Learner"


def require_learner_exists(actor):
    """Priority 3: the Learner named by X-User-ID must exist for entity-backed
    roles (PRD 2.1)."""
    if actor["role"] != "Learner":
        return None
    row = STORE.learners.get(actor["user_id"])
    if row is None:
        raise ApiError(core.ERR_LEARNER_NOT_FOUND)
    return row


def own(actor, owner_learner_id, allow_admin=True):
    """Ownership: a learner acting on another learner's resource is refused with
    ERR_UNAUTHORIZED at HTTP 403 (PRD 2.1)."""
    if actor["role"] == "Learner" and actor["user_id"] != owner_learner_id:
        raise ApiError(core.ERR_UNAUTHORIZED)
    if actor["role"] == "PlatformAdmin" and not allow_admin:
        raise ApiError(core.ERR_UNAUTHORIZED)


def check_learner_param(actor, learner_id):
    """A learner acting on another learner's resource is refused with
    ERR_UNAUTHORIZED at HTTP 403 (PRD 2.1); an unknown learner is a 404."""
    if actor["role"] == "Learner" and learner_id is not None and learner_id != actor["user_id"]:
        raise ApiError(core.ERR_UNAUTHORIZED)
    if learner_id is not None and learner_id not in STORE.learners:
        raise ApiError(core.ERR_LEARNER_NOT_FOUND)