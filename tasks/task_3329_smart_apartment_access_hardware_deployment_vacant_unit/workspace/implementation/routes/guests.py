"""Guest passes and the GUEST credential (PRD 3.6)."""

from flask import request

from db import clock, db, iso, parse_instant, touch
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CREDENTIAL_OUT_OF_SCOPE,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RESIDENT_NOT_ACTIVE,
    ERR_UNIT_SCHEDULE_CONFLICT,
    ApiError,
)
from middleware import require_roles
from records import body, require_value, serialize, validate_body
from response import paged, success
from svc_common import (
    get_guest_pass,
    get_resident,
    get_unit,
    has_schedule_conflict,
    issue_credential,
    new_record,
)


def _ownership(caller, host_resident_id):
    """A Resident may only act on passes whose host_resident_id is its own id."""
    if caller.role == "Resident" and caller.user_id != host_resident_id:
        raise ApiError(
            ERR_FORBIDDEN,
            "A Resident may only manage guest passes on their own id",
        )


@require_roles("PropertyManager", "Resident")
def create_guest_pass(caller, unitId):
    payload = body()
    validate_body(
        payload,
        required=("host_resident_id", "guest_label", "start_at", "end_at"),
    )
    unit = get_unit(unitId)
    host = get_resident(require_value(payload, "host_resident_id"))
    _ownership(caller, host["id"])
    if host.get("status") == "REVOKED":
        raise ApiError(
            ERR_RESIDENT_NOT_ACTIVE, "Host resident is REVOKED and cannot host"
        )
    start = parse_instant(require_value(payload, "start_at"), "start_at")
    end = parse_instant(require_value(payload, "end_at"), "end_at")
    if has_schedule_conflict(unit["id"], start, end):
        raise ApiError(
            ERR_UNIT_SCHEDULE_CONFLICT,
            "The requested window overlaps an existing occupation of the unit",
        )
    if host.get("unit_id") != unit["id"]:
        raise ApiError(
            ERR_CREDENTIAL_OUT_OF_SCOPE, "Host resident is not attached to this unit"
        )
    if host.get("status") not in ("ACTIVE", "DEACTIVATING"):
        raise ApiError(
            ERR_CREDENTIAL_OUT_OF_SCOPE,
            "Host resident status %s cannot back a guest credential" % host.get("status"),
        )
    if end <= start:
        raise ApiError(
            ERR_CREDENTIAL_OUT_OF_SCOPE, "The guest window must end after it starts"
        )
    record = new_record(
        {
            "unit_id": unit["id"],
            "host_resident_id": host["id"],
            "guest_label": require_value(payload, "guest_label"),
            "status": "ACTIVE",
            "start_at": iso(start),
            "end_at": iso(end),
        }
    )
    db.guest_passes[record["id"]] = record
    credential = issue_credential(
        unit_id=unit["id"],
        subject_resident_id=None,
        credential_type="GUEST",
        status="ACTIVE",
        valid_from=iso(start),
        valid_until=iso(end),
    )
    credential["_guest_pass_id"] = record["id"]
    record["_credential_id"] = credential["id"]
    # PRD 2.7: every credential belongs to exactly one unit and the four live
    # states partition the population. A revoked pass is withdrawn along with
    # the door credential it was born with, so no live GUEST row survives the
    # move-out sweep (PRD 3.5 / 3.6).
    credential["_host_resident_id"] = host["id"]
    return success(serialize(record), "object", 201)


@require_roles("PropertyManager", "Resident")
def extend_guest_pass(caller, guestPassId):
    payload = body()
    validate_body(payload, required=("new_end_at",))
    new_end = parse_instant(require_value(payload, "new_end_at"), "new_end_at")
    guest_pass = get_guest_pass(guestPassId)
    _ownership(caller, guest_pass.get("host_resident_id"))
    if guest_pass.get("status") == "REVOKED":
        raise ApiError(
            ERR_ALREADY_TERMINAL, "A REVOKED guest pass cannot be extended"
        )
    if guest_pass.get("status") != "EXPIRED":
        raise ApiError(
            ERR_INVALID_STATE,
            "Guest pass %s is not EXPIRED" % guestPassId,
        )
    host = db.residents.get(guest_pass.get("host_resident_id"))
    if host is None:
        raise ApiError(ERR_INVALID_REQUEST, "Host resident no longer exists")
    if host.get("status") == "REVOKED":
        raise ApiError(
            ERR_RESIDENT_NOT_ACTIVE, "Host resident is REVOKED"
        )
    if new_end <= clock.now:
        raise ApiError(
            ERR_CREDENTIAL_OUT_OF_SCOPE,
            "The new end must be later than the current logical clock",
        )
    if host.get("status") not in ("ACTIVE", "DEACTIVATING"):
        raise ApiError(
            ERR_CREDENTIAL_OUT_OF_SCOPE,
            "Host resident status %s cannot back a guest credential" % host.get("status"),
        )
    guest_pass["status"] = "ACTIVE"
    guest_pass["end_at"] = iso(new_end)
    touch(guest_pass)
    credential = db.access_credentials.get(guest_pass.get("_credential_id"))
    if credential is not None:
        credential["status"] = "ACTIVE"
        credential["valid_until"] = iso(new_end)
        # a revoked GUEST row belongs to its pass; reviving the pass revives it
        credential["_host_resident_id"] = guest_pass.get("host_resident_id")
        touch(credential)
    return success(serialize(guest_pass), "object", 200)


@require_roles("PlatformAdmin", "PropertyManager", "Resident")
def list_guest_passes(caller):
    rows = list(db.guest_passes.values())
    unit_id = request.args.get("unit_id")
    host_resident_id = request.args.get("host_resident_id")
    if unit_id:
        rows = [row for row in rows if row.get("unit_id") == unit_id]
    if host_resident_id:
        rows = [row for row in rows if row.get("host_resident_id") == host_resident_id]
    if caller.role == "Resident":
        rows = [row for row in rows if row.get("host_resident_id") == caller.user_id]
    window, pagination = paged(rows)
    return success([serialize(row) for row in window], "array", 200, pagination)


API_ROUTES = [
    ("POST", "/units/<unitId>/guest-passes", create_guest_pass),
    ("POST", "/guest-passes/<guestPassId>/extend", extend_guest_pass),
    ("GET", "/guest-passes", list_guest_passes),
]