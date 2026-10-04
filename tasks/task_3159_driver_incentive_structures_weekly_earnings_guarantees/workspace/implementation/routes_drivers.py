"""Driver endpoints."""
from flask import Blueprint, request

import db
from errors import err_invalid_request, err_invalid_state
from middleware import require_roles
from response import success_list, success_object
from services import (
    cancel_enrollment,
    driver_view,
    enrollment_view,
    get_driver_or_404,
    get_market_or_404,
    iso_now,
    maybe_rate_posture_cascade,
    new_entity,
    paginate,
    parse_iso,
    record_rate_event,
    require_str,
    ride_view,
    rolling_recompute,
    settlement_view,
    statement_view,
    touch,
    touch_expiry,
)

bp = Blueprint("drivers", __name__)

ALL_READ = ("PlatformAdmin", "IncentiveOps", "PaymentsOfficer", "FraudAnalyst", "Driver")
STAFF_READ = ("PlatformAdmin", "IncentiveOps", "PaymentsOfficer", "FraudAnalyst")

RATE_EVENT_TYPES = ("OFFER_RECORDED", "OFFER_ACCEPTED", "OFFER_DECLINED", "DRIVER_CANCEL")


@bp.post("/drivers")
@require_roles("IncentiveOps")
def create_driver(_user_id, _role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    market_id = body.get("market_id")
    if not isinstance(market_id, str):
        raise err_invalid_request("market_id is required")
    get_market_or_404(market_id)
    display_name = require_str(body.get("display_name"), "display_name")
    d = new_entity(
        {
            "market_id": market_id,
            "display_name": display_name,
            "rate_posture": "ELIGIBLE",
            "fraud_posture": "CLEAR",
            "acceptance_rate_bps": 10000,
            "cancellation_rate_bps": 0,
            "offers_total": 0,
            "accepted_total": 0,
            "cancelled_total": 0,
            "account_status": "ACTIVE",
            "acute_score": 0,
            "chronic_score": 0,
        }
    )
    db.drivers[d["id"]] = d
    return success_object(driver_view(d), 201)


@bp.get("/drivers/<did>")
@require_roles(*ALL_READ)
def get_driver(did, _user_id, _role):
    d = get_driver_or_404(did)
    return success_object(driver_view(d))


@bp.get("/drivers")
@require_roles(*STAFF_READ)
def list_drivers(_user_id, _role):
    items = list(db.drivers.values())
    market_id = request.args.get("market_id")
    rate_posture = request.args.get("rate_posture")
    fraud_posture = request.args.get("fraud_posture")
    if market_id is not None:
        items = [d for d in items if d["market_id"] == market_id]
    if rate_posture is not None:
        items = [d for d in items if d["rate_posture"] == rate_posture]
    if fraud_posture is not None:
        items = [d for d in items if d["fraud_posture"] == fraud_posture]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([driver_view(d) for d in page], limit, offset, total)


@bp.post("/drivers/<did>/rate-events")
@require_roles("IncentiveOps")
def record_rate_events(did, _user_id, _role):
    d = get_driver_or_404(did)
    if d["account_status"] != "ACTIVE":
        raise err_invalid_state("Driver account is not ACTIVE")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    events = body.get("events")
    if not isinstance(events, list):
        raise err_invalid_request("events must be a list")
    for ev in events:
        if not isinstance(ev, dict):
            raise err_invalid_request("each event must be an object")
        etype = ev.get("type")
        if etype not in RATE_EVENT_TYPES:
            raise err_invalid_request(f"event type must be one of {RATE_EVENT_TYPES}")
        recorded_at = ev.get("recorded_at")
        if recorded_at is not None:
            recorded_at = parse_iso(recorded_at, "recorded_at")
        record_rate_event(d, etype, recorded_at)
    old, new = rolling_recompute(d)
    maybe_rate_posture_cascade(d, old, new)
    return success_object(driver_view(d))


@bp.post("/drivers/<did>/deactivate")
@require_roles("PlatformAdmin")
def deactivate_driver(did, _user_id, _role):
    d = get_driver_or_404(did)
    if d["account_status"] != "ACTIVE":
        raise err_invalid_state("Driver account is not ACTIVE")
    for s in db.settlements.values():
        if s["driver_id"] == d["id"] and s["status"] in ("DRAFT", "REOPENED"):
            raise err_invalid_state("Driver has open settlements")
    for enr in db.enrollments.values():
        if enr["driver_id"] == d["id"] and enr["status"] == "ACTIVE":
            cancel_enrollment(enr)
    for f in db.fraud_flags.values():
        if f["driver_id"] == d["id"] and f["status"] == "OPEN":
            f["status"] = "DISMISSED"
            touch(f)
    d["account_status"] = "DEACTIVATED"
    touch(d)
    return success_object(driver_view(d))


@bp.get("/drivers/<did>/enrollments")
@require_roles("PlatformAdmin", "IncentiveOps", "PaymentsOfficer", "Driver")
def list_driver_enrollments(did, _user_id, _role):
    d = get_driver_or_404(did)
    status = request.args.get("status")
    items = [e for e in db.enrollments.values() if e["driver_id"] == d["id"]]
    for e in items:
        touch_expiry("enrollment", e)
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([enrollment_view(e) for e in page], limit, offset, total)


@bp.get("/drivers/<did>/rides")
@require_roles(*ALL_READ)
def list_driver_rides(did, _user_id, _role):
    d = get_driver_or_404(did)
    status = request.args.get("status")
    items = [r for r in db.rides.values() if r["driver_id"] == d["id"]]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([ride_view(r) for r in page], limit, offset, total)


@bp.get("/drivers/<did>/settlements")
@require_roles("PlatformAdmin", "PaymentsOfficer", "Driver")
def list_driver_settlements(did, _user_id, _role):
    d = get_driver_or_404(did)
    status = request.args.get("status")
    items = [s for s in db.settlements.values() if s["driver_id"] == d["id"]]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([settlement_view(s) for s in page], limit, offset, total)


@bp.get("/drivers/<did>/statements")
@require_roles("PlatformAdmin", "PaymentsOfficer", "Driver")
def list_driver_statements(did, _user_id, _role):
    d = get_driver_or_404(did)
    status = request.args.get("status")
    items = [s for s in db.statements.values() if s["driver_id"] == d["id"]]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([statement_view(s) for s in page], limit, offset, total)
