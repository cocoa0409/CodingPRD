"""Every read endpoint of PRD section 4. All reads are open to all seven roles."""
from flask import Blueprint

import calc
import db as D
import serializers as S
from db import (
    COMPETENCY_LEVELS,
    DOC_STATES,
    ENTRY_KINDS,
    ENTRY_STATUSES,
    EVENT_KINDS,
    EVENT_STATUSES,
    FEED_STATUSES,
    MODALITIES,
    ORDER_STATUSES,
    PATIENT_STATUSES,
    ROLES,
    SOURCE_POOLS,
    STAFF_STATUSES,
    STATION_STATUSES,
    UNIT_STATUSES,
    WATCH_STATUSES,
    db,
)
from errors import fail
from response import array_response, object_response
from services import paginate
from validation import authenticate, enum_filter, pagination, plain_filter

bp = Blueprint("reads", __name__)

ALL_ROLES = ROLES


def _fetch(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        fail(error_id)
    return row


def _listing(rows, projector, limit, offset, key=None):
    rows = sorted(rows, key=key or D.sort_key)
    page, total = paginate(rows, limit, offset)
    return array_response([projector(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
@bp.get("/observation/units")
def list_units():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", UNIT_STATUSES)
    rows = [u for u in db.units.values() if status is None or u["status"] == status]
    return _listing(rows, S.unit_json, limit, offset)


@bp.get("/observation/units/<unit_id>")
def get_unit(unit_id):
    authenticate(ALL_ROLES)
    unit = _fetch(db.units, unit_id, "ERR_UNIT_NOT_FOUND")
    return object_response(S.unit_json(unit))


@bp.get("/observation/units/<unit_id>/patients")
def list_unit_patients(unit_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", PATIENT_STATUSES)
    unit = _fetch(db.units, unit_id, "ERR_UNIT_NOT_FOUND")
    rows = [
        p for p in calc.patients_of_unit(unit) if status is None or p["status"] == status
    ]
    return _listing(rows, S.patient_json, limit, offset)


@bp.get("/observation/units/<unit_id>/staff")
def list_unit_staff(unit_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", STAFF_STATUSES)
    pool = enum_filter("source_pool", SOURCE_POOLS)
    level = enum_filter("competency_level", COMPETENCY_LEVELS)
    unit = _fetch(db.units, unit_id, "ERR_UNIT_NOT_FOUND")
    rows = []
    for s in db.staff.values():
        if s["home_unit_id"] != unit["id"]:
            continue
        if status is not None and s["status"] != status:
            continue
        if pool is not None and s["source_pool"] != pool:
            continue
        if level is not None and s["competency_level"] != level:
            continue
        rows.append(s)
    return _listing(rows, S.staff_json, limit, offset)


@bp.get("/observation/units/<unit_id>/cost-entries")
def list_unit_cost_entries(unit_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", ENTRY_STATUSES)
    kind = enum_filter("entry_kind", ENTRY_KINDS)
    unit = _fetch(db.units, unit_id, "ERR_UNIT_NOT_FOUND")
    rows = []
    for c in calc.cost_entries_of_unit(unit["id"]):
        if status is not None and c["status"] != status:
            continue
        if kind is not None and c["entry_kind"] != kind:
            continue
        rows.append(c)
    return _listing(rows, S.cost_entry_json, limit, offset)


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------
@bp.get("/observation/patients/<patient_id>")
def get_patient(patient_id):
    authenticate(ALL_ROLES)
    patient = _fetch(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    return object_response(S.patient_json(patient))


@bp.get("/observation/patients/<patient_id>/orders")
def list_patient_orders(patient_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", ORDER_STATUSES)
    modality = enum_filter("required_modality", MODALITIES)
    patient = _fetch(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    rows = []
    for o in db.orders.values():
        if o["patient_id"] != patient["id"]:
            continue
        if status is not None and o["status"] != status:
            continue
        if modality is not None and o["required_modality"] != modality:
            continue
        rows.append(o)
    return _listing(rows, S.order_json, limit, offset)


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------
@bp.get("/observation/staff")
def list_staff():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", STAFF_STATUSES)
    pool = enum_filter("source_pool", SOURCE_POOLS)
    level = enum_filter("competency_level", COMPETENCY_LEVELS)
    home_unit_id = plain_filter("home_unit_id")
    rows = []
    for s in db.staff.values():
        if status is not None and s["status"] != status:
            continue
        if pool is not None and s["source_pool"] != pool:
            continue
        if level is not None and s["competency_level"] != level:
            continue
        if home_unit_id is not None and s["home_unit_id"] != home_unit_id:
            continue
        rows.append(s)
    return _listing(rows, S.staff_json, limit, offset)


@bp.get("/observation/staff/<staff_id>")
def get_staff(staff_id):
    authenticate(ALL_ROLES)
    staff = _fetch(db.staff, staff_id, "ERR_STAFF_NOT_FOUND")
    return object_response(S.staff_json(staff))


@bp.get("/observation/staff/<staff_id>/sitter-assignments")
def list_staff_assignments(staff_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    watch_status = enum_filter("watch_status", WATCH_STATUSES)
    staff = _fetch(db.staff, staff_id, "ERR_STAFF_NOT_FOUND")
    rows = [
        a
        for a in calc.assignments_of_staff(staff["id"])
        if watch_status is None or a["watch_status"] == watch_status
    ]
    return _listing(rows, S.assignment_json, limit, offset)


@bp.get("/observation/staff/<staff_id>/monitoring-stations")
def list_staff_stations(staff_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", STATION_STATUSES)
    staff = _fetch(db.staff, staff_id, "ERR_STAFF_NOT_FOUND")
    rows = []
    for st in db.stations.values():
        if st["observer_staff_id"] != staff["id"]:
            continue
        if status is not None and st["status"] != status:
            continue
        rows.append(st)
    return _listing(rows, S.station_json, limit, offset)


# ---------------------------------------------------------------------------
# Observation orders
# ---------------------------------------------------------------------------
@bp.get("/observation/orders")
def list_orders():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", ORDER_STATUSES)
    modality = enum_filter("required_modality", MODALITIES)
    patient_id = plain_filter("patient_id")
    rows = []
    for o in db.orders.values():
        if status is not None and o["status"] != status:
            continue
        if modality is not None and o["required_modality"] != modality:
            continue
        if patient_id is not None and o["patient_id"] != patient_id:
            continue
        rows.append(o)
    return _listing(rows, S.order_json, limit, offset)


@bp.get("/observation/orders/<order_id>")
def get_order(order_id):
    authenticate(ALL_ROLES)
    order = _fetch(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
    return object_response(S.order_json(order))


@bp.get("/observation/orders/<order_id>/sitter-assignments")
def list_order_assignments(order_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    watch_status = enum_filter("watch_status", WATCH_STATUSES)
    order = _fetch(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
    rows = [
        a
        for a in calc.assignments_of_order(order["id"])
        if watch_status is None or a["watch_status"] == watch_status
    ]
    return _listing(rows, S.assignment_json, limit, offset)


@bp.get("/observation/orders/<order_id>/reassessments")
def list_order_reassessments(order_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    order = _fetch(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
    rows = [r for r in db.reassessments.values() if r["order_id"] == order["id"]]
    # PRD 3.3: a reassessment history is readable in reassessed_at order.
    return _listing(
        rows, S.reassessment_json, limit, offset,
        key=lambda r: (r["reassessed_at"], r["_seq"]),
    )


@bp.get("/observation/orders/<order_id>/video-feeds")
def list_order_feeds(order_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", FEED_STATUSES)
    order = _fetch(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
    rows = [
        f
        for f in calc.feeds_of_order(order["id"])
        if status is None or f["status"] == status
    ]
    return _listing(rows, S.feed_json, limit, offset)


@bp.get("/observation/orders/<order_id>/safety-events")
def list_order_events(order_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", EVENT_STATUSES)
    kind = enum_filter("event_kind", EVENT_KINDS)
    order = _fetch(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
    rows = []
    for e in calc.events_of_order(order["id"]):
        if status is not None and e["status"] != status:
            continue
        if kind is not None and e["event_kind"] != kind:
            continue
        rows.append(e)
    return _listing(rows, S.event_json, limit, offset)


# ---------------------------------------------------------------------------
# Sitter assignments
# ---------------------------------------------------------------------------
@bp.get("/observation/sitter-assignments/<assignment_id>")
def get_assignment(assignment_id):
    authenticate(ALL_ROLES)
    assignment = _fetch(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    return object_response(S.assignment_json(assignment))


@bp.get("/observation/sitter-assignments/<assignment_id>/handoffs")
def list_assignment_handoffs(assignment_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    state = enum_filter("documentation_state", DOC_STATES)
    assignment = _fetch(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    rows = []
    for h in db.handoffs.values():
        if assignment["id"] not in (h["outgoing_assignment_id"], h["incoming_assignment_id"]):
            continue
        if state is not None and h["documentation_state"] != state:
            continue
        rows.append(h)
    return _listing(rows, S.handoff_json, limit, offset)


@bp.get("/observation/sitter-assignments/<assignment_id>/cost-entries")
def list_assignment_cost_entries(assignment_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", ENTRY_STATUSES)
    kind = enum_filter("entry_kind", ENTRY_KINDS)
    assignment = _fetch(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    rows = []
    for c in calc.cost_entries_of_assignment(assignment["id"]):
        if status is not None and c["status"] != status:
            continue
        if kind is not None and c["entry_kind"] != kind:
            continue
        rows.append(c)
    return _listing(rows, S.cost_entry_json, limit, offset)


@bp.get("/observation/sitter-assignments/<assignment_id>/safety-events")
def list_assignment_events(assignment_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", EVENT_STATUSES)
    kind = enum_filter("event_kind", EVENT_KINDS)
    assignment = _fetch(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    rows = []
    for e in db.events.values():
        if e["assignment_id"] != assignment["id"]:
            continue
        if status is not None and e["status"] != status:
            continue
        if kind is not None and e["event_kind"] != kind:
            continue
        rows.append(e)
    return _listing(rows, S.event_json, limit, offset)


# ---------------------------------------------------------------------------
# Monitoring stations, feeds, events, handoffs, reassessments, cost entries
# ---------------------------------------------------------------------------
@bp.get("/observation/monitoring-stations/<station_id>")
def get_station(station_id):
    authenticate(ALL_ROLES)
    station = _fetch(db.stations, station_id, "ERR_STATION_NOT_FOUND")
    return object_response(S.station_json(station))


@bp.get("/observation/monitoring-stations/<station_id>/video-feeds")
def list_station_feeds(station_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", FEED_STATUSES)
    station = _fetch(db.stations, station_id, "ERR_STATION_NOT_FOUND")
    rows = [
        f
        for f in calc.feeds_of_station(station["id"])
        if status is None or f["status"] == status
    ]
    return _listing(rows, S.feed_json, limit, offset)


@bp.get("/observation/video-feeds/<feed_id>")
def get_feed(feed_id):
    authenticate(ALL_ROLES)
    feed = _fetch(db.feeds, feed_id, "ERR_FEED_NOT_FOUND")
    return object_response(S.feed_json(feed))


@bp.get("/observation/safety-events/<event_id>")
def get_event(event_id):
    authenticate(ALL_ROLES)
    event = _fetch(db.events, event_id, "ERR_SAFETY_EVENT_NOT_FOUND")
    return object_response(S.event_json(event))


@bp.get("/observation/handoffs/<handoff_id>")
def get_handoff(handoff_id):
    authenticate(ALL_ROLES)
    handoff = _fetch(db.handoffs, handoff_id, "ERR_HANDOFF_NOT_FOUND")
    return object_response(S.handoff_json(handoff))


@bp.get("/observation/reassessments/<reassessment_id>")
def get_reassessment(reassessment_id):
    authenticate(ALL_ROLES)
    row = _fetch(db.reassessments, reassessment_id, "ERR_REASSESSMENT_NOT_FOUND")
    return object_response(S.reassessment_json(row))


@bp.get("/observation/cost-entries/<entry_id>")
def get_cost_entry(entry_id):
    authenticate(ALL_ROLES)
    row = _fetch(db.cost_entries, entry_id, "ERR_COST_ENTRY_NOT_FOUND")
    return object_response(S.cost_entry_json(row))
