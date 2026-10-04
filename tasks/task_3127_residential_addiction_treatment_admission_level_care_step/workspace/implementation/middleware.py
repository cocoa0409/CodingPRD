"""Identity extraction, role checks and existence helpers."""

import hashlib
import json

from flask import request

from common import DECLARED_ROLES, body_of
from db import STORE
from errors import ApiError

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"
HEADER_IDEMPOTENCY = "Idempotency-Key"

ENTITY_BACKED_ROLE = {"Clinician": "Clinician"}


def caller():
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError("ERR_MISSING_USER_CONTEXT_HEADER")
    if role not in DECLARED_ROLES:
        raise ApiError("ERR_MISSING_USER_CONTEXT_HEADER")
    return user_id, role


def require_roles(user_id, role, allowed):
    """`Any` covers the read surface only: it is listed explicitly in the
    roles of every read endpoint and is never implicitly granted a write."""
    if role not in set(allowed):
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS")
    backing = ENTITY_BACKED_ROLE.get(role)
    if backing is not None:
        if STORE.get(backing, user_id) is None:
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS")
    return role


def json_body():
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:
        parsed = None
    if parsed is None:
        return {}
    return body_of(parsed)


def body_fingerprint(body):
    try:
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    except Exception:
        return hashlib.sha256(repr(sorted(body.items())).encode("utf-8")).hexdigest()


def check_idempotency(scope, body):
    """When the Idempotency-Key header is supplied, it must not already be
    bound to a different request body for the same operation."""
    key = request.headers.get(HEADER_IDEMPOTENCY)
    if key is None or key == "":
        return
    fingerprint = body_fingerprint(body)
    bucket = STORE.idem.setdefault(scope, {})
    if key in bucket and bucket[key] != fingerprint:
        raise ApiError("ERR_IDEMPOTENCY_KEY_CONFLICT")
    bucket[key] = fingerprint


# ---------------------------------------------------------------------------
# Path existence resolution (left to right, short-circuiting)
# ---------------------------------------------------------------------------

def facility_in_path(facility_id):
    facility = STORE.get("Facility", facility_id)
    if facility is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    return facility


def episode_in_path(facility, episode_id):
    episode = STORE.get("TreatmentEpisode", episode_id)
    if episode is None or episode.get("_facility_id") != facility["id"]:
        raise ApiError("ERR_EPISODE_NOT_FOUND")
    return episode


def child_in_path(entity, record_id, facility, entity_error, episode=None):
    record = STORE.get(entity, record_id)
    if record is None or record.get("_facility_id") != facility["id"]:
        raise ApiError(entity_error)
    if episode is not None and record.get("_episode_id") != episode["id"]:
        raise ApiError(entity_error)
    return record


def resolve_service(service_id, facility):
    service = STORE.get("ServiceOffering", service_id)
    if service is None:
        # PRD §2.7: a body field naming a ServiceOffering that does not exist is
        # ERR_SERVICE_NOT_FOUND, but "a reference that exists but belongs to a
        # different facility from the one in the path" is ERR_INVALID_REFERENCE.
        raise ApiError("ERR_SERVICE_NOT_FOUND")
    if service.get("_facility_id") != facility["id"]:
        raise ApiError("ERR_INVALID_REFERENCE")
    return service


def resolve_clinician(clinician_id):
    clinician = STORE.get("Clinician", clinician_id)
    if clinician is None:
        raise ApiError("ERR_CLINICIAN_NOT_FOUND")
    return clinician


def resolve_payer(payer_id):
    payer = STORE.get("Payer", payer_id)
    if payer is None:
        raise ApiError("ERR_PAYER_NOT_FOUND")
    return payer