"""Residents, onboarding, move-out cascade, status events (PRD 3.4, 3.5)."""

from flask import request

from calculations import refresh_connectivity
from db import clock, db, iso, parse_instant, touch
from errors import (
    ERR_INSUFFICIENT_CONNECTIVITY,
    ERR_INVALID_STATE,
    ApiError,
)
from middleware import require_roles
from records import body, require_value, serialize, validate_body
from response import paged, success
from svc_common import (
    append_status_event,
    bubble_resident_to_revoked,
    credentials_for_resident,
    get_property,
    get_resident,
    get_unit,
    issue_credential,
    new_record,
    non_revoked_residents,
    refresh_portal_status,
    revoke_live_credentials,
    set_unit_occupied,
)


def _online_smart_lock(unit_id):
    for device in db.devices.values():
        if device.get("unit_id") != unit_id:
            continue
        if device.get("device_type") != "SMART_LOCK":
            continue
        if device.get("status") == "ONLINE":
            return device
    return None


def _unit_building_connected(unit):
    building_id = unit.get("building_id")
    if not building_id:
        return False
    building = db.buildings.get(building_id)
    if building is None:
        return False
    return refresh_connectivity(building)


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
@require_roles("PlatformAdmin", "PropertyManager")
def create_resident(caller):
    payload = body()
    validate_body(
        payload,
        required=("property_id", "unit_id", "full_name", "email"),
    )
    prop = get_property(require_value(payload, "property_id"))
    unit = get_unit(require_value(payload, "unit_id"))
    record = new_record(
        {
            "property_id": prop["id"],
            "unit_id": unit["id"],
            "full_name": require_value(payload, "full_name"),
            "email": require_value(payload, "email"),
            "status": "PENDING_CREDENTIAL",
            "portal_credential_status": "NOT_ISSUED",
            "notice_end_at": None,
        }
    )
    first_resident = not non_revoked_residents(unit["id"])
    db.residents[record["id"]] = record
    # VACANT -> OCCUPIED on the first resident (PRD 3.1 / 3.4)
    if unit.get("occupancy_status") == "VACANT" and first_resident:
        set_unit_occupied(unit)
    return success(serialize(record), "object", 201)


@require_roles("PlatformAdmin", "PropertyManager")
def list_residents(caller):
    rows = list(db.residents.values())
    property_id = request.args.get("property_id")
    unit_id = request.args.get("unit_id")
    if property_id:
        rows = [row for row in rows if row.get("property_id") == property_id]
    if unit_id:
        rows = [row for row in rows if row.get("unit_id") == unit_id]
    window, pagination = paged(rows)
    return success([serialize(row) for row in window], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------
@require_roles("PropertyManager")
def onboard_resident(caller, residentId):
    payload = body()
    validate_body(payload)
    resident = get_resident(residentId)
    status = resident.get("status")
    if status not in ("PENDING_CREDENTIAL", "DEACTIVATING"):
        raise ApiError(
            ERR_INVALID_STATE,
            "Resident %s cannot be onboarded from status %s" % (residentId, status),
        )
    unit = get_unit(resident["unit_id"])
    if status == "PENDING_CREDENTIAL":
        if unit.get("occupancy_status") not in ("OCCUPIED", "NOTICE"):
            raise ApiError(
                ERR_INSUFFICIENT_CONNECTIVITY,
                "Resident unit is not occupied",
            )
        if _online_smart_lock(unit["id"]) is None:
            raise ApiError(
                ERR_INSUFFICIENT_CONNECTIVITY,
                "No ONLINE SMART_LOCK device is present on the unit",
            )
        if not _unit_building_connected(unit):
            raise ApiError(
                ERR_INSUFFICIENT_CONNECTIVITY,
                "The unit's building does not pass the connectivity check",
            )
        issue_credential(
            unit_id=unit["id"],
            subject_resident_id=resident["id"],
            credential_type="RESIDENT",
            status="ACTIVE",
            valid_from=iso(clock.now),
            valid_until=None,
        )
        resident["status"] = "ACTIVE"
        resident["portal_credential_status"] = "ACTIVE"
        touch(resident)
        append_status_event(resident["id"], "PENDING_CREDENTIAL", "ACTIVE")
        return success(serialize(resident), "object", 200)

    # DEACTIVATING -> ACTIVE (move-out cancellation cycle, PRD 3.4)
    if unit.get("occupancy_status") != "NOTICE":
        raise ApiError(
            ERR_INVALID_STATE,
            "Resident's unit is not in NOTICE; move-out cannot be cancelled",
        )
    resident_credentials = [
        c
        for c in credentials_for_resident(resident["id"])
        if c.get("credential_type") == "RESIDENT"
    ]
    for credential in resident_credentials:
        if credential.get("status") in ("ISSUED", "ACTIVE"):
            credential["status"] = "REVOKED"
            touch(credential)
    revivable = [
        c
        for c in resident_credentials
        if c.get("status") == "REVOKED"
        and c.get("valid_until") is not None
        and parse_instant(c["valid_until"], "valid_until") > clock.now
    ]
    if revivable:
        revivable[0]["status"] = "ACTIVE"
        touch(revivable[0])
    else:
        issue_credential(
            unit_id=unit["id"],
            subject_resident_id=resident["id"],
            credential_type="RESIDENT",
            status="ACTIVE",
            valid_from=iso(clock.now),
            valid_until=None,
        )
    resident["status"] = "ACTIVE"
    refresh_portal_status(resident)
    touch(resident)
    append_status_event(resident["id"], "DEACTIVATING", "ACTIVE")
    return success(serialize(resident), "object", 200)


# ---------------------------------------------------------------------------
# Deactivation / move-out cascade
# ---------------------------------------------------------------------------
@require_roles("PropertyManager")
def deactivate_resident(caller, residentId):
    payload = body()
    validate_body(payload, required=("notice_end_at",))
    notice_end_at = parse_instant(
        require_value(payload, "notice_end_at"), "notice_end_at"
    )
    resident = get_resident(residentId)
    if resident.get("status") != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE,
            "Resident %s is not ACTIVE" % residentId,
        )
    resident["status"] = "DEACTIVATING"
    resident["notice_end_at"] = iso(notice_end_at)
    touch(resident)
    append_status_event(resident["id"], "ACTIVE", "DEACTIVATING")

    unit = db.units.get(resident.get("unit_id"))
    if unit is not None:
        if unit.get("occupancy_status") == "OCCUPIED":
            unit["occupancy_status"] = "NOTICE"
        unit["_notice_end_at"] = iso(notice_end_at)
        touch(unit)

    revoke_live_credentials(resident["id"])
    for guest_pass in db.guest_passes.values():
        if (
            guest_pass.get("host_resident_id") == resident["id"]
            and guest_pass.get("status") == "ACTIVE"
        ):
            guest_pass["status"] = "REVOKED"
            touch(guest_pass)
            # PRD 3.6: a pass revoked by its host's move-out is withdrawn along
            # with the GUEST credential it created, so no live row outlives it.
            link = db.access_credentials.get(guest_pass.get("_credential_id"))
            if link is not None and link.get("status") in ("ISSUED", "ACTIVE"):
                link["status"] = "REVOKED"
                touch(link)
    refresh_portal_status(resident)
    # PRD 3.5: "The resident does not reach its terminal state at that moment."
    # The response reports the hop this operation performed (ACTIVE ->
    # DEACTIVATING); the bubble-up that follows from the emptied credential
    # scope is a consequence of the cascade and lands in storage, so a
    # subsequent read observes REVOKED.
    snapshot = serialize(resident)
    bubble_resident_to_revoked(resident)
    return success(snapshot, "object", 200)


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------
@require_roles("PlatformAdmin", "PropertyManager")
def list_status_events(caller):
    rows = list(db.resident_status_events.values())
    resident_id = request.args.get("resident_id")
    if resident_id:
        rows = [row for row in rows if row.get("resident_id") == resident_id]
    window, pagination = paged(rows)
    return success([serialize(row) for row in window], "array", 200, pagination)


@require_roles("PlatformAdmin", "PropertyManager")
def list_credentials(caller):
    rows = list(db.access_credentials.values())
    unit_id = request.args.get("unit_id")
    subject_resident_id = request.args.get("subject_resident_id")
    if unit_id:
        rows = [row for row in rows if row.get("unit_id") == unit_id]
    if subject_resident_id:
        rows = [
            row for row in rows if row.get("subject_resident_id") == subject_resident_id
        ]
    window, pagination = paged(rows)
    return success([serialize(row) for row in window], "array", 200, pagination)


API_ROUTES = [
    ("POST", "/residents", create_resident),
    ("GET", "/residents", list_residents),
    ("POST", "/residents/<residentId>/onboard", onboard_resident),
    ("POST", "/residents/<residentId>/deactivate", deactivate_resident),
    ("GET", "/resident-status-events", list_status_events),
    ("GET", "/access-credentials", list_credentials),
]