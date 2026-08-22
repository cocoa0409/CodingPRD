"""Secure material lots, the chain of custody and reconciliation (PRD 3.5)."""

from flask import Blueprint, request

import serialize
from db import create, db, now, ordered, touch
from derive import (
    custody_events_of_lot,
    lot_replacement_charge,
    outstanding_booklets,
    recompute_district_ledger,
    recompute_session_materials,
    recompute_window_breach,
    replay_chain,
)
from errors import api_error
from middleware import (
    ALL_ROLES,
    CUSTODY_EVENT_TYPES,
    DISTRICT_COORDINATOR,
    PROCTOR,
    SCHOOL_COORDINATOR,
    STATE_OFFICER,
    body_reference,
    custody_event_guard,
    endpoint,
    json_body,
    require_scope,
    resolve,
)
from response import object_response, paginate
from validators import identifier_field, integer_field, nullable_string, string_field

bp = Blueprint("materials", __name__)

LOT_CODE_PATTERN = r"LOT-[A-Z0-9]{2,8}"

HOLDER_TYPES = {
    "RECEIPT": ("STATE", "DISTRICT"),
    "TRANSFER_TO_SCHOOL": ("DISTRICT", "SCHOOL"),
    "SESSION_CHECKOUT": ("SCHOOL", "SESSION"),
    "SESSION_CHECKIN": ("SESSION", "SCHOOL"),
    "RETURN_TO_DISTRICT": ("SCHOOL", "DISTRICT"),
    "DESTRUCTION": ("DISTRICT", "DESTROYED"),
}

SESSION_SCOPED_EVENTS = ("SESSION_CHECKOUT", "SESSION_CHECKIN")


# --------------------------------------------------------------------------
# Lots
# --------------------------------------------------------------------------
@bp.post("/material-lots")
@endpoint(STATE_OFFICER)
def create_lot(actor):
    body = json_body()
    window_id = identifier_field(body, "window_id")
    district_id = identifier_field(body, "district_id")
    lot_code = string_field(body, "lot_code", pattern=LOT_CODE_PATTERN)
    quantity_shipped = integer_field(body, "quantity_shipped", minimum=1, maximum=5000)
    seal_range_start = integer_field(body, "seal_range_start", minimum=1)
    seal_range_end = integer_field(body, "seal_range_end")
    if seal_range_end - seal_range_start + 1 != quantity_shipped:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "the sealed serial range must tally with quantity_shipped.",
        )

    resolve(db.windows, window_id, "ERR_TEST_WINDOW_NOT_FOUND")
    resolve(db.districts, district_id, "ERR_DISTRICT_NOT_FOUND")

    for existing in db.lots.values():
        if existing["lot_code"] == lot_code:
            raise api_error("ERR_DUPLICATE_CODE", "lot_code already exists.")

    lot = create(
        db.lots,
        {
            "window_id": window_id,
            "district_id": district_id,
            "lot_code": lot_code,
            "quantity_shipped": quantity_shipped,
            "seal_range_start": seal_range_start,
            "seal_range_end": seal_range_end,
            "status": "SHIPPED",
            "quantity_at_district": 0,
            "quantity_at_school": 0,
            "quantity_in_sessions": 0,
            "quantity_destroyed": 0,
            "chain_accounted_count": 0,
            "declared_accounted_count": None,
            "chain_vs_declared_delta": None,
            "missing_count": 0,
            "seal_broken_count": 0,
            "replacement_charge_cents": 0,
            "charge_reversed": False,
            "reconciled_at": None,
        },
    )
    return object_response(serialize.lot(lot), 201)


@bp.get("/material-lots/<material_lot_id>")
@endpoint(*ALL_ROLES)
def read_lot(actor, material_lot_id):
    lot = resolve(db.lots, material_lot_id, "ERR_MATERIAL_LOT_NOT_FOUND")
    return object_response(serialize.lot(lot))


@bp.get("/material-lots")
@endpoint(*ALL_ROLES)
def list_lots(actor):
    window_id = request.args.get("window_id")
    district_id = request.args.get("district_id")
    status = request.args.get("status")
    items = [
        lot
        for lot in db.lots.values()
        if (window_id is None or lot["window_id"] == window_id)
        and (district_id is None or lot["district_id"] == district_id)
        and (status is None or lot["status"] == status)
    ]
    return paginate(ordered(items), serialize.lot)


# --------------------------------------------------------------------------
# Custody events
# --------------------------------------------------------------------------
@bp.post("/material-lots/<material_lot_id>/custody-events")
@endpoint(DISTRICT_COORDINATOR, SCHOOL_COORDINATOR, PROCTOR, sub_operation=custody_event_guard)
def append_custody_event(actor, material_lot_id):
    lot = resolve(db.lots, material_lot_id, "ERR_MATERIAL_LOT_NOT_FOUND")

    # Check 4 — the acting principal must own the lot.
    if actor.role == DISTRICT_COORDINATOR:
        require_scope(actor.user_id == lot["district_id"])
    elif actor.role == SCHOOL_COORDINATOR:
        school = db.schools.get(actor.user_id)
        require_scope(school is not None and school["district_id"] == lot["district_id"])
    else:
        scoped_session_id = body_reference("session_id")
        scoped_session = db.sessions.get(scoped_session_id) if scoped_session_id else None
        if scoped_session is not None:
            require_scope(scoped_session["proctor_id"] == actor.user_id)

    body = json_body()
    event_type = string_field(body, "event_type")
    if event_type not in CUSTODY_EVENT_TYPES:
        raise api_error("ERR_INVALID_REQUEST", "event_type must be a declared movement type.")
    quantity = integer_field(body, "quantity", minimum=1)
    sealed_count = integer_field(body, "sealed_count", minimum=0)
    if sealed_count > quantity:
        raise api_error("ERR_INVALID_REQUEST", "sealed_count may not exceed quantity.")
    note = nullable_string(body, "note")
    session_id = body.get("session_id")
    if event_type in SESSION_SCOPED_EVENTS:
        session_id = identifier_field(body, "session_id")
    elif session_id is not None:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "session_id is only accepted on session-scoped movements.",
        )

    session = None
    if session_id is not None:
        session = resolve(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")

    next_status = _screen_custody_event(lot, event_type, quantity, session)

    events = custody_events_of_lot(lot["id"])
    from_holder, to_holder = HOLDER_TYPES[event_type]
    event = create(
        db.custody_events,
        {
            "material_lot_id": lot["id"],
            "previous_event_id": events[-1]["id"] if events else None,
            "session_id": session["id"] if session is not None else None,
            "sequence_no": len(events) + 1,
            "event_type": event_type,
            "quantity": quantity,
            "sealed_count": sealed_count,
            "from_holder_type": from_holder,
            "to_holder_type": to_holder,
            "actor_user_id": actor.user_id,
            "actor_role": actor.role,
            "occurred_at": now(),
            "chain_balance_after": 0,
            "note": note,
        },
        common_fields=False,
    )

    replay_chain(lot)
    lot["status"] = next_status
    touch(lot)
    if session is not None:
        recompute_session_materials(session)

    return object_response(serialize.custody_event(event), 201)


def _chain_broken(message):
    raise api_error("ERR_CUSTODY_CHAIN_BROKEN", message)


def _screen_custody_event(lot, event_type, quantity, session):
    """Checks 12 (chain continuity) then 13 (booklet availability).
    Returns the lot status the movement lands in."""
    status = lot["status"]

    if event_type == "RECEIPT":
        if status != "SHIPPED" or custody_events_of_lot(lot["id"]):
            _chain_broken("a receipt must be the lot's first custody entry.")
        if quantity != lot["quantity_shipped"]:
            _chain_broken("a receipt must take delivery of the whole lot.")
        return "RECEIVED"

    if event_type == "TRANSFER_TO_SCHOOL":
        if status != "RECEIVED":
            _chain_broken("the lot has not been received by its district.")
        if quantity > lot["quantity_at_district"]:
            raise api_error("ERR_INSUFFICIENT_MATERIALS")
        return "IN_DISTRIBUTION"

    if event_type == "SESSION_CHECKOUT":
        if status != "IN_DISTRIBUTION":
            _chain_broken("the lot is not in distribution.")
        if session["status"] != "SCHEDULED":
            _chain_broken("booklets may only be checked out to a scheduled session.")
        if quantity > lot["quantity_at_school"]:
            raise api_error("ERR_INSUFFICIENT_MATERIALS")
        return status

    if event_type == "SESSION_CHECKIN":
        if status != "IN_DISTRIBUTION":
            _chain_broken("the lot is not in distribution.")
        if session["status"] != "ACTIVE":
            _chain_broken("booklets may only be checked in against an active session.")
        outstanding = outstanding_booklets(session)
        if outstanding <= 0:
            _chain_broken("the session holds no open checkout.")
        if quantity > outstanding or quantity > lot["quantity_in_sessions"]:
            raise api_error("ERR_INSUFFICIENT_MATERIALS")
        return status

    if event_type == "RETURN_TO_DISTRICT":
        if status != "IN_DISTRIBUTION":
            _chain_broken("the lot is not in distribution.")
        if lot["quantity_in_sessions"] != 0:
            _chain_broken("booklets are still out in sessions.")
        if quantity < lot["quantity_at_school"]:
            _chain_broken("a return must empty the school bucket completely.")
        if quantity > lot["quantity_at_school"]:
            raise api_error("ERR_INSUFFICIENT_MATERIALS")
        return "RETURNED_PENDING"

    # DESTRUCTION
    if status != "RETURNED_PENDING":
        _chain_broken("the lot has not been returned to its district.")
    if quantity > lot["quantity_at_district"]:
        raise api_error("ERR_INSUFFICIENT_MATERIALS")
    return status


@bp.get("/custody-events/<custody_event_id>")
@endpoint(*ALL_ROLES)
def read_custody_event(actor, custody_event_id):
    event = resolve(db.custody_events, custody_event_id, "ERR_CUSTODY_EVENT_NOT_FOUND")
    return object_response(serialize.custody_event(event))


@bp.get("/custody-events")
@endpoint(*ALL_ROLES)
def list_custody_events(actor):
    material_lot_id = request.args.get("material_lot_id")
    session_id = request.args.get("session_id")
    previous_event_id = request.args.get("previous_event_id")
    event_type = request.args.get("event_type")
    items = [
        event
        for event in db.custody_events.values()
        if (material_lot_id is None or event["material_lot_id"] == material_lot_id)
        and (session_id is None or event.get("session_id") == session_id)
        and (previous_event_id is None or event.get("previous_event_id") == previous_event_id)
        and (event_type is None or event["event_type"] == event_type)
    ]
    return paginate(ordered(items), serialize.custody_event)


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------
@bp.post("/material-lots/<material_lot_id>/reconciliations")
@endpoint(DISTRICT_COORDINATOR)
def reconcile_lot(actor, material_lot_id):
    lot = resolve(db.lots, material_lot_id, "ERR_MATERIAL_LOT_NOT_FOUND")
    require_scope(actor.user_id == lot["district_id"])

    body = json_body()
    declared_returned_count = integer_field(body, "declared_returned_count", minimum=0)
    declared_destroyed_count = integer_field(body, "declared_destroyed_count", minimum=0)
    broken_seal_count = integer_field(body, "broken_seal_count", minimum=0)

    if lot["status"] != "RETURNED_PENDING":
        raise api_error("ERR_LOT_NOT_AWAITING_RECONCILIATION")

    declared_accounted = declared_returned_count + declared_destroyed_count
    lot["declared_accounted_count"] = declared_accounted
    lot["chain_vs_declared_delta"] = lot["chain_accounted_count"] - declared_accounted
    lot["missing_count"] = max(0, lot["quantity_shipped"] - declared_accounted)
    lot["seal_broken_count"] = broken_seal_count
    lot["reconciled_at"] = now()

    clean = (
        lot["missing_count"] == 0
        and lot["chain_vs_declared_delta"] == 0
        and broken_seal_count == 0
    )
    if clean:
        lot["status"] = "RECONCILED"
        lot["replacement_charge_cents"] = 0
        touch(lot)
        return object_response(serialize.lot(lot))

    lot["status"] = "DISCREPANT"
    lot["replacement_charge_cents"] = lot_replacement_charge(lot)
    touch(lot)
    recompute_district_ledger(db.districts.get(lot["district_id"]))
    create(
        db.reports,
        {
            "session_id": None,
            "registration_id": None,
            "reporter_proctor_id": None,
            "material_lot_id": lot["id"],
            "category": "SECURITY_BREACH",
            "severity": "HIGH",
            "narrative": "Lot %s reconciled with a discrepancy." % lot["lot_code"],
            "status": "SUBMITTED",
            "disposition": None,
            "return_count": 0,
            "adjudicated_at": None,
            "system_generated": True,
        },
    )
    recompute_window_breach(db.windows.get(lot["window_id"]))
    return object_response(serialize.lot(lot))
