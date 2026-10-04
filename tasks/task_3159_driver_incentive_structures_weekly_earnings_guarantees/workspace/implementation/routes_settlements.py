"""GuaranteeSettlement endpoints."""
from flask import Blueprint, request

import db
from errors import (
    err_budget_exceeded,
    err_fraud_restricted,
    err_invalid_request,
    err_invalid_state,
    err_program_not_guarantee,
    err_settlement_already_paid,
    err_settlement_rides_pending,
)
from middleware import require_roles
from response import success_list, success_object
from services import (
    get_driver_or_404,
    get_market_or_404,
    get_program_or_404,
    get_settlement_or_404,
    iso_now,
    market_available,
    new_entity,
    paginate,
    parse_iso,
    ride_completed_in_week,
    settlement_compute_fields,
    settlement_view,
    statement_recompute_for_week,
    touch,
    week_start_of,
)

bp = Blueprint("settlements", __name__)


@bp.post("/settlements/compute")
@require_roles("PaymentsOfficer")
def compute_settlement(_user_id, _role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    driver_id = body.get("driver_id")
    if not isinstance(driver_id, str):
        raise err_invalid_request("driver_id is required")
    driver = get_driver_or_404(driver_id)
    program_id = body.get("program_id")
    if not isinstance(program_id, str):
        raise err_invalid_request("program_id is required")
    program = get_program_or_404(program_id)
    week_start_raw = body.get("week_start_utc")
    if not isinstance(week_start_raw, str):
        raise err_invalid_request("week_start_utc is required")
    week_start = parse_iso(week_start_raw, "week_start_utc")

    if program["program_type"] != "GUARANTEE":
        raise err_program_not_guarantee()

    promised, actual, count, make_up = settlement_compute_fields(
        driver, program, week_start, "PROVISIONAL"
    )
    s = new_entity(
        {
            "driver_id": driver["id"],
            "program_id": program["id"],
            "week_start_utc": week_start.strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"
            if week_start.microsecond == 0
            else week_start.isoformat(),
            "promised_cents": promised,
            "actual_gross_cents": actual,
            "qualifying_ride_count": count,
            "make_up_cents": make_up,
            "basis_variant": "PROVISIONAL",
            "status": "DRAFT",
            "paid_at_utc": None,
        }
    )
    db.settlements[s["id"]] = s
    return success_object(settlement_view(s), 201)


@bp.get("/settlements/<sid>")
@require_roles("PlatformAdmin", "PaymentsOfficer", "Driver")
def get_settlement(sid, _user_id, _role):
    s = get_settlement_or_404(sid)
    return success_object(settlement_view(s))


@bp.get("/settlements")
@require_roles("PlatformAdmin", "PaymentsOfficer")
def list_settlements(_user_id, _role):
    items = list(db.settlements.values())
    driver_id = request.args.get("driver_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if driver_id is not None:
        items = [s for s in items if s["driver_id"] == driver_id]
    if program_id is not None:
        items = [s for s in items if s["program_id"] == program_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([settlement_view(s) for s in page], limit, offset, total)


@bp.post("/settlements/<sid>/finalize")
@require_roles("PaymentsOfficer")
def finalize_settlement(sid, _user_id, _role):
    s = get_settlement_or_404(sid)
    if s["status"] not in ("DRAFT", "REOPENED"):
        raise err_invalid_state("Settlement must be DRAFT or REOPENED to finalize")
    driver = get_driver_or_404(s["driver_id"])
    # fraud gate (priority 4)
    if driver["fraud_posture"] == "RESTRICTED":
        raise err_fraud_restricted()
    program = get_program_or_404(s["program_id"])
    week_start = parse_iso(s["week_start_utc"])
    # all week rides terminal (no UNDER_REVIEW)
    for r in db.rides.values():
        if r["driver_id"] != driver["id"]:
            continue
        if r["status"] == "UNDER_REVIEW" and ride_completed_in_week(r, week_start):
            raise err_settlement_rides_pending()
    promised, actual, count, make_up = settlement_compute_fields(driver, program, week_start, "FINAL")
    s["promised_cents"] = promised
    s["actual_gross_cents"] = actual
    s["qualifying_ride_count"] = count
    s["make_up_cents"] = make_up
    s["basis_variant"] = "FINAL"
    s["status"] = "FINALIZED"
    touch(s)
    return success_object(settlement_view(s))


@bp.post("/settlements/<sid>/pay")
@require_roles("PaymentsOfficer")
def pay_settlement(sid, _user_id, _role):
    s = get_settlement_or_404(sid)
    if s["status"] != "FINALIZED":
        raise err_invalid_state("Settlement must be FINALIZED to pay")
    program = get_program_or_404(s["program_id"])
    market = get_market_or_404(program["market_id"])
    if market_available(market) < s["make_up_cents"]:
        raise err_budget_exceeded("Make-up exceeds available budget")
    market["budget_spent_cents"] += s["make_up_cents"]
    touch(market)
    s["status"] = "PAID"
    s["paid_at_utc"] = iso_now()
    touch(s)
    week_start = parse_iso(s["week_start_utc"])
    statement_recompute_for_week(s["driver_id"], week_start)
    return success_object(settlement_view(s))


@bp.post("/settlements/<sid>/reopen")
@require_roles("PaymentsOfficer")
def reopen_settlement(sid, _user_id, _role):
    s = get_settlement_or_404(sid)
    if s["status"] == "PAID":
        raise err_settlement_already_paid()
    if s["status"] != "FINALIZED":
        raise err_invalid_state("Settlement must be FINALIZED to reopen")
    s["status"] = "REOPENED"
    s["basis_variant"] = "PROVISIONAL"
    touch(s)
    return success_object(settlement_view(s))


@bp.post("/settlements/<sid>/void")
@require_roles("PaymentsOfficer")
def void_settlement(sid, _user_id, _role):
    s = get_settlement_or_404(sid)
    if s["status"] == "PAID":
        raise err_settlement_already_paid()
    if s["status"] not in ("DRAFT", "FINALIZED", "REOPENED"):
        raise err_invalid_state("Settlement cannot be voided from its current state")
    s["status"] = "VOID"
    touch(s)
    return success_object(settlement_view(s))
