"""StaffShift endpoints: schedule, start, complete, revert, cancel."""

from flask import Blueprint, request

import calculations as calc
import db
import middleware as mw
import response as resp
import serializers as ser
from errors import ApiError

bp = Blueprint("staff_shifts", __name__)

SHIFT_READ_ROLES = ["PlatformAdmin", "BoutiqueManager", "RetailLead", "Cashier", "Server"]
WORKCODES = {"SERVER", "COOK", "CASHIER", "RETAIL_STOCK", "RETAIL_CASHIER", "RETAIL_GIFT"}

RESTAURANT_POOL = {"SERVER", "CASHIER"}
RETAIL_POOL = {"RETAIL_STOCK", "RETAIL_CASHIER", "RETAIL_GIFT"}
RESTAURANT_WORKCODES = {"SERVER", "COOK", "CASHIER"}


def _interval_seconds(start, end):
    return (end - start).total_seconds()


def _overlaps(shift, start, end):
    existing_start = db.parse_ts(shift.get("start_utc"), "start_utc")
    existing_end = db.parse_ts(shift.get("end_utc"), "end_utc")
    # Half-open [start, end): touching at a single instant is permitted.
    return start < existing_end and existing_start < end


@bp.post("/retail-ops/staff-shifts")
def create_shift():
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    data = mw.body()

    location_id = mw.required(data, "location_id")
    location_rec = db.get_or_404(db.locations, location_id, "ERR_LOCATION_NOT_FOUND")

    start = db.parse_ts(mw.required(data, "start_utc"), "start_utc")
    end = db.parse_ts(mw.required(data, "end_utc"), "end_utc")
    if _interval_seconds(start, end) < 0:
        raise ApiError("ERR_INVALID_REQUEST", "end_utc must be at or after start_utc.")

    workcode = mw.required(data, "workcode")
    if workcode not in WORKCODES:
        raise ApiError("ERR_INVALID_REQUEST", "workcode is not a declared workcode.")
    tip_claim = mw.optional(data, "tip_eligible_claim", False, bool)
    crossover_id = mw.optional(data, "crossover_authorized_by_shift_id", None)

    brand_rec = calc.brand_of_location(location_rec)
    minimum = brand_rec.get("tip_minimum_minutes", 240) if brand_rec else 240

    # Priority 18 — a claim asserted against a front-of-house retail workcode.
    if tip_claim and workcode not in calc.TIP_ELIGIBLE_WORKCODES:
        raise ApiError("ERR_TIP_INELIGIBLE_WORKCODE")

    # Priority 19 — the (location_id, employee_id) overlap rule.
    employee_id = mw.required(data, "employee_id")
    for other in db.staff_shifts.values():
        if other.get("location_id") != location_rec["id"] or other.get("employee_id") != employee_id:
            continue
        if other.get("status") in {"COMPLETED", "CANCELLED"}:
            continue
        if _overlaps(other, start, end):
            raise ApiError("ERR_SHIFT_OVERLAP")

    # Priority 20 — the crossover-authorization rule.  The authorizing
    # reference is a real StaffShift record and it is the only thing that makes
    # a cross-pool shift legitimate, so it must name a shift in progress.
    if crossover_id is not None:
        authorizer = db.get_or_404(db.staff_shifts, crossover_id, "ERR_SHIFT_NOT_FOUND")
        if authorizer.get("status") != "IN_PROGRESS":
            raise ApiError("ERR_CROSSOVER_NOT_AUTHORIZED")

    # Priority 26 — a claim that cannot reach the minute bar.
    if tip_claim:
        provisional = {"start_utc": db.fmt_ts(start), "end_utc": db.fmt_ts(end),
                       "workcode": workcode, "location_id": location_rec["id"]}
        if calc.shift_minutes(provisional) < minimum:
            raise ApiError("ERR_TIP_SHIFT_TOO_SHORT")

    rec = db.new_record({
        "location_id": location_rec["id"],
        "employee_id": employee_id,
        "start_utc": db.fmt_ts(start),
        "end_utc": db.fmt_ts(end),
        "workcode": workcode,
        "tip_eligible_claim": tip_claim,
        "tip_eligible": False,
        "tip_eligible_minutes": 0,
        "status": "SCHEDULED",
        "crossover_authorized_by_shift_id": crossover_id,
        "completed_at": None,
    })
    db.staff_shifts[rec["id"]] = rec
    return resp.ok(ser.staff_shift(rec), 201)


@bp.get("/retail-ops/staff-shifts")
def list_shifts():
    ctx = mw.context()
    mw.require_role(ctx, SHIFT_READ_ROLES)
    records = resp.order_records([r for r in db.staff_shifts.values() if mw.matches(r, {
        "location_id": mw.query_str("location_id"),
        "employee_id": mw.query_str("employee_id"),
        "workcode": mw.query_str("workcode"),
        "status": mw.query_str("status"),
        "tip_eligible": mw.query_bool("tip_eligible"),
        "crossover_authorized_by_shift_id": mw.query_str("crossover_authorized_by_shift_id"),
    })])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.staff_shift(r) for r in page], pagination=pagination)


@bp.get("/retail-ops/staff-shifts/<shift_id>")
def get_shift(shift_id):
    ctx = mw.context()
    mw.require_role(ctx, SHIFT_READ_ROLES)
    rec = db.get_or_404(db.staff_shifts, shift_id, "ERR_SHIFT_NOT_FOUND")
    return resp.ok(ser.staff_shift(rec))


@bp.post("/retail-ops/staff-shifts/<shift_id>/start")
def start_shift(shift_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.staff_shifts, shift_id, "ERR_SHIFT_NOT_FOUND")

    if rec.get("status") != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    if db.now() < db.parse_ts(rec.get("start_utc"), "start_utc"):
        raise ApiError("ERR_INVALID_STATE")

    # Priority 18 also guards this endpoint.
    if rec.get("tip_eligible_claim") and rec.get("workcode") not in calc.TIP_ELIGIBLE_WORKCODES:
        raise ApiError("ERR_TIP_INELIGIBLE_WORKCODE")

    day = calc.shift_store_day(rec)
    if day is not None and day.get("conversion_gate") == "SUSPENDED":
        raise ApiError("ERR_STORE_DAY_GATE_SUSPENDED")

    rec["status"] = "IN_PROGRESS"
    calc.derive_tip_eligibility(rec)
    calc.recompute_presented_checks(rec)
    db.touch(rec)

    _refresh_shift_day(rec)
    return resp.ok(ser.staff_shift(rec))


@bp.post("/retail-ops/staff-shifts/<shift_id>/complete")
def complete_shift(shift_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.staff_shifts, shift_id, "ERR_SHIFT_NOT_FOUND")

    if rec.get("status") != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")

    if db.now() < db.parse_ts(rec.get("start_utc"), "start_utc"):
        raise ApiError("ERR_INVALID_STATE")

    rec["status"] = "COMPLETED"
    rec["completed_at"] = db.fmt_ts(db.now())
    calc.derive_tip_eligibility(rec)
    calc.recompute_presented_checks(rec)
    db.touch(rec)

    _refresh_shift_day(rec)
    return resp.ok(ser.staff_shift(rec))


def _refresh_shift_day(rec):
    day = calc.shift_store_day(rec)
    if day is not None:
        calc.recompute_conversion_index(day)
        db.touch(day)


@bp.post("/retail-ops/staff-shifts/<shift_id>/revert-to-scheduled")
def revert_shift(shift_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.staff_shifts, shift_id, "ERR_SHIFT_NOT_FOUND")

    if rec.get("status") != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")

    location_rec = db.locations.get(rec.get("location_id"))
    brand_rec = calc.brand_of_location(location_rec)
    grace = brand_rec.get("open_receipt_grace_hours", 24) if brand_rec else 24
    end = db.parse_ts(rec.get("end_utc"), "end_utc")
    if db.now() > db.plus_hours(end, grace):
        raise ApiError("ERR_INVALID_STATE")

    rec["status"] = "SCHEDULED"
    rec["tip_eligible"] = False
    rec["tip_eligible_minutes"] = 0
    for check in db.guest_checks.values():
        if check.get("presented_shift_id") != rec["id"]:
            continue
        if check.get("check_status") == "FINALIZED":
            calc.recompute_check_tip_eligibility(check)
    db.touch(rec)

    _refresh_shift_day(rec)
    return resp.ok(ser.staff_shift(rec))


@bp.post("/retail-ops/staff-shifts/<shift_id>/cancel")
def cancel_shift(shift_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.staff_shifts, shift_id, "ERR_SHIFT_NOT_FOUND")

    if rec.get("status") != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    location_rec = db.locations.get(rec.get("location_id"))
    brand_rec = calc.brand_of_location(location_rec)
    fiscal_open = (brand_rec.get("fiscal_period_status", "OPEN") == "OPEN") if brand_rec else True

    if rec.get("tip_eligible_claim") and not fiscal_open:
        raise ApiError("ERR_INVALID_STATE")

    rec["status"] = "CANCELLED"
    for check in db.guest_checks.values():
        if check.get("presented_shift_id") != rec["id"]:
            continue
        if check.get("check_status") == "FINALIZED":
            check["tip_eligible"] = False
    db.touch(rec)

    _refresh_shift_day(rec)
    return resp.ok(ser.staff_shift(rec))