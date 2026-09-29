"""Quarantine orders: seals, holds, release and breach (PRD 3.7)."""

from flask import Blueprint

import calc
import services
from envelope import created, ok
from errors import ApiError
from routes._common import ALL_ROLES, listing, matches, read_pagination
from store import base_row, db, now, now_iso, parse_iso, serialize, touch
from validate import (arg_filter, opt_str, read_body, req_enum,
                      req_ref, req_str, require_auth)

bp = Blueprint("quarantine", __name__)

RELEASE_OUTCOMES = ("APPROVED", "REJECTED")
HOLDING_STATUSES = ("SEALED", "RELEASE_REQUESTED")


@bp.post("/quarantine-orders")
def issue_order():
    user_id, _role, actor = require_auth(("Inspector",))
    body = read_body()
    record_id = req_ref(body, "inspection_record_id")
    seal_number = req_str(body, "seal_number")

    record = services.record_or_404(record_id)

    for existing in db.quarantine_orders.values():
        if existing["seal_number"] == seal_number:
            raise ApiError("ERR_SEAL_NUMBER_DUPLICATE")

    if record["inspection_status"] != "DECON_REQUIRED":
        raise ApiError("ERR_RECORD_NOT_AWAITING_DECON")

    services.require_active(actor)

    for existing in db.quarantine_orders.values():
        if existing["watercraft_id"] != record["watercraft_id"]:
            continue
        if existing["status"] not in HOLDING_STATUSES:
            continue
        hold_until = parse_iso(existing["hold_until"])
        if hold_until is not None and now() <= hold_until:
            raise ApiError("ERR_WATERCRAFT_ALREADY_QUARANTINED")

    if not record["quarantine_warranted"]:
        raise ApiError("ERR_QUARANTINE_NOT_WARRANTED")

    station = services.station_or_404(record["station_id"])
    if station["seal_stock_count"] < 1:
        raise ApiError("ERR_STATION_SEAL_STOCK_EXHAUSTED")

    row = base_row()
    row.update({
        "inspection_record_id": record["id"],
        "watercraft_id": record["watercraft_id"],
        "station_id": station["id"],
        "issued_by_inspector_id": user_id,
        "release_verified_by_inspector_id": None,
        "seal_number": seal_number,
        "seal_state_code": services.station_seal_state_code(station),
        "status": "SEALED",
        "band_at_issue": record["risk_band"],
        "issued_at": now_iso(),
        "hold_hours_required": 0,
        "hold_until": None,
        "rejected_release_count": 0,
    })
    db.quarantine_orders[row["id"]] = row

    station["seal_stock_count"] -= 1
    station["seals_in_circulation_count"] += 1
    touch(station)

    vessel = db.watercraft.get(record["watercraft_id"])
    services.apply_hold(row, vessel)
    if vessel is not None:
        touch(vessel)
    return created(serialize(row))


@bp.get("/quarantine-orders/<qid>")
def get_order(qid):
    require_auth(ALL_ROLES)
    return ok(serialize(services.quarantine_order_or_404(qid)))


@bp.get("/quarantine-orders")
def list_orders():
    require_auth(ALL_ROLES)
    limit, offset = read_pagination()
    filters = {
        "inspection_record_id": arg_filter("inspection_record_id"),
        "watercraft_id": arg_filter("watercraft_id"),
        "station_id": arg_filter("station_id"),
        "issued_by_inspector_id": arg_filter("issued_by_inspector_id"),
        "release_verified_by_inspector_id":
            arg_filter("release_verified_by_inspector_id"),
        "status": arg_filter("status"),
        "seal_number": arg_filter("seal_number"),
    }
    rows = [r for r in db.quarantine_orders.values() if matches(r, filters)]
    return listing(rows, limit, offset)


@bp.post("/quarantine-orders/<qid>/release-request")
def request_release(qid):
    user_id, _role, _actor = require_auth(("Inspector",))
    body = read_body()
    opt_str(body, "notes", min_len=None)

    order = services.quarantine_order_or_404(qid)

    if order["issued_by_inspector_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    if order["status"] != "SEALED":
        raise ApiError("ERR_QUARANTINE_NOT_SEALED")

    hold_until = parse_iso(order["hold_until"])
    if hold_until is None or now() < hold_until:
        raise ApiError("ERR_HOLD_PERIOD_NOT_ELAPSED")

    order["status"] = "RELEASE_REQUESTED"
    touch(order)
    return ok(serialize(order))


@bp.post("/quarantine-orders/<qid>/release")
def decide_release(qid):
    user_id, _role, actor = require_auth(("ReleaseVerifier",))
    body = read_body()
    outcome = req_enum(body, "outcome", RELEASE_OUTCOMES)
    opt_str(body, "notes", min_len=None)

    order = services.quarantine_order_or_404(qid)

    if order["status"] != "RELEASE_REQUESTED":
        raise ApiError("ERR_QUARANTINE_RELEASE_NOT_REQUESTED")

    services.require_active(actor)
    services.require_verifier_certified(actor)

    record = db.records.get(order["inspection_record_id"])
    vessel = db.watercraft.get(order["watercraft_id"])

    if outcome == "APPROVED":
        hold_until = parse_iso(order["hold_until"])
        if hold_until is None or now() < hold_until:
            raise ApiError("ERR_HOLD_PERIOD_NOT_ELAPSED")
        if (record is not None and record["decon_mandatory"]
                and not services.has_verified_decon(record["id"])):
            raise ApiError("ERR_DECON_REQUIRED_BEFORE_RELEASE")

    if user_id == order["issued_by_inspector_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    order["release_verified_by_inspector_id"] = user_id

    if outcome == "APPROVED":
        order["status"] = "RELEASED"
        services.retire_seal(db.stations.get(order["station_id"]))
        if vessel is not None:
            vessel["quarantine_hold_until"] = None
            touch(vessel)
    else:
        order["status"] = "SEALED"
        order["rejected_release_count"] += 1
        services.apply_hold(order, vessel)
        if vessel is not None:
            touch(vessel)
        if (order["rejected_release_count"] >= calc.REJECTED_RELEASE_REFERRAL_THRESHOLD
                and record is not None and record["enforcement_status"] == "NONE"):
            services.apply_referral(record, "QUARANTINE_RELEASE_FAILURE")

    touch(order)
    return ok(serialize(order))


@bp.post("/quarantine-orders/<qid>/breach-report")
def report_breach(qid):
    require_auth(("ReleaseVerifier", "EnforcementOfficer"))
    body = read_body()
    opt_str(body, "notes", min_len=None)

    order = services.quarantine_order_or_404(qid)

    if order["status"] not in HOLDING_STATUSES:
        raise ApiError("ERR_QUARANTINE_NOT_SEALED")

    order["status"] = "VOIDED_BREACH"
    services.retire_seal(db.stations.get(order["station_id"]))

    vessel = db.watercraft.get(order["watercraft_id"])
    if vessel is not None:
        vessel["quarantine_hold_until"] = None
        touch(vessel)

    record = db.records.get(order["inspection_record_id"])
    if record is not None and record["enforcement_status"] == "NONE":
        services.apply_referral(record, "SEAL_TAMPER")

    touch(order)
    return ok(serialize(order))
