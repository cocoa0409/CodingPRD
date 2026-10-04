"""Transfer endpoints: create, dispatch, receive, reconcile, void-receiving,
redispatch, advance, discrepancy, plus reverse-reachability capacity reads."""

from flask import Blueprint, request

import calculations as calc
import db
import middleware as mw
import response as resp
import serializers as ser
import services
from errors import ApiError

bp = Blueprint("transfers", __name__)

TRANSFER_READ_ROLES = ["PlatformAdmin", "BoutiqueManager", "RetailLead"]


def _gate_check(day):
    """Priority 8: a SUSPENDED gate refuses this retail-side write."""
    if day is not None and day.get("conversion_gate") == "SUSPENDED":
        raise ApiError("ERR_STORE_DAY_GATE_SUSPENDED")


def _restricted_check(day):
    """Priority 24: a GATED_RESTRICTED gate refuses new backroom load."""
    if day is not None and day.get("conversion_gate") == "GATED_RESTRICTED":
        raise ApiError("ERR_STORE_DAY_GATE_RESTRICTED")


def _dispatch_admission(location_rec, declared_units):
    free = location_rec.get("staging_free_units", 0) or 0
    capacity = location_rec.get("backroom_capacity_units", 0) or 0
    return free >= 1 or declared_units <= capacity


@bp.post("/retail-ops/transfers")
def create_transfer():
    ctx = mw.context()
    mw.require_role(ctx, ["RetailLead"])
    data = mw.body()

    location_id = mw.required(data, "location_id")
    location_rec = db.get_or_404(db.locations, location_id, "ERR_LOCATION_NOT_FOUND")
    store_day_id = mw.required(data, "store_day_id")
    db.get_or_404(db.store_days, store_day_id, "ERR_STORE_DAY_NOT_FOUND")

    declared = mw.required(data, "declared_units", int)
    if declared <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "declared_units must be greater than zero.")
    received = mw.required(data, "received_units", int)
    if received < 0:
        raise ApiError("ERR_INVALID_REQUEST", "received_units must not be negative.")

    receiving_zone = mw.required(data, "receiving_zone")
    if receiving_zone not in {"BACKROOM", "FOOD_STORAGE"}:
        raise ApiError("ERR_INVALID_REQUEST", "receiving_zone is not a declared zone.")

    item_id = mw.required(data, "item_id")

    # Priority 6 — a FOOD_STORAGE transfer carrying item lines is refused.
    if receiving_zone == "FOOD_STORAGE":
        raise ApiError("ERR_FOOD_STORAGE_ZONE_FORBIDDEN")

    # Priority 9 — the item reference.
    db.get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")

    rec = db.new_record({
        "location_id": location_rec["id"],
        "store_day_id": store_day_id,
        "item_id": item_id,
        "declared_units": declared,
        "received_units": received,
        "receiving_zone": receiving_zone,
        "status": "PLANNED",
        "variance_units": 0,
        "variance_bps": 0,
        "dispatched_at": None,
        "received_at": None,
    })
    db.transfers[rec["id"]] = rec
    calc.recompute_location_posture(location_rec)
    return resp.ok(ser.transfer(rec), 201)


@bp.get("/retail-ops/transfers")
def list_transfers():
    ctx = mw.context()
    mw.require_role(ctx, TRANSFER_READ_ROLES)
    records = resp.order_records([r for r in db.transfers.values() if mw.matches(r, {
        "location_id": mw.query_str("location_id"),
        "store_day_id": mw.query_str("store_day_id"),
        "item_id": mw.query_str("item_id"),
        "status": mw.query_str("status"),
        "receiving_zone": mw.query_str("receiving_zone"),
    })])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.transfer(r) for r in page], pagination=pagination)


@bp.get("/retail-ops/transfers/<transfer_id>")
def get_transfer(transfer_id):
    ctx = mw.context()
    mw.require_role(ctx, TRANSFER_READ_ROLES)
    rec = db.get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    return resp.ok(ser.transfer(rec))


@bp.get("/retail-ops/transfers/<transfer_id>/capacity-readings")
def list_transfer_readings(transfer_id):
    ctx = mw.context()
    mw.require_role(ctx, TRANSFER_READ_ROLES)
    db.get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    records = resp.order_records(
        [r for r in db.capacity_readings.values() if r.get("trigger_transfer_id") == transfer_id])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.capacity_reading(r) for r in page], pagination=pagination)


@bp.get("/retail-ops/transfers/<transfer_id>/discrepancy")
def transfer_discrepancy(transfer_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager", "RetailLead"])
    rec = db.get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    return resp.ok(ser.transfer_discrepancy(rec))


@bp.post("/retail-ops/transfers/<transfer_id>/dispatch")
def dispatch_transfer(transfer_id):
    ctx = mw.context()
    mw.require_role(ctx, ["RetailLead"])
    rec = db.get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")

    location_rec = db.locations.get(rec.get("location_id"))
    day = db.store_days.get(rec.get("store_day_id"))

    # Priority 8 — the suspended gate refuses dispatch.
    _gate_check(day)

    if rec.get("status") != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")

    if not _dispatch_admission(location_rec, rec.get("declared_units", 0)):
        raise ApiError("ERR_POSTURE_LOCKOUT")

    rec["status"] = "IN_TRANSIT"
    rec["dispatched_at"] = db.fmt_ts(db.now())
    db.touch(rec)

    calc.recompute_location_posture(location_rec)
    if location_rec.get("staging_free_units", 0) <= 0 and day is not None:
        day["conversion_gate"] = "GATED_RESTRICTED"
        db.touch(day)
    return resp.ok(ser.transfer(rec))


@bp.post("/retail-ops/transfers/<transfer_id>/advance")
def advance_transfer(transfer_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")

    data = mw.body()
    target = db.parse_ts(mw.required(data, "from_iso8601"), "from_iso8601")
    db.set_clock(target)

    location_rec = db.locations.get(rec.get("location_id"))
    for schedule in services.clearance_schedules_for_location(location_rec["id"], {"ACTIVE", "EXTENDED"}):
        steps = services.weeks_on_clearance(schedule)
        if steps <= 0:
            continue
        services.advance_schedule_markdown(schedule, steps=steps,
                                           mirror=(schedule.get("status") == "ACTIVE"))

    day = db.store_days.get(rec.get("store_day_id"))
    if day is not None:
        db.touch(day)
    return resp.ok(ser.store_day(day) if day is not None else {})


@bp.post("/retail-ops/transfers/<transfer_id>/receive")
def receive_transfer(transfer_id):
    ctx = mw.context()
    mw.require_role(ctx, ["RetailLead"])
    rec = db.get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    data = mw.body()

    location_rec = db.locations.get(rec.get("location_id"))
    day = db.store_days.get(rec.get("store_day_id"))
    item_rec = db.items.get(rec.get("item_id"))

    # Priority 7 — state (checked before the priority-8 gate rule: a receiving
    # that is both in the wrong state and posted on a suspended day reports the
    # state failure).
    if rec.get("status") != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE")

    # Priority 8 — the suspended gate refuses this write.
    _gate_check(day)

    received = mw.required(data, "received_units", int)
    if received < 0:
        raise ApiError("ERR_INVALID_REQUEST", "received_units must not be negative.")

    # Priority 17 — the staging-free-units floor for the projected write.  It is
    # evaluated before the priority-24 restricted-gate rule because the numeric
    # ladder is a total order (PRD 2.12: 17 < 24).
    declared = rec.get("declared_units", 0)
    projected_free = (location_rec.get("staging_free_units", 0) or 0) + declared - received
    if projected_free < 0:
        raise ApiError("ERR_BACKROOM_OVER_CAPACITY")

    # Priority 24 — the restricted gate refuses new backroom load.
    _restricted_check(day)

    rec["received_units"] = received
    rec["received_at"] = db.fmt_ts(db.now())
    rec["variance_units"] = received - declared
    rec["variance_bps"] = db.cents(
        abs(rec["variance_units"]) * 10000 / declared) if declared else 0
    rec["status"] = "RECEIVED"

    # The claim staked at dispatch is released before the space is re-measured,
    # so the appended reading snapshots the post-release committed figure.
    calc.recompute_location_posture(location_rec)

    services.build_capacity_reading(
        location_rec, rec.get("store_day_id"), rec["id"], rec["received_at"],
        received, 0, 0, "RECEIVING")

    if rec.get("receiving_zone") == "BACKROOM" and item_rec is not None:
        item_rec["on_hand_units"] = (item_rec.get("on_hand_units", 0) or 0) + received
        db.touch(item_rec)

    db.touch(rec)
    return resp.ok(ser.transfer(rec))


@bp.post("/retail-ops/transfers/<transfer_id>/reconcile")
def reconcile_transfer(transfer_id):
    ctx = mw.context()
    mw.require_role(ctx, ["RetailLead"])
    rec = db.get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")

    day = db.store_days.get(rec.get("store_day_id"))
    if rec.get("status") != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE")

    # Priority 27 — the variance must be within the brand's tolerance.
    brand_rec = calc.brand_of_store_day(day) if day is not None else None
    tolerance = brand_rec.get("transfer_variance_tolerance_bps", 200) if brand_rec else 200
    if rec.get("variance_bps", 0) > tolerance:
        raise ApiError("ERR_TRANSFER_VARIANCE_EXCEEDED")

    rec["status"] = "RECONCILED"
    db.touch(rec)
    return resp.ok(ser.transfer(rec))


@bp.post("/retail-ops/transfers/<transfer_id>/void-receiving")
def void_receiving(transfer_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")

    location_rec = db.locations.get(rec.get("location_id"))
    day = db.store_days.get(rec.get("store_day_id"))
    item_rec = db.items.get(rec.get("item_id"))

    if rec.get("status") != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE")

    brand_rec = calc.brand_of_store_day(day) if day is not None else None
    tolerance = brand_rec.get("transfer_variance_tolerance_bps", 200) if brand_rec else 200
    # Priority 27 declares the refusal identifier for the receiving-tolerance
    # rule; a within-tolerance transfer is refused on exactly that ground, so the
    # rule's own id is reported rather than a generic state error.
    if rec.get("variance_bps", 0) <= tolerance:
        raise ApiError("ERR_TRANSFER_VARIANCE_EXCEEDED")

    if day is None or day.get("day_status") != "OPEN":
        raise ApiError("ERR_STORE_DAY_CLOSED")

    rec["status"] = "VOID_RECEIVING"
    if item_rec is not None:
        item_rec["on_hand_units"] = ((item_rec.get("on_hand_units", 0) or 0)
                                     - rec.get("received_units", 0)
                                     + rec.get("declared_units", 0))
        db.touch(item_rec)

    services.build_capacity_reading(
        location_rec, rec.get("store_day_id"), rec["id"], db.fmt_ts(db.now()),
        -rec.get("received_units", 0), 0, 0, "RECEIVING")

    # Restore the conserved quantity to its pre-receiving value.
    calc.recompute_location_posture(location_rec)
    db.touch(location_rec)
    db.touch(rec)
    return resp.ok(ser.transfer(rec))


@bp.post("/retail-ops/transfers/<transfer_id>/redispatch")
def redispatch_transfer(transfer_id):
    ctx = mw.context()
    mw.require_role(ctx, ["RetailLead"])
    rec = db.get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")

    location_rec = db.locations.get(rec.get("location_id"))
    if rec.get("status") != "VOID_RECEIVING":
        raise ApiError("ERR_INVALID_STATE")

    if not _dispatch_admission(location_rec, rec.get("declared_units", 0)):
        raise ApiError("ERR_POSTURE_LOCKOUT")

    rec["status"] = "IN_TRANSIT"
    rec["received_units"] = 0
    rec["variance_units"] = 0
    rec["variance_bps"] = 0
    db.touch(rec)

    calc.recompute_location_posture(location_rec)
    db.touch(location_rec)
    return resp.ok(ser.transfer(rec))