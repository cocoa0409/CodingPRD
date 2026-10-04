"""Ride endpoints."""
from flask import Blueprint, request

import db
from errors import (
    err_cross_market_reference,
    err_geo_cell_unknown,
    err_invalid_request,
    err_invalid_state,
    err_ride_already_terminal,
    err_ride_not_completable,
    err_unauthorized,
)
from middleware import require_roles
from response import success_list, success_object
from services import (
    break_streaks,
    fold_accept_event,
    fold_decline_event,
    fold_driver_cancel_event,
    fold_offer_event,
    fraud_posture_recompute,
    get_driver_or_404,
    get_market_or_404,
    get_ride_or_404,
    maybe_fraud_posture_cascade,
    new_entity,
    paginate,
    parse_iso,
    process_ride_completion,
    require_enum,
    require_int,
    ride_view,
    ride_week,
    rolling_recompute,
    statement_recompute_for_week,
    touch,
    week_start_of,
    CANCELLED_BY,
    RIDE_TERMINAL,
    RIDE_TYPES,
)

bp = Blueprint("rides", __name__)

ALL_READ = ("PlatformAdmin", "IncentiveOps", "PaymentsOfficer", "FraudAnalyst", "Driver")


@bp.post("/rides")
@require_roles("Driver")
def create_ride(_user_id, _role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    driver_id = body.get("driver_id")
    if not isinstance(driver_id, str):
        raise err_invalid_request("driver_id is required")
    if driver_id != _user_id:
        raise err_unauthorized("Driver may only record rides as themselves")
    driver = get_driver_or_404(driver_id)
    market_id = body.get("market_id")
    if not isinstance(market_id, str):
        raise err_invalid_request("market_id is required")
    market = db.markets.get(market_id)
    if market is None:
        raise err_cross_market_reference("Ride market does not exist")
    ride_type = require_enum(body.get("ride_type"), "ride_type", RIDE_TYPES)
    geo_cell_id = body.get("geo_cell_id")
    if not isinstance(geo_cell_id, str):
        raise err_invalid_request("geo_cell_id is required")
    if geo_cell_id not in market["geo_cells"]:
        raise err_geo_cell_unknown()
    base_fare = require_int(body.get("base_fare_cents"), "base_fare_cents", minimum=0)
    tips = require_int(body.get("tips_cents"), "tips_cents", minimum=0)

    r = new_entity(
        {
            "driver_id": driver["id"],
            "market_id": market["id"],
            "ride_type": ride_type,
            "geo_cell_id": geo_cell_id,
            "base_fare_cents": base_fare,
            "tips_cents": tips,
            "request_offer_recorded": True,
            "status": "OFFERED",
            "qualifying_earnings_cents": 0,
            "completed_at": None,
        }
    )
    db.rides[r["id"]] = r
    fold_offer_event(driver)
    rolling_recompute(driver)
    return success_object(ride_view(r), 201)


@bp.get("/rides/<rid>")
@require_roles(*ALL_READ)
def get_ride(rid, _user_id, _role):
    r = get_ride_or_404(rid)
    return success_object(ride_view(r))


@bp.get("/rides")
@require_roles("PlatformAdmin", "IncentiveOps", "PaymentsOfficer", "FraudAnalyst")
def list_rides(_user_id, _role):
    items = list(db.rides.values())
    driver_id = request.args.get("driver_id")
    market_id = request.args.get("market_id")
    status = request.args.get("status")
    if driver_id is not None:
        items = [r for r in items if r["driver_id"] == driver_id]
    if market_id is not None:
        items = [r for r in items if r["market_id"] == market_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([ride_view(r) for r in page], limit, offset, total)


@bp.post("/rides/<rid>/accept")
@require_roles("Driver")
def accept_ride(rid, _user_id, _role):
    r = get_ride_or_404(rid)
    if r["driver_id"] != _user_id:
        raise err_unauthorized("Driver may only act on their own rides")
    if r["status"] in RIDE_TERMINAL:
        raise err_ride_already_terminal()
    if r["status"] != "OFFERED":
        raise err_invalid_state("Ride must be OFFERED to accept")
    driver = get_driver_or_404(r["driver_id"])
    if driver["account_status"] != "ACTIVE":
        raise err_invalid_state("Driver account is not ACTIVE")
    r["status"] = "ACCEPTED"
    touch(r)
    fold_accept_event(driver)
    return success_object(ride_view(r))


@bp.post("/rides/<rid>/decline")
@require_roles("Driver")
def decline_ride(rid, _user_id, _role):
    r = get_ride_or_404(rid)
    if r["driver_id"] != _user_id:
        raise err_unauthorized("Driver may only act on their own rides")
    if r["status"] in RIDE_TERMINAL:
        raise err_ride_already_terminal()
    if r["status"] != "OFFERED":
        raise err_invalid_state("Ride must be OFFERED to decline")
    r["status"] = "DECLINED"
    touch(r)
    driver = get_driver_or_404(r["driver_id"])
    fold_decline_event(driver)
    break_streaks(driver)
    return success_object(ride_view(r))


@bp.post("/rides/<rid>/complete")
@require_roles("Driver")
def complete_ride(rid, _user_id, _role):
    r = get_ride_or_404(rid)
    if r["driver_id"] != _user_id:
        raise err_unauthorized("Driver may only act on their own rides")
    if r["status"] in RIDE_TERMINAL:
        raise err_ride_already_terminal()
    if r["status"] != "ACCEPTED":
        raise err_ride_not_completable("Ride must be ACCEPTED to complete")
    driver = get_driver_or_404(r["driver_id"])
    process_ride_completion(r, driver)
    return success_object(ride_view(r))


@bp.post("/rides/<rid>/cancel")
@require_roles("Driver")
def cancel_ride(rid, _user_id, _role):
    r = get_ride_or_404(rid)
    if r["driver_id"] != _user_id:
        raise err_unauthorized("Driver may only act on their own rides")
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    cancelled_by = require_enum(body.get("cancelled_by"), "cancelled_by", CANCELLED_BY)
    if r["status"] in RIDE_TERMINAL:
        raise err_ride_already_terminal()
    if r["status"] != "ACCEPTED":
        raise err_invalid_state("Ride must be ACCEPTED to cancel")
    driver = get_driver_or_404(r["driver_id"])
    if cancelled_by == "DRIVER":
        r["status"] = "DRIVER_CANCELLED"
        touch(r)
        fold_driver_cancel_event(driver)
        break_streaks(driver)
    else:
        r["status"] = "RIDER_CANCELLED"
        touch(r)
    return success_object(ride_view(r))


def _reopen_finalized_settlements(driver_id, week_start):
    for s in db.settlements.values():
        if (
            s["driver_id"] == driver_id
            and s["status"] == "FINALIZED"
            and parse_iso(s["week_start_utc"]) == week_start
        ):
            s["status"] = "REOPENED"
            s["basis_variant"] = "PROVISIONAL"
            touch(s)


@bp.post("/rides/<rid>/flag-review")
@require_roles("FraudAnalyst")
def flag_review(rid, _user_id, _role):
    r = get_ride_or_404(rid)
    if r["status"] in RIDE_TERMINAL and r["status"] != "COMPLETED":
        raise err_ride_already_terminal()
    if r["status"] != "COMPLETED":
        raise err_ride_not_completable("Ride must be COMPLETED to flag for review")
    r["status"] = "UNDER_REVIEW"
    touch(r)
    wk = ride_week(r)
    if wk is not None:
        _reopen_finalized_settlements(r["driver_id"], wk)
    return success_object(ride_view(r))


@bp.post("/rides/<rid>/clear-review")
@require_roles("FraudAnalyst")
def clear_review(rid, _user_id, _role):
    r = get_ride_or_404(rid)
    if r["status"] != "UNDER_REVIEW":
        if r["status"] in RIDE_TERMINAL:
            raise err_ride_already_terminal()
        raise err_ride_not_completable("Ride must be UNDER_REVIEW to clear")
    r["status"] = "COMPLETED"
    touch(r)
    return success_object(ride_view(r))


@bp.post("/rides/<rid>/void")
@require_roles("FraudAnalyst")
def void_ride(rid, _user_id, _role):
    r = get_ride_or_404(rid)
    if r["status"] in RIDE_TERMINAL:
        raise err_ride_already_terminal()
    if r["status"] != "UNDER_REVIEW":
        raise err_ride_not_completable("Ride must be UNDER_REVIEW to void")
    has_confirmed = any(
        f for f in db.fraud_flags.values() if f["ride_id"] == r["id"] and f["status"] == "CONFIRMED"
    )
    if not has_confirmed:
        raise err_invalid_state("A CONFIRMED FraudFlag must exist for this ride")

    # compute clawback from ACTIVE zone enrollments before cancelling
    driver = get_driver_or_404(r["driver_id"])
    clawback = 0
    for enr in db.enrollments.values():
        if enr["driver_id"] != driver["id"] or enr["status"] != "ACTIVE":
            continue
        prog = db.programs.get(enr["program_id"])
        if (
            prog
            and prog["program_type"] == "BONUS_ZONE"
            and prog.get("geo_cell_id") == r["geo_cell_id"]
            and r["ride_type"] not in (prog.get("excluded_ride_types") or [])
        ):
            per_ride = (r["base_fare_cents"] * (prog["zone_multiplier_bps"] - 10000)) // 10000
            if per_ride > 0:
                enr["payout_cents"] = max(0, (enr.get("payout_cents") or 0) - per_ride)
                touch(enr)
                clawback += per_ride
    if clawback > 0:
        market = db.markets.get(r["market_id"])
        if market is not None:
            market["budget_spent_cents"] = max(0, market["budget_spent_cents"] - clawback)
            touch(market)

    r["status"] = "VOIDED"
    r["qualifying_earnings_cents"] = 0
    touch(r)

    wk = ride_week(r)
    if wk is not None and clawback > 0:
        for st in db.statements.values():
            if st["driver_id"] == driver["id"] and parse_iso(st["week_start_utc"]) == wk:
                st["adjustments_cents"] = st.get("adjustments_cents", 0) - clawback
                st["total_cents"] = (
                    st["base_fares_cents"]
                    + st["tips_cents_total"]
                    + st["bonus_total_cents"]
                    + st["make_up_total_cents"]
                    + st["adjustments_cents"]
                )
                touch(st)

    old, new = fraud_posture_recompute(driver)
    maybe_fraud_posture_cascade(driver, old, new)
    return success_object(ride_view(r))
