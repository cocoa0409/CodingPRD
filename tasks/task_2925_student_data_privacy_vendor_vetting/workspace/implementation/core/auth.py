"""Authentication, role authorization and reference resolution.

Ladder rungs 1 (ERR_UNAUTHENTICATED), 2 (ERR_UNAUTHORIZED), 4/5 (not-found) and
6 (ERR_NOT_RESOURCE_OWNER) live here; PRD 2.1, 2.5 and 2.6.
"""
from flask import request

from . import store
from .errors import ApiError

ROLES = ("Teacher", "PrivacyAnalyst", "VendorLiaison", "PrivacyOfficeAdmin", "TelemetryAgent")


def actor(*allowed_roles):
    """Rungs 1 and 2. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


_NOT_FOUND = {
    "vendor": "ERR_VENDOR_NOT_FOUND",
    "subprocessor": "ERR_SUBPROCESSOR_NOT_FOUND",
    "application": "ERR_APPLICATION_NOT_FOUND",
    "teacher": "ERR_TEACHER_NOT_FOUND",
    "analyst": "ERR_ANALYST_NOT_FOUND",
    "request": "ERR_REQUEST_NOT_FOUND",
    "review": "ERR_REVIEW_NOT_FOUND",
    "commitment": "ERR_COMMITMENT_NOT_FOUND",
    "entry": "ERR_CATALOG_ENTRY_NOT_FOUND",
    "detection": "ERR_DETECTION_NOT_FOUND",
    "incident": "ERR_INCIDENT_NOT_FOUND",
}

_COLLECTION = {
    "vendor": store.vendors,
    "subprocessor": store.subprocessors,
    "application": store.applications,
    "teacher": store.teachers,
    "analyst": store.analysts,
    "request": store.requests,
    "review": store.reviews,
    "commitment": store.commitments,
    "entry": store.catalog_entries,
    "detection": store.detections,
    "incident": store.incidents,
}


def need(kind, row_id):
    """Rungs 4 and 5: resolve an id or raise the entity's own 404."""
    row = _COLLECTION[kind].get(row_id)
    if row is None:
        raise ApiError(_NOT_FOUND[kind], "No %s with id %r." % (kind, row_id))
    return row


def owner_or_403(condition):
    if not condition:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def sod_or_403(condition):
    if not condition:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
