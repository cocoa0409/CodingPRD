import hashlib

from flask import request

import db
from errors import err_unauthenticated, err_unauthorized
from helpers import body

ROLES = [
    "AgencyAdmin", "DeviceCoordinator", "Officer", "Supervisor",
    "RedactionTechnician", "RecordsOfficer", "Prosecutor", "DefenseCounsel",
]

SUPERVISOR_RANKS = ("SERGEANT", "LIEUTENANT")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return {"user_id": user_id, "role": role}


def require_roles(actor, *roles):
    if actor["role"] not in roles:
        raise err_unauthorized()


def check_supervisor_rank(actor):
    """Entity-backed Supervisor: X-User-ID must be an Officer ranked SERGEANT or LIEUTENANT."""
    officer = db.collection("officers").get(actor["user_id"])
    if officer is None or officer.get("rank") not in SUPERVISOR_RANKS:
        raise err_unauthorized("Supervisor role requires rank SERGEANT or LIEUTENANT")
    return officer


def check_officer_exists(actor):
    """Entity-backed Officer: X-User-ID must resolve to an Officer record."""
    officer = db.collection("officers").get(actor["user_id"])
    if officer is None:
        raise err_unauthorized("X-User-ID is not a known officer")
    return officer


def compute_content_hash(payload):
    """Server-side recompute of the media payload hash.

    Uploads may carry an opaque `payload` field; when present the server hashes
    it, otherwise the uploader-supplied hash stands in for the payload itself.
    """
    try:
        data = body()
    except Exception:
        data = {}
    payload_value = payload if payload is not None else data.get("payload")
    if payload_value is None:
        return None
    if not isinstance(payload_value, str):
        payload_value = str(payload_value)
    return hashlib.sha256(payload_value.encode("utf-8")).hexdigest()
