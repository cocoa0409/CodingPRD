"""Authentication, RBAC and actor resolution (PRD 2.1, rejection ladder rungs 1-3)."""

from flask import request

import store
from errors import ApiError

ROLES = (
    "EyeBankCoordinator",
    "RecoveryTechnician",
    "EvaluationTechnician",
    "LabTechnician",
    "Surgeon",
    "MedicalDirector",
)

TECHNICIAN_ROLES = ("RecoveryTechnician", "EvaluationTechnician")
ENTITY_BACKED = ("RecoveryTechnician", "EvaluationTechnician", "Surgeon")


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_technician(self):
        return self.role in TECHNICIAN_ROLES

    @property
    def is_surgeon(self):
        return self.role == "Surgeon"

    @property
    def is_entity_backed(self):
        return self.role in ENTITY_BACKED


def authenticate(allowed_roles):
    """Rung 1: both headers present and the role recognised.
    Rung 2: the role appears in the endpoint's role list.
    Rung 3: an entity-backed role resolves to a live row.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    if role in TECHNICIAN_ROLES:
        if user_id not in store.DB["technicians"]:
            raise ApiError("ERR_UNKNOWN_ACTOR")
    elif role == "Surgeon":
        if user_id not in store.DB["surgeons"]:
            raise ApiError("ERR_UNKNOWN_ACTOR")
    return Actor(user_id, role)


def body_dict():
    raw = request.get_json(silent=True)
    if isinstance(raw, dict):
        return raw
    return {}
