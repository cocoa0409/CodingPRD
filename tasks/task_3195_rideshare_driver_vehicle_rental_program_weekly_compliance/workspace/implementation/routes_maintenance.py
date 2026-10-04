"""Maintenance event endpoints, including loaner cover."""

from flask import Blueprint, request

import db
import services as svc
from db import stamp_created as DB_STAMP
from errors import (E_AGREEMENT_FROZEN, E_INVALID_REQUEST, E_INVALID_STATE,
                    E_LOANER_UNAVAILABLE, E_REFERENCED_ENTITY_NOT_FOUND, raise_error)
from middleware import check_schema, is_int
from middleware import body as get_body
from response import ok, ok_list
from services import (all_of, by_created, check_recovery_quiet_period, check_vehicle_version,
                      damage_settlement_split, get_agreement, get_event, get_vehicle,
                      open_week_of, paginate, round_half_up)

bp = Blueprint("maintenance", __name__)

EVENT_TYPES = ("SCHEDULED_SERVICE", "UNSCHEDULED_REPAIR", "DAMAGE_REPAIR")
EVENT_STATUSES = ("REPORTED", "IN_PROGRESS", "LOANER_ISSUED", "COMPLETED")


@bp.post("/program/maintenance-events")
def report_event():
    payload = get_body()
    check_schema(payload, "POST", "/program/maintenance-events")
    agreement_id = payload["agreement_id"]
    vehicle_id = payload["vehicle_id"]
    if agreement_id not in db.AGREEMENTS:
        raise_error(E_REFERENCED_ENTITY_NOT_FOUND, "agreement_id does not name an agreement.")
    if vehicle_id not in db.VEHICLES:
        raise_error(E_REFERENCED_ENTITY_NOT_FOUND, "vehicle_id does not name a vehicle.")
    agreement = db.AGREEMENTS[agreement_id]
    vehicle = db.VEHICLES[vehicle_id]

    event_type = payload["event_type"]
    if event_type not in EVENT_TYPES:
        raise_error(E_INVALID_REQUEST, "event_type is not recognised.")
    odometer = payload["odometer_at_service"]
    if not is_int(odometer) or odometer < 0:
        raise_error(E_INVALID_REQUEST, "odometer_at_service must be a non-negative integer.")
    downtime = payload.get("downtime_hours", 0)
    if not is_int(downtime) or downtime < 0:
        raise_error(E_INVALID_REQUEST, "downtime_hours must be a non-negative integer.")
    damage = payload.get("damage_liability_cents", 0)
    if not is_int(damage) or damage < 0:
        raise_error(E_INVALID_REQUEST, "damage_liability_cents must be a non-negative integer.")

    # guard 8 (posture freeze) is evaluated before guard 21 (quiet period)
    if agreement["compliance_posture"] == "FROZEN":
        raise_error(E_AGREEMENT_FROZEN, "The agreement's compliance posture is FROZEN.")
    check_recovery_quiet_period(vehicle)

    expected = payload.get("expected_vehicle_version")
    check_vehicle_version(vehicle, expected)

    if odometer > vehicle["odometer_miles"]:
        vehicle["odometer_miles"] = odometer

    row = {
        "id": db.new_id(),
        "agreement_id": agreement_id,
        "vehicle_id": vehicle_id,
        "event_type": event_type,
        "odometer_at_service": odometer,
        "downtime_hours": downtime,
        "loaner_vehicle_id": None,
        "loaner_deadline": None,
        "event_status": "REPORTED",
        "damage_liability_cents": damage,
        "maintenance_allowance_applied_miles": 0,
        "earnings_interruption_hours": 0,
        "_open_week_id": (open_week_of(agreement_id) or {}).get("id"),
        "operator_id": request.headers.get("X-User-ID"),
    }
    DB_STAMP(row)
    db.MAINTENANCE_EVENTS[row["id"]] = row

    vehicle["vehicle_status"] = "MAINTENANCE"
    vehicle["assigned_driver_id"] = None
    db.touch(vehicle)
    return ok(svc.event_out(row), 201)


@bp.get("/program/maintenance-events")
def list_events():
    rows = by_created(db.MAINTENANCE_EVENTS.values())
    for key in ("agreement_id", "vehicle_id", "loaner_vehicle_id", "event_status",
                "event_type"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if str(r[key]) == value]
    page, limit, offset, total = paginate(rows)
    return ok_list([svc.event_out(r) for r in page], limit, offset, total)


@bp.get("/program/maintenance-events/<event_id>")
def get_one_event(event_id):
    return ok(svc.event_out(get_event(event_id)))


@bp.post("/program/maintenance-events/<event_id>/start")
def start_event(event_id):
    event = get_event(event_id)
    if event["event_status"] != "REPORTED":
        raise_error(E_INVALID_STATE, "Only a REPORTED event may be started.")
    vehicle = get_vehicle(event["vehicle_id"])
    if vehicle["vehicle_status"] != "MAINTENANCE":
        raise_error(E_INVALID_STATE, "The unit is not in MAINTENANCE.")
    event["event_status"] = "IN_PROGRESS"
    db.touch(event)
    return ok(svc.event_out(event))


@bp.post("/program/maintenance-events/<event_id>/issue-loaner")
def issue_loaner(event_id):
    event = get_event(event_id)
    agreement = get_agreement(event["agreement_id"])
    if event["event_status"] != "IN_PROGRESS":
        raise_error(E_INVALID_STATE, "A loaner is only issuable from IN_PROGRESS.")
    if event["downtime_hours"] <= 24:
        raise_error(E_INVALID_STATE, "The service window is not long enough for a loaner.")
    if agreement["compliance_posture"] == "FROZEN":
        raise_error(E_AGREEMENT_FROZEN, "The agreement's compliance posture is FROZEN.")

    assigned = get_vehicle(event["vehicle_id"])
    pool = [v for v in db.VEHICLES.values()
            if v["region_code"] == assigned["region_code"]
            and v["vehicle_class"] == assigned["vehicle_class"]
            and v["vehicle_status"] == "AVAILABLE"
            and v["id"] != event["vehicle_id"]]
    if not pool:
        raise_error(E_LOANER_UNAVAILABLE,
                    "No conforming loaner unit is available in the region and class.")
    pool.sort(key=lambda v: (v["odometer_miles"], v["created_at"]))
    loaner = pool[0]

    event["loaner_vehicle_id"] = loaner["id"]
    event["loaner_deadline"] = db.now() + db.hours(event["downtime_hours"])
    event["event_status"] = "LOANER_ISSUED"
    event["earnings_interruption_hours"] = 0
    db.touch(event)

    loaner["vehicle_status"] = "ASSIGNED"
    loaner["assigned_driver_id"] = agreement["driver_id"]
    db.touch(loaner)
    return ok(svc.event_out(event))


@bp.post("/program/maintenance-events/<event_id>/complete")
def complete_event(event_id):
    event = get_event(event_id)
    agreement = get_agreement(event["agreement_id"])
    vehicle = get_vehicle(event["vehicle_id"])
    status = event["event_status"]
    downtime = event["downtime_hours"]

    if status == "REPORTED":
        if downtime != 0:
            raise_error(E_INVALID_STATE,
                        "A zero-downtime event may only be completed from REPORTED.")
        event["maintenance_allowance_applied_miles"] = 0
        event["earnings_interruption_hours"] = 0
    elif status == "IN_PROGRESS":
        if downtime <= 0 or downtime > 24:
            raise_error(E_INVALID_STATE,
                        "An event with this downtime cannot be completed from IN_PROGRESS.")
        event["earnings_interruption_hours"] = downtime
        event["maintenance_allowance_applied_miles"] = min(
            downtime, agreement["maintenance_allowance_miles"])
    elif status == "LOANER_ISSUED":
        if not event["loaner_vehicle_id"]:
            raise_error(E_INVALID_STATE, "No loaner is outstanding on this event.")
        loaner = db.VEHICLES.get(event["loaner_vehicle_id"])
        if loaner is not None:
            loaner["vehicle_status"] = "AVAILABLE"
            loaner["assigned_driver_id"] = None
            loaner["returned_to_available_at"] = db.now()
            db.touch(loaner)
        vehicle["vehicle_status"] = "ASSIGNED"
        vehicle["assigned_driver_id"] = agreement["driver_id"]
        db.touch(vehicle)
        event["earnings_interruption_hours"] = 0
        event["maintenance_allowance_applied_miles"] = min(
            round_half_up(downtime / 8), agreement["maintenance_allowance_miles"])
    else:
        raise_error(E_INVALID_STATE, "The event is already COMPLETED.")

    event["event_status"] = "COMPLETED"
    db.touch(event)

    # every completion path returns the unit under repair to ASSIGNED
    vehicle["vehicle_status"] = "ASSIGNED"
    vehicle["assigned_driver_id"] = agreement["driver_id"]
    db.touch(vehicle)

    damage_settlement_split(agreement)
    week = open_week_of(agreement["id"])
    if week is not None:
        week["amount_due_cents"] = (week["base_charge_cents"] + week["insurance_charge_cents"]
                                    + week["mileage_overage_cents"] + week["damage_charge_cents"]
                                    - week["platform_credit_cents"])
        db.touch(week)
    return ok(svc.event_out(event))