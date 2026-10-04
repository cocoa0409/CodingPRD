"""GuestCheck endpoints: open, edit, finalize, tip, settle, void."""

from flask import Blueprint, request

import calculations as calc
import db
import middleware as mw
import response as resp
import serializers as ser
from errors import ApiError

bp = Blueprint("guest_checks", __name__)

CHECK_READ_ROLES = ["PlatformAdmin", "BoutiqueManager", "RetailLead", "Server", "Cashier"]


def _recompute_day_after_check_change(day):
    calc.recompute_store_day_retail_metrics(day)
    calc.recompute_store_day_transaction_count(day)
    calc.recompute_conversion_index(day)
    db.touch(day)


@bp.post("/retail-ops/guest-checks")
def create_check():
    ctx = mw.context()
    mw.require_role(ctx, ["Server"])
    data = mw.body()

    location_id = mw.required(data, "location_id")
    location_rec = db.get_or_404(db.locations, location_id, "ERR_LOCATION_NOT_FOUND")
    store_day_id = mw.required(data, "store_day_id")
    db.get_or_404(db.store_days, store_day_id, "ERR_STORE_DAY_NOT_FOUND")

    guest_count = mw.required(data, "restaurant_guest_count", int)
    if guest_count < 1:
        raise ApiError("ERR_INVALID_REQUEST", "restaurant_guest_count must be at least 1.")
    subtotal = mw.required(data, "restaurant_subtotal_cents", int)
    if subtotal < 0:
        raise ApiError("ERR_INVALID_REQUEST", "restaurant_subtotal_cents must not be negative.")

    rec = db.new_record({
        "location_id": location_rec["id"],
        "store_day_id": store_day_id,
        "table_number": mw.required(data, "table_number"),
        "restaurant_guest_count": guest_count,
        "restaurant_subtotal_cents": subtotal,
        "retail_subtotal_cents": 0,
        "service_fee_cents": 0,
        "total_cents": 0,
        "check_status": "PENDING",
        "settlement_status": "UNSETTLED",
        "presented_shift_id": mw.required(data, "presented_shift_id"),
        "tip_cents": 0,
        "tip_eligible": False,
        "tip_pct": 0.0,
    })
    calc.recompute_check(rec)
    calc.recompute_check_tip_eligibility(rec)
    db.guest_checks[rec["id"]] = rec
    return resp.ok(ser.guest_check(rec), 201)


@bp.get("/retail-ops/guest-checks")
def list_checks():
    ctx = mw.context()
    mw.require_role(ctx, CHECK_READ_ROLES)
    records = resp.order_records([r for r in db.guest_checks.values() if mw.matches(r, {
        "location_id": mw.query_str("location_id"),
        "store_day_id": mw.query_str("store_day_id"),
        "presented_shift_id": mw.query_str("presented_shift_id"),
        "check_status": mw.query_str("check_status"),
        "tip_eligible": mw.query_bool("tip_eligible"),
    })])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.guest_check(r) for r in page], pagination=pagination)


@bp.get("/retail-ops/guest-checks/<check_id>")
def get_check(check_id):
    ctx = mw.context()
    mw.require_role(ctx, CHECK_READ_ROLES)
    rec = db.get_or_404(db.guest_checks, check_id, "ERR_CHECK_NOT_FOUND")
    return resp.ok(ser.guest_check(rec))


@bp.put("/retail-ops/guest-checks/<check_id>")
def edit_check(check_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager", "Cashier"])
    rec = db.get_or_404(db.guest_checks, check_id, "ERR_CHECK_NOT_FOUND")
    data = mw.body()

    if rec.get("check_status") != "PENDING":
        raise ApiError("ERR_INVALID_STATE")

    guest_count = mw.optional(data, "restaurant_guest_count", None, int)
    if guest_count is not None:
        if guest_count < 1:
            raise ApiError("ERR_INVALID_REQUEST", "restaurant_guest_count must be at least 1.")
        rec["restaurant_guest_count"] = guest_count
    subtotal = mw.optional(data, "restaurant_subtotal_cents", None, int)
    if subtotal is not None:
        if subtotal < 0:
            raise ApiError("ERR_INVALID_REQUEST", "restaurant_subtotal_cents must not be negative.")
        rec["restaurant_subtotal_cents"] = subtotal

    calc.recompute_check(rec)
    calc.recompute_check_tip_fields(rec)
    db.touch(rec)
    return resp.ok(ser.guest_check(rec))


@bp.post("/retail-ops/guest-checks/<check_id>/finalize")
def finalize_check(check_id):
    ctx = mw.context()
    mw.require_role(ctx, ["Cashier"])
    rec = db.get_or_404(db.guest_checks, check_id, "ERR_CHECK_NOT_FOUND")

    if rec.get("check_status") in {"FINALIZED", "VOIDED"}:
        # PRD 3.2: "A check that has already reached FINALIZED or VOIDED will not
        # accept a further retail line; an attempt to attach one is refused with
        # ERR_CHECK_ALREADY_FINALIZED".  Re-finalizing an already-finalized check
        # is the same terminal-state refusal and reports the same identifier.
        raise ApiError("ERR_CHECK_ALREADY_FINALIZED")
    if rec.get("check_status") != "PENDING":
        raise ApiError("ERR_INVALID_STATE")

    calc.recompute_check(rec)
    calc.recompute_check_tip_fields(rec)
    rec["check_status"] = "FINALIZED"
    calc.recompute_check_tip_eligibility(rec)
    db.touch(rec)

    day = db.store_days.get(rec.get("store_day_id"))
    if day is not None:
        calc.recompute_conversion_index(day)
        db.touch(day)
    return resp.ok(ser.guest_check(rec))


@bp.post("/retail-ops/guest-checks/<check_id>/tips")
def post_tip(check_id):
    ctx = mw.context()
    mw.require_role(ctx, ["Cashier", "Server"])
    rec = db.get_or_404(db.guest_checks, check_id, "ERR_CHECK_NOT_FOUND")
    data = mw.body()

    tip = mw.required(data, "tip_cents", int)
    if tip < 0:
        raise ApiError("ERR_INVALID_REQUEST", "tip_cents must not be negative.")

    # Priority 16 — the combined-check ceiling.  It is declared over the check's
    # total, and the tip is part of that total, so a tip that would carry the
    # check past the brand's cap is refused here and the tip is left unwritten.
    brand_rec = calc.brand_of_store_day(db.store_days.get(rec.get("store_day_id")))
    if brand_rec is not None:
        previous_tip = rec.get("tip_cents", 0) or 0
        rec["tip_cents"] = tip
        calc.recompute_check(rec)
        if rec.get("total_cents", 0) > brand_rec.get("max_check_total_cents", 50000):
            rec["tip_cents"] = previous_tip
            calc.recompute_check(rec)
            raise ApiError("ERR_CHECK_TOTAL_EXCEEDED")
    else:
        rec["tip_cents"] = tip
        calc.recompute_check(rec)

    calc.recompute_check_tip_fields(rec)
    db.touch(rec)
    return resp.ok(ser.guest_check(rec))


@bp.post("/retail-ops/guest-checks/<check_id>/settle")
def settle_check(check_id):
    ctx = mw.context()
    mw.require_role(ctx, ["Cashier"])
    rec = db.get_or_404(db.guest_checks, check_id, "ERR_CHECK_NOT_FOUND")
    data = mw.body()

    if rec.get("settlement_status") != "UNSETTLED":
        raise ApiError("ERR_INVALID_STATE")

    payment_method = mw.required(data, "payment_method")
    if payment_method not in {"CASH", "CARD", "GIFT_CARD", "SPLIT"}:
        raise ApiError("ERR_INVALID_REQUEST", "payment_method is not a declared tender.")
    basis = mw.optional(data, "restaurant_share_basis", None)
    if basis is not None and basis not in {"CHECK_TOTAL", "ALLOCATED"}:
        raise ApiError("ERR_INVALID_REQUEST", "restaurant_share_basis is not a declared basis.")

    rec["_restaurant_share_basis"] = basis
    rec["settlement_status"] = "SETTLED"
    db.touch(rec)
    return resp.ok(ser.guest_check(rec))


@bp.post("/retail-ops/guest-checks/<check_id>/void")
def void_check(check_id):
    ctx = mw.context()
    mw.require_role(ctx, ["BoutiqueManager"])
    rec = db.get_or_404(db.guest_checks, check_id, "ERR_CHECK_NOT_FOUND")

    if rec.get("check_status") == "VOIDED":
        raise ApiError("ERR_INVALID_STATE")

    rec["check_status"] = "VOIDED"
    for receipt in db.receipts.values():
        if receipt.get("guest_check_id") != rec["id"]:
            continue
        if receipt.get("status") in {"RECONCILED", "SETTLED"}:
            receipt["status"] = "DISPUTED"
            receipt["reversal_posted_at"] = db.fmt_ts(db.now())
            db.touch(receipt)

    db.touch(rec)

    day = db.store_days.get(rec.get("store_day_id"))
    if day is not None:
        brand_rec = calc.brand_of_store_day(day)
        if brand_rec is not None:
            calc.recompute_brand_revenue(brand_rec)
            db.touch(brand_rec)
        _recompute_day_after_check_change(day)

    return resp.ok(ser.guest_check(rec))