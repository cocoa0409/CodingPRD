"""Authentication, role authorization and entity-backed identity resolution.

Implements rungs 1-4 of the Order of Refusal (PRD 2.5).
"""

from flask import request

from errors import (
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_FORBIDDEN_ROLE,
    ERR_UNAUTHENTICATED,
    raise_error,
)
from store import db

ROLE_CLINIC_ADMIN = "ClinicAdmin"
ROLE_CLINICIAN = "Clinician"
ROLE_PHYSICIAN = "CollaboratingPhysician"
ROLE_FRONT_DESK = "FrontDeskAgent"
ROLE_PATIENT = "Patient"

ALL_ROLES = (
    ROLE_CLINIC_ADMIN,
    ROLE_CLINICIAN,
    ROLE_PHYSICIAN,
    ROLE_FRONT_DESK,
    ROLE_PATIENT,
)

READ_ALL_ROLES = ALL_ROLES

# Entity-backed roles resolve X-User-ID to a persisted row.
_BACKING = {
    ROLE_CLINICIAN: "clinicians",
    ROLE_PHYSICIAN: "physicians",
    ROLE_PATIENT: "patients",
}


class Actor(object):
    __slots__ = ("user_id", "role", "row")

    def __init__(self, user_id, role, row):
        self.user_id = user_id
        self.role = role
        self.row = row

    @property
    def is_clinician(self):
        return self.role == ROLE_CLINICIAN

    @property
    def is_physician(self):
        return self.role == ROLE_PHYSICIAN

    @property
    def is_patient(self):
        return self.role == ROLE_PATIENT

    @property
    def is_admin(self):
        return self.role == ROLE_CLINIC_ADMIN

    @property
    def is_front_desk(self):
        return self.role == ROLE_FRONT_DESK


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value


def authenticate(allowed_roles):
    """Rungs 1-4.  Returns the Actor or raises."""
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")

    # rung 1: header presence / non-emptiness
    if user_id is None or user_id.strip() == "":
        raise_error(ERR_UNAUTHENTICATED, "The X-User-ID header is required.")
    if role is None or role.strip() == "":
        raise_error(ERR_UNAUTHENTICATED, "The X-User-Role header is required.")

    # rung 2: role recognition
    if role not in ALL_ROLES:
        raise_error(
            ERR_UNAUTHENTICATED, "The X-User-Role header names an unknown role."
        )

    # rung 3: role authorization
    if role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_ROLE,
            "The role %s may not call this endpoint." % role,
        )

    # rung 4: identity resolution for entity-backed roles
    row = None
    backing = _BACKING.get(role)
    if backing is not None:
        row = getattr(db, backing).get(user_id)
        if row is None:
            raise_error(
                ERR_FORBIDDEN_ROLE,
                "The X-User-ID does not resolve to a %s row." % role,
            )
    return Actor(user_id, role, row)


def patient_scope(actor, patient_id):
    """Rung 9: a Patient caller may only read their own rows."""
    if actor.role == ROLE_PATIENT and actor.user_id != patient_id:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "A patient may only read their own records.",
        )
