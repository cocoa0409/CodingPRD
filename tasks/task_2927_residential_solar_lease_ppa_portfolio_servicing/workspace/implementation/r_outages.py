"""Monitoring alarms: recording, triage and false positives (PRD §3.5)."""
from flask import Blueprint

import calc
from core import (
    ApiError, clock, fmt_instant, parse_instant, sorted_rows, stamp_new, store,
    touch,
)
from guards import (
    homeowner_agreement_ids, homeowner_scope, lookup, require_child_write_allowed,
    require_not_decommissioned,
)
from serialize import outage_view
from web import (
    apply_filters, authenticate, created, filters, ok, ok_list, paginate,
    pagination, validate_body,
)

bp = Blueprint("outage_routes", __name__)

OUTAGE_TYPES = ("INVERTER_FAULT", "COMMS_LOSS", "PRODUCTION_ANOMALY")
OUTAGE_STATUSES = ("OPEN", "TRIAGED", "DISPATCHED", "RESOLVED", "FALSE_POSITIVE")
SEVERITIES = ("LOW", "MEDIUM", "HIGH")

OUTAGE_SPECS = [
    {"name": "agreement_id", "kind": "id", "required": True},
    {"name": "inverter_serial", "kind": "str", "required": True, "minlen": 1,
     "maxlen": 40, "nonblank": True},
    {"name": "outage_type", "kind": "enum", "required": True, "values": OUTAGE_TYPES},
    {"name": "detected_at", "kind": "instant", "required": True},
]


@bp.post("/servicing/outage-events")
def create_outage():
    authenticate(("FieldOpsCoordinator", "PortfolioAdmin"))
    body = validate_body(OUTAGE_SPECS)
    ag = lookup("agreements", body["agreement_id"])
    require_child_write_allowed(ag)
    require_not_decommissioned(ag)
    detected = parse_instant(body["detected_at"])
    now = clock.now()
    if detected > now:
        raise ApiError("ERR_DETECTED_AT_IN_FUTURE",
                       "detected_at is after the current logical clock instant.")
    minutes = calc.elapsed_minutes(detected, now)
    if minutes < 0:
        minutes = 0
    event = {
        "agreement_id": ag["id"],
        "inverter_serial": body["inverter_serial"],
        "outage_type": body["outage_type"],
        "detected_at": fmt_instant(detected),
        "resolved_at": None,
        "severity": calc.grade_severity(minutes),
        "downtime_minutes": minutes,
        "excused": False,
        "status": "OPEN",
    }
    stamp_new(event)
    store.outage_events[event["id"]] = event
    calc.derive_monitoring(ag)
    touch(ag)
    return created(outage_view(event))


@bp.get("/servicing/outage-events/<outage_event_id>")
def get_outage(outage_event_id):
    user_id, role = authenticate(("FieldOpsCoordinator", "PortfolioAdmin",
                                  "ServicingAgent", "Homeowner"))
    event = lookup("outage_events", outage_event_id)
    homeowner_scope(role, user_id, store.agreements.get(event["agreement_id"]))
    return ok(outage_view(event))


@bp.get("/servicing/outage-events")
def list_outages():
    user_id, role = authenticate(("FieldOpsCoordinator", "PortfolioAdmin",
                                  "ServicingAgent", "Homeowner"))
    limit, offset = pagination()
    flt = filters([
        ("agreement_id", "str", None),
        ("status", "enum", OUTAGE_STATUSES),
        ("outage_type", "enum", OUTAGE_TYPES),
        ("severity", "enum", SEVERITIES),
        ("excused", "bool", None),
    ])
    rows = list(store.outage_events.values())
    if role == "Homeowner":
        if "agreement_id" in flt:
            homeowner_scope(role, user_id, store.agreements.get(flt["agreement_id"]))
        owned = homeowner_agreement_ids(user_id)
        rows = [r for r in rows if r["agreement_id"] in owned]
    for r in rows:
        outage_view(r)
    rows = apply_filters(sorted_rows(rows), flt)
    page, total = paginate(rows, limit, offset)
    return ok_list([outage_view(r) for r in page], limit, offset, total)


@bp.post("/servicing/outage-events/<outage_event_id>/triage")
def triage_outage(outage_event_id):
    authenticate(("FieldOpsCoordinator",))
    validate_body([])
    event = lookup("outage_events", outage_event_id)
    ag = store.agreements[event["agreement_id"]]
    if event["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an OPEN alarm may be triaged.")
    minutes = calc.elapsed_minutes(parse_instant(event["detected_at"]), clock.now())
    if minutes < 0:
        minutes = 0
    event["downtime_minutes"] = minutes
    event["severity"] = calc.grade_severity(minutes)
    event["status"] = "TRIAGED"
    touch(event)
    calc.derive_monitoring(ag)
    return ok(outage_view(event))


@bp.post("/servicing/outage-events/<outage_event_id>/mark-false-positive")
def mark_false_positive(outage_event_id):
    authenticate(("FieldOpsCoordinator", "PortfolioAdmin"))
    validate_body([])
    event = lookup("outage_events", outage_event_id)
    ag = store.agreements[event["agreement_id"]]
    if event["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an OPEN alarm may be closed as a false positive.")
    for roll in store.truck_rolls.values():
        if roll["outage_event_id"] == event["id"]:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A truck roll already exists for this alarm.")
    event["resolved_at"] = fmt_instant(clock.now())
    event["downtime_minutes"] = 0
    event["excused"] = False
    event["status"] = "FALSE_POSITIVE"
    touch(event)
    calc.derive_monitoring(ag)
    calc.derive_excused_downtime(ag)
    touch(ag)
    return ok(outage_view(event))
