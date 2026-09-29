"""Truck rolls: dispatch, close-out, cost allocation, cancellation (PRD §3.5, §3.6)."""
from flask import Blueprint

import calc
from core import (
    ApiError, clock, fmt_instant, invalid, parse_instant, sorted_rows, stamp_new,
    store, touch,
)
from guards import lookup
from serialize import outage_view, truck_roll_view
from web import (
    apply_filters, authenticate, created, filters, ok, ok_list, paginate,
    pagination, validate_body,
)

bp = Blueprint("truck_roll_routes", __name__)

DISPOSITIONS = ("SERVICE_COMPLETE", "NO_ACCESS")
ROOT_CAUSES = ("INVERTER_FAULT", "MODULE_DEFECT", "STRING_FAULT", "COMMS_ONLY",
               "HOMEOWNER_CAUSED")
ROLL_STATUSES = ("SCHEDULED", "COMPLETED", "NO_ACCESS", "CANCELLED")
BILLABLE_TO = ("PENDING_MANUFACTURER", "SUNRUN_OM", "WARRANTY", "HOMEOWNER")

ROLL_SPECS = [
    {"name": "outage_event_id", "kind": "id", "required": True},
    {"name": "technician_code", "kind": "str", "required": True, "minlen": 1,
     "maxlen": 24, "nonblank": True},
    {"name": "scheduled_window_start", "kind": "instant", "required": True},
    {"name": "scheduled_window_end", "kind": "instant", "required": True},
    {"name": "expected_outage_event_version", "kind": "int", "required": True},
]

COMPLETE_SPECS = [
    {"name": "disposition", "kind": "enum", "required": True, "values": DISPOSITIONS},
    {"name": "root_cause", "kind": "enum", "values": ROOT_CAUSES},
]


@bp.post("/servicing/truck-rolls")
def create_truck_roll():
    user_id, role = authenticate(("FieldOpsCoordinator",))
    body = validate_body(ROLL_SPECS)
    start = parse_instant(body["scheduled_window_start"])
    end = parse_instant(body["scheduled_window_end"])
    if end <= start:
        raise invalid("scheduled_window_end must be strictly after "
                      "scheduled_window_start.")
    event = lookup("outage_events", body["outage_event_id"])
    ag = store.agreements[event["agreement_id"]]
    if event["status"] != "TRIAGED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a TRIAGED alarm may be dispatched.")
    # rung 9 — optimistic concurrency on the parent outage event
    if body["expected_outage_event_version"] != event["version"]:
        raise ApiError("ERR_STALE_OUTAGE_EVENT_VERSION",
                       "expected_outage_event_version does not match the outage "
                       "event's current version.")
    # rung 13 — half-open technician window overlap, no buffer
    for other in store.truck_rolls.values():
        if other["status"] != "SCHEDULED":
            continue
        if other["technician_code"] != body["technician_code"]:
            continue
        o_start = parse_instant(other["scheduled_window_start"])
        o_end = parse_instant(other["scheduled_window_end"])
        if start < o_end and o_start < end:
            raise ApiError("ERR_TECHNICIAN_WINDOW_CONFLICT",
                           "That technician already has an overlapping window.")

    roll = {
        "outage_event_id": event["id"],
        "agreement_id": event["agreement_id"],
        "technician_code": body["technician_code"],
        "scheduled_window_start": fmt_instant(start),
        "scheduled_window_end": fmt_instant(end),
        "disposition": None,
        "root_cause": None,
        "billable_to": None,
        "labor_cost_cents": 0,
        "completed_at": None,
        "dispatched_by_user_id": user_id,
        "diagnosed_by_user_id": None,
        "status": "SCHEDULED",
    }
    stamp_new(roll)
    store.truck_rolls[roll["id"]] = roll

    event["status"] = "DISPATCHED"
    touch(event)
    calc.derive_monitoring(ag)
    touch(ag)
    return created(truck_roll_view(roll))


@bp.get("/servicing/truck-rolls/<truck_roll_id>")
def get_truck_roll(truck_roll_id):
    authenticate(("FieldOpsCoordinator", "PortfolioAdmin", "ServicingAgent"))
    return ok(truck_roll_view(lookup("truck_rolls", truck_roll_id)))


@bp.get("/servicing/truck-rolls")
def list_truck_rolls():
    authenticate(("FieldOpsCoordinator", "PortfolioAdmin", "ServicingAgent"))
    limit, offset = pagination()
    flt = filters([
        ("outage_event_id", "str", None),
        ("agreement_id", "str", None),
        ("technician_code", "str", None),
        ("status", "enum", ROLL_STATUSES),
        ("billable_to", "enum", BILLABLE_TO),
        ("root_cause", "enum", ROOT_CAUSES),
    ])
    rows = apply_filters(sorted_rows(list(store.truck_rolls.values())), flt)
    page, total = paginate(rows, limit, offset)
    return ok_list([truck_roll_view(r) for r in page], limit, offset, total)


@bp.post("/servicing/truck-rolls/<truck_roll_id>/complete")
def complete_truck_roll(truck_roll_id):
    user_id, role = authenticate(("FieldOpsCoordinator",))
    body = validate_body(COMPLETE_SPECS)
    roll = lookup("truck_rolls", truck_roll_id)
    # rung 7 — segregation of duties, ahead of any state check
    if roll["dispatched_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The dispatching user may not close out the same roll.")
    if roll["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SCHEDULED roll may be closed out.")
    disposition = body["disposition"]
    root_cause = body.get("root_cause")
    if disposition == "SERVICE_COMPLETE" and root_cause is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A SERVICE_COMPLETE close-out requires a root_cause.")
    if disposition == "NO_ACCESS" and root_cause is not None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A NO_ACCESS close-out may not carry a root_cause.")

    event = store.outage_events[roll["outage_event_id"]]
    ag = store.agreements[roll["agreement_id"]]
    now = clock.now()
    billable, labor, excused = calc.allocate_truck_roll(disposition, root_cause)

    roll["disposition"] = disposition
    roll["root_cause"] = root_cause
    roll["billable_to"] = billable
    roll["labor_cost_cents"] = labor
    roll["completed_at"] = fmt_instant(now)

    if disposition == "SERVICE_COMPLETE":
        roll["diagnosed_by_user_id"] = user_id
        roll["status"] = "COMPLETED"
        minutes = calc.elapsed_minutes(parse_instant(event["detected_at"]), now)
        if minutes < 0:
            minutes = 0
        event["resolved_at"] = fmt_instant(now)
        event["downtime_minutes"] = minutes
        event["severity"] = calc.grade_severity(minutes)
        event["excused"] = excused
        event["status"] = "RESOLVED"
    else:
        roll["status"] = "NO_ACCESS"
        event["status"] = "TRIAGED"
    touch(roll)
    touch(event)
    calc.derive_monitoring(ag)
    calc.derive_excused_downtime(ag)
    touch(ag)
    return ok(truck_roll_view(roll))


@bp.post("/servicing/truck-rolls/<truck_roll_id>/cancel")
def cancel_truck_roll(truck_roll_id):
    authenticate(("FieldOpsCoordinator", "PortfolioAdmin"))
    validate_body([])
    roll = lookup("truck_rolls", truck_roll_id)
    if roll["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SCHEDULED roll may be cancelled.")
    event = store.outage_events[roll["outage_event_id"]]
    ag = store.agreements[roll["agreement_id"]]
    roll["status"] = "CANCELLED"
    roll["billable_to"] = None
    roll["labor_cost_cents"] = 0
    touch(roll)
    event["status"] = "TRIAGED"
    touch(event)
    calc.derive_monitoring(ag)
    touch(ag)
    outage_view(event)
    return ok(truck_roll_view(roll))
