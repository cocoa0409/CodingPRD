"""Shared lookups, budget roll-up, credential cascade and clock advance."""

from datetime import timedelta

from calculations import (
    ESTIMATED_JOB_RESERVE_CENTS,
    MAX_VERIFY_ATTEMPTS,
    OCCUPIED_SETPOINT_C,
    _round,
    clamp,
    installation_labor_hours,
)
from db import add_minutes, clock, iso, new_record, parse_instant, touch
from db import db
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_BUDGET_EXCEEDED,
    ERR_BUILDING_NOT_FOUND,
    ERR_DEVICE_ALERT_NOT_FOUND,
    ERR_DEVICE_NOT_FOUND,
    ERR_GUEST_PASS_NOT_FOUND,
    ERR_INSTALLATION_JOB_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_MAINTENANCE_VISIT_NOT_FOUND,
    ERR_PROPERTY_NOT_FOUND,
    ERR_RESIDENT_NOT_FOUND,
    ERR_TOUR_SESSION_NOT_FOUND,
    ERR_UNIT_NOT_FOUND,
    ERR_WORK_ORDER_NOT_FOUND,
    ApiError,
)
from records import new_record as _new_record  # noqa: F401  (re-export convenience)

LIVE_CREDENTIAL_STATES = ("ISSUED", "ACTIVE")

# ---------------------------------------------------------------------------
# Existence lookups (priority 4, resolved left-to-right)
# ---------------------------------------------------------------------------
def get_property(property_id):
    row = db.properties.get(property_id)
    if row is None:
        raise ApiError(ERR_PROPERTY_NOT_FOUND, "Property %s does not exist" % property_id)
    return row


def get_building(building_id):
    row = db.buildings.get(building_id)
    if row is None:
        raise ApiError(ERR_BUILDING_NOT_FOUND, "Building %s does not exist" % building_id)
    return row


def get_unit(unit_id):
    row = db.units.get(unit_id)
    if row is None:
        raise ApiError(ERR_UNIT_NOT_FOUND, "Unit %s does not exist" % unit_id)
    return row


def get_device(device_id):
    row = db.devices.get(device_id)
    if row is None:
        raise ApiError(ERR_DEVICE_NOT_FOUND, "Device %s does not exist" % device_id)
    return row


def get_resident(resident_id):
    row = db.residents.get(resident_id)
    if row is None:
        raise ApiError(ERR_RESIDENT_NOT_FOUND, "Resident %s does not exist" % resident_id)
    return row


def get_guest_pass(guest_pass_id):
    row = db.guest_passes.get(guest_pass_id)
    if row is None:
        raise ApiError(
            ERR_GUEST_PASS_NOT_FOUND, "Guest pass %s does not exist" % guest_pass_id
        )
    return row


def get_tour_session(tour_session_id):
    row = db.tour_sessions.get(tour_session_id)
    if row is None:
        raise ApiError(
            ERR_TOUR_SESSION_NOT_FOUND,
            "Tour session %s does not exist" % tour_session_id,
        )
    return row


def get_maintenance_visit(visit_id):
    row = db.maintenance_visits.get(visit_id)
    if row is None:
        raise ApiError(
            ERR_MAINTENANCE_VISIT_NOT_FOUND,
            "Maintenance visit %s does not exist" % visit_id,
        )
    return row


def get_installation_job(job_id):
    row = db.installation_jobs.get(job_id)
    if row is None:
        raise ApiError(
            ERR_INSTALLATION_JOB_NOT_FOUND,
            "Installation job %s does not exist" % job_id,
        )
    return row


def get_device_alert(alert_id):
    row = db.device_alerts.get(alert_id)
    if row is None:
        raise ApiError(
            ERR_DEVICE_ALERT_NOT_FOUND, "Device alert %s does not exist" % alert_id
        )
    return row


def get_work_order(work_order_id):
    row = db.work_orders.get(work_order_id)
    if row is None:
        raise ApiError(
            ERR_WORK_ORDER_NOT_FOUND, "Work order %s does not exist" % work_order_id
        )
    return row


# ---------------------------------------------------------------------------
# Property budget (PRD 2.8 / 3.7)
# ---------------------------------------------------------------------------
def committed_from_visits(property_id):
    total = 0
    for visit in db.maintenance_visits.values():
        if visit.get("_property_id") != property_id:
            continue
        if visit.get("status") in ("NOTICE_CERTIFIED", "COMPLETED"):
            total += int(visit.get("accrued_cost_cents") or 0)
    return total


def committed_from_jobs(property_id):
    total = 0
    for job in db.installation_jobs.values():
        if job.get("property_id") != property_id:
            continue
        if job.get("status") != "ABORTED":
            total += int(job.get("_reserve_cents") or 0)
    return total


def recompute_budget(property_id):
    prop = db.properties.get(property_id)
    if prop is None:
        return 0
    total = committed_from_visits(property_id) + committed_from_jobs(property_id)
    prop["budget_committed_cents"] = total
    touch(prop)
    return total


def ensure_budget(property_id, prospective_total):
    prop = db.properties.get(property_id)
    if prop is None:
        return
    if prospective_total > int(prop.get("temp_budget_cents_per_day") or 0):
        raise ApiError(
            ERR_BUDGET_EXCEEDED,
            "Committing %d cents would exceed the property daily allowance"
            % prospective_total,
        )


def unit_residents(unit_id):
    return [r for r in db.residents.values() if r.get("unit_id") == unit_id]


def non_revoked_residents(unit_id):
    return [r for r in unit_residents(unit_id) if r.get("status") != "REVOKED"]


def active_residents(unit_id):
    return [r for r in unit_residents(unit_id) if r.get("status") == "ACTIVE"]


# ---------------------------------------------------------------------------
# Credentials (PRD 2.7)
# ---------------------------------------------------------------------------
def credentials_for_resident(resident_id):
    return [
        c
        for c in db.access_credentials.values()
        if c.get("subject_resident_id") == resident_id
        or (c.get("subject_resident_id") is None
            and c.get("_host_resident_id") == resident_id)
    ]


def credentials_for_unit(unit_id):
    return [c for c in db.access_credentials.values() if c.get("unit_id") == unit_id]


def live_credentials_for_resident(resident_id):
    return [
        c
        for c in credentials_for_resident(resident_id)
        if c.get("status") in LIVE_CREDENTIAL_STATES
    ]


def credential_conservation(rows):
    """issued_total == active + expired + revoked (exact integer)."""
    counts = {"ISSUED": 0, "ACTIVE": 0, "EXPIRED": 0, "REVOKED": 0}
    for row in rows:
        status = row.get("status")
        if status in counts:
            counts[status] += 1
    return {
        "issued_total": len(rows),
        "active": counts["ACTIVE"],
        "expired": counts["EXPIRED"],
        "revoked": counts["REVOKED"],
        "issued": counts["ISSUED"],
    }


def refresh_portal_status(resident):
    live = live_credentials_for_resident(resident["id"])
    if not live:
        if any(
            c.get("status") == "REVOKED"
            for c in credentials_for_resident(resident["id"])
        ):
            resident["portal_credential_status"] = "REVOKED"
        else:
            resident["portal_credential_status"] = "NOT_ISSUED"
    else:
        resident["portal_credential_status"] = "ACTIVE"
    return resident["portal_credential_status"]


def append_status_event(resident_id, from_status, to_status):
    event = new_record(
        {
            "resident_id": resident_id,
            "from_status": from_status,
            "to_status": to_status,
            "recorded_at": iso(clock.now),
        },
        common=False,
    )
    db.resident_status_events[event["id"]] = event
    return event


def bubble_resident_to_revoked(resident):
    """DEACTIVATING -> REVOKED once no live credential remains (PRD 2.7).

    The only condition PRD 3.5 names for this hop is credential liveness: "It
    rests in `DEACTIVATING` until no credential in its scope remains in
    `ISSUED` or `ACTIVE`, at which point it moves to `REVOKED` — its only
    terminal state." Because deactivation revokes the live credentials in the
    same operation, "the condition is generally satisfied in the same breath",
    so the terminal hop lands with the cascade rather than waiting on the
    logical clock. The notice-end tick of PRD 3.5 (NOTICE -> NOTICE_ENDED) is a
    separate transition that re-runs this bubble-up for a resident the clock
    caught mid-notice; it is not a precondition of the hop itself, and a
    resident still holding a live credential is held back regardless of the
    clock.
    """
    if resident.get("status") != "DEACTIVATING":
        return False
    if live_credentials_for_resident(resident["id"]):
        return False
    resident["status"] = "REVOKED"
    resident["portal_credential_status"] = "REVOKED"
    touch(resident)
    append_status_event(resident["id"], "DEACTIVATING", "REVOKED")
    return True


def revoke_live_credentials(resident_id):
    revoked = []
    for cred in credentials_for_resident(resident_id):
        if cred.get("status") in LIVE_CREDENTIAL_STATES:
            cred["status"] = "REVOKED"
            touch(cred)
            revoked.append(cred)
    return revoked


def issue_credential(unit_id, subject_resident_id, credential_type, status,
                     valid_from=None, valid_until=None):
    record = new_record(
        {
            "unit_id": unit_id,
            "subject_resident_id": subject_resident_id,
            "credential_type": credential_type,
            "status": status,
            "valid_from": valid_from,
            "valid_until": valid_until,
        }
    )
    db.access_credentials[record["id"]] = record
    return record


def covering_credential(unit_id, moment, kinds=("GUEST", "TOUR")):
    """An ACTIVE credential of one of `kinds` whose window covers `moment`."""
    for cred in credentials_for_unit(unit_id):
        if cred.get("credential_type") not in kinds:
            continue
        if cred.get("status") != "ACTIVE":
            continue
        start = parse_instant(cred.get("valid_from"), "valid_from")
        end = parse_instant(cred.get("valid_until"), "valid_until")
        if start <= moment <= end:
            return cred
    return None


# ---------------------------------------------------------------------------
# Unit occupancy / HVAC (PRD 3.1, 3.4)
# ---------------------------------------------------------------------------
def set_unit_occupied(unit):
    unit["occupancy_status"] = "OCCUPIED"
    unit["hvac_mode"] = "OCCUPIED"
    unit["target_setpoint_c"] = _round(OCCUPIED_SETPOINT_C, 1)
    unit["unauthorized_entry_detected"] = False
    touch(unit)


def set_unit_vacant_auto(unit):
    unit["hvac_mode"] = "VACANT_AUTO"
    touch(unit)


# ---------------------------------------------------------------------------
# Schedule exclusivity (PRD 2.6)
# ---------------------------------------------------------------------------
def maintenance_occupations(unit_id, exclude_id=None):
    spans = []
    for visit in db.maintenance_visits.values():
        if visit.get("unit_id") != unit_id or visit.get("id") == exclude_id:
            continue
        if visit.get("status") not in ("REQUESTED", "NOTICE_CERTIFIED"):
            continue
        spans.append(
            (
                parse_instant(visit.get("start_at"), "start_at"),
                parse_instant(visit.get("end_at"), "end_at"),
            )
        )
    return spans


def tour_occupations(unit_id):
    spans = []
    for session in db.tour_sessions.values():
        if session.get("unit_id") != unit_id:
            continue
        if session.get("status") not in ("REQUESTED", "VERIFIED", "ACTIVE"):
            continue
        start = parse_instant(session.get("requested_start_at"), "requested_start_at")
        end = add_minutes(start, int(session.get("duration_minutes") or 60))
        spans.append((start, end))
    return spans


def _overlaps(a_start, a_end, spans):
    for b_start, b_end in spans:
        if a_start < b_end and b_start < a_end:
            return True
    return False


def has_schedule_conflict(unit_id, start, end):
    spans = maintenance_occupations(unit_id) + tour_occupations(unit_id)
    return _overlaps(start, end, spans)


def has_install_conflict(unit_id, start, end, buffer_minutes=30):
    if unit_id is None:
        return False
    buffered_start = start - timedelta(minutes=buffer_minutes)
    buffered_end = end + timedelta(minutes=buffer_minutes)
    spans = maintenance_occupations(unit_id) + tour_occupations(unit_id)
    return _overlaps(buffered_start, buffered_end, spans)


# ---------------------------------------------------------------------------
# Logical clock advance (PRD 3.10)
# ---------------------------------------------------------------------------
def advance_clock(moment):
    clock.advance_to(moment)
    _expire_credentials()
    _expire_guest_passes()
    _advance_units_on_notice()
    _advance_tour_sessions()
    _cancel_stale_installations()
    for prop_id in list(db.properties.keys()):
        recompute_budget(prop_id)


def _expire_credentials():
    for cred in list(db.access_credentials.values()):
        if cred.get("status") != "ACTIVE":
            continue
        until = cred.get("valid_until")
        if until is None:
            continue
        if clock.now >= parse_instant(until, "valid_until"):
            cred["status"] = "EXPIRED"
            touch(cred)


def _expire_guest_passes():
    for guest_pass in list(db.guest_passes.values()):
        if guest_pass.get("status") != "ACTIVE":
            continue
        if clock.now >= parse_instant(guest_pass.get("end_at"), "end_at"):
            guest_pass["status"] = "EXPIRED"
            touch(guest_pass)


def _advance_units_on_notice():
    for unit in list(db.units.values()):
        if unit.get("occupancy_status") != "NOTICE":
            continue
        if unit.get("_notice_end_at") is None:
            continue
        if clock.now < parse_instant(unit["_notice_end_at"], "notice_end_at"):
            continue
        unit["occupancy_status"] = "NOTICE_ENDED"
        unit["hvac_mode"] = "VACANT_AUTO"
        touch(unit)
        for resident in unit_residents(unit["id"]):
            if resident.get("status") == "DEACTIVATING":
                bubble_resident_to_revoked(resident)


def _advance_tour_sessions():
    for session in list(db.tour_sessions.values()):
        status = session.get("status")
        if status not in ("VERIFIED", "ACTIVE"):
            continue
        cred = session.get("_credential_id")
        credential = db.access_credentials.get(cred) if cred else None
        if credential is None:
            continue
        start = parse_instant(credential.get("valid_from"), "valid_from")
        end = parse_instant(credential.get("valid_until"), "valid_until")
        if status == "VERIFIED" and clock.now >= start:
            session["status"] = "ACTIVE"
            touch(session)
        if session.get("status") == "ACTIVE" and clock.now >= end:
            session["status"] = "COMPLETED"
            touch(session)
            if credential.get("status") != "REVOKED":
                credential["status"] = "EXPIRED"
                touch(credential)


def _cancel_stale_installations():
    for job in list(db.installation_jobs.values()):
        if job.get("status") != "SCHEDULED":
            continue
        created = parse_instant(job.get("created_at"), "created_at")
        if clock.now >= created + timedelta(hours=24):
            job["status"] = "ABORTED"
            job["_abort_reason"] = "SCHEDULE_EXPIRED"
            touch(job)
            recompute_budget(job.get("property_id"))