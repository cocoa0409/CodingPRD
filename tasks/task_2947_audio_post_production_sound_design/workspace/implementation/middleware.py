"""Authentication, RBAC, path resolution, reference resolution and the project
gates — rungs 1, 2, 3-11, 16, 17 and 18 of the PRD §2.11 ladder."""

from flask import request

import derive
from db import db
from errors import ApiError
from validation import ROLES


def actor(*allowed_roles):
    """Rung 1 then rung 2: authentication strictly before authorisation."""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


# ------------------------------------------------------ path parameters (3-8)
def path_project(project_id):
    record = db.projects.get(project_id)
    if record is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    return record


def path_stem_package(stem_package_id):
    record = db.stem_packages.get(stem_package_id)
    if record is None:
        raise ApiError("ERR_STEM_PACKAGE_NOT_FOUND")
    return record


def path_deliverable(deliverable_id):
    record = db.deliverables.get(deliverable_id)
    if record is None:
        raise ApiError("ERR_DELIVERABLE_NOT_FOUND")
    return record


def path_mix_booking(booking_id):
    record = db.mix_bookings.get(booking_id)
    if record is None:
        raise ApiError("ERR_MIX_BOOKING_NOT_FOUND")
    return record


def path_adr_session(session_id):
    record = db.adr_sessions.get(session_id)
    if record is None:
        raise ApiError("ERR_ADR_SESSION_NOT_FOUND")
    return record


def path_library_asset(asset_id):
    record = db.library_assets.get(asset_id)
    if record is None:
        raise ApiError("ERR_LIBRARY_ASSET_NOT_FOUND")
    return record


def path_generic(collection, record_id):
    """Facility records without a dedicated spine error in PRD §2.6 fall back to
    the catalogue's only other 404, ERR_REFERENCE_NOT_FOUND."""
    record = collection.get(record_id)
    if record is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return record


# --------------------------------------------------------- body references (9)
def body_ref(payload, field, collection):
    """Rung 9.  A field that is absent, null, non-string or empty is left to the
    schema rung (12); a supplied identifier that does not resolve is a 404."""
    if field not in payload:
        return None
    value = payload[field]
    if not isinstance(value, str) or value == "":
        return None
    record = collection.get(value)
    if record is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return record


# ------------------------------------------------------------- ownership (10, 11)
def require_assigned_mixer(user_id, booking):
    if user_id != booking["mixer_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_MIXER")


def require_project_client(user_id, role, project):
    """Rung 11 applies only when the caller acts as ClientReviewer."""
    if role == "ClientReviewer" and user_id != project["client_user_id"]:
        raise ApiError("ERR_NOT_PROJECT_CLIENT")


# ------------------------------------------------------------- project gates
def gate_posture(project, operation):
    """Rung 16.  FROZEN rejects every child write in the PRD §2.9 list;
    RESTRICTED rejects only QC submission, QC evaluation, delivery and archival.
    Both answer ERR_PROJECT_FROZEN."""
    if project["posture"] == "FROZEN":
        raise ApiError("ERR_PROJECT_FROZEN")
    if project["posture"] == "RESTRICTED" and operation in derive.RESTRICTED_BLOCKED_OPS:
        raise ApiError("ERR_PROJECT_FROZEN")


def gate_archived(project):
    """Rung 17."""
    if project["pipeline_stage"] == "ARCHIVED":
        raise ApiError("ERR_PROJECT_ARCHIVED")


def gate_picture_locked(project):
    """Rung 18."""
    if project["picture_status"] != "LOCKED":
        raise ApiError("ERR_PICTURE_NOT_LOCKED")
