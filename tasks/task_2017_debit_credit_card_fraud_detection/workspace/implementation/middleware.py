"""Auth header extraction, role checking, and common-field stamping."""

import uuid

from flask import request

import db
import errors

ROLES = {
    "FraudAnalyst",
    "FraudOpsManager",
    "LossAccountant",
    "RecoverySpecialist",
    "Cardholder",
    "NetworkGateway",
}


def get_auth():
    """Extract X-User-ID and X-User-Role; raise ERR_UNAUTHENTICATED on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.err_unauthenticated()
    return user_id, role


def require_role(*allowed_roles):
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise errors.err_forbidden_role()
    return user_id, role


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return db.get_clock_iso()


def stamp_new(record: dict) -> dict:
    """Attach id, created_at, updated_at, version to a new record."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record: dict) -> None:
    """Bump updated_at and version on a mutated record."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
