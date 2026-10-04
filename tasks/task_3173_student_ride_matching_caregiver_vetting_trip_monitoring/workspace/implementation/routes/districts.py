"""District endpoints: onboarding, reverse-reachability lists, billing runs,
supply planning, availability blocks and credit adjustments.
"""

import calculations as calc
import db
import models
import validators as v
from clock import clock_date, fmt_date, parse_date, stamp
from decimal import Decimal
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CONTRACT_OVERLAP,
    ERR_DISTRICT_OVER_LIMIT,
    ERR_DRIVER_WINDOW_OVERLAP,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_PERIOD_MISMATCH,
    ERR_STALE_VERSION,
    ApiError,
    not_found,
)
from flask import Blueprint, request
from middleware import requires
from response import array_response, object_response, paginate

bp = Blueprint("districts", __name__)

DISTRICT_INPUT = (
    "name", "billing_email", "contract_rate_per_ride_cents", "contract_rate_per_mile_cents",
    "minimum_billable_cents", "no_school_dates", "bell_schedule_start",
    "support_center_alert_enabled",
)


def load_district(district_id):
    district = db.get("districts", district_id)
    if district is None:
        raise not_found("The addressed district does not exist.")
    return district


def check_stale(district, payload):
    """Optimistic concurrency: expected_district_version (SCAFFOLD section 1.2.1)."""
    expected = payload.get("expected_district_version")
    if expected is None:
        raise ApiError(ERR_INVALID_REQUEST, "expected_district_version is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_district_version must be an integer.")
    if expected != district["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_district_version does not match the district's current version.",
        )


@bp.post("/student-rides/districts")
def create_district():
    """The only unauthenticated endpoint (PRD section 2.1)."""
    data = v.body()
    v.reject_unknown(data, DISTRICT_INPUT)
    no_school_dates = v.as_array(data, "no_school_dates", default=[]) or []
    for d in no_school_dates:
        try:
            parse_date(d)
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, "no_school_dates must be ISO date strings.")

    district = db.new_record({
        "name": v.as_string(data, "name"),
        "billing_email": v.as_string(data, "billing_email"),
        "contract_rate_per_ride_cents": v.as_int(data, "contract_rate_per_ride_cents", required_field=True),
        "contract_rate_per_mile_cents": v.as_int(data, "contract_rate_per_mile_cents", required_field=True),
        "minimum_billable_cents": v.as_int(data, "minimum_billable_cents", default=0),
        "no_school_dates": [str(d) for d in no_school_dates],
        "bell_schedule_start": v.as_string(data, "bell_schedule_start", required_field=False),
        "support_center_alert_enabled": v.as_bool(data, "support_center_alert_enabled", default=True),
        "outstanding_balance_cents": 0,
        "credit_balance_cents": 0,
        "account_status": "ACTIVE",
        "trips_scheduled_total": 0,
    })
    db.save("districts", district)
    return object_response(models.district_out(district), 201)


@bp.get("/student-rides/districts/<district_id>")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def get_district(district_id):
    district = load_district(district_id)
    return object_response(models.district_out(district))


def _list_children(district_id, coll, filter_fn=None):
    load_district(district_id)
    rows = [r for r in db.all_of(coll) if filter_fn(r)]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all(coll, page), limit, offset, total)


@bp.get("/student-rides/districts/<district_id>/riders")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_district_riders(district_id):
    return _list_children(district_id, "riders", lambda r: r["district_id"] == district_id)


@bp.get("/student-rides/districts/<district_id>/ride-requests")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_district_ride_requests(district_id):
    return _list_children(district_id, "ride_requests", lambda r: r["district_id"] == district_id)


@bp.get("/student-rides/districts/<district_id>/contracts")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_district_contracts(district_id):
    return _list_children(district_id, "contracts", lambda r: r["district_id"] == district_id)


@bp.get("/student-rides/districts/<district_id>/trips")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_district_trips(district_id):
    return _list_children(district_id, "trips", lambda r: r["district_id"] == district_id)


@bp.get("/student-rides/districts/<district_id>/billing-statements")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_district_statements(district_id):
    return _list_children(district_id, "billing_statements", lambda r: r["district_id"] == district_id)


@bp.get("/student-rides/districts/<district_id>/geofences")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_district_geofences(district_id):
    return _list_children(district_id, "geofences", lambda r: r["district_id"] == district_id)


# --- Billing runs -----------------------------------------------------------

BILLING_RUN_INPUT = ("expected_district_version", "period_key", "period_start", "period_end")


@bp.post("/student-rides/districts/<district_id>/billing-runs")
@requires("DistrictAdmin", "PlatformAdmin")
def create_billing_run(district_id):
    district = load_district(district_id)
    data = v.body()
    v.reject_unknown(data, BILLING_RUN_INPUT)
    check_stale(district, data)
    period_key = v.as_string(data, "period_key")
    period_start = v.as_iso_date_string(data, "period_start")
    period_end = v.as_iso_date_string(data, "period_end")

    # Automatic contract expiry runs during a billing run (PRD section 3.10).
    calc.expire_overdue_contracts(district)

    contract = calc.covering_contract(district_id)
    if contract is None:
        raise ApiError(ERR_FORBIDDEN, "The district has no ACTIVE contract to bill under.")

    included = [
        t for t in db.all_of("trips")
        if t["district_id"] == district_id
        and t["trip_state"] == "COMPLETED"
        and t.get("billing_period_key") == period_key
        and period_start <= t["scheduled_date"] <= period_end
    ]
    # Pinned accumulation order: scheduled_date ASC, completed_at ASC,
    # created_at ASC (PRD section 3.10).
    included.sort(key=lambda t: (t["scheduled_date"], t.get("completed_at") or "", t["created_at"]))

    gross_total = 0
    total_ride_units = 0
    total_miles = Decimal("0")
    for trip in included:
        gross_total += calc.trip_charge_final_cents(trip, contract)
        total_ride_units += int(trip.get("billable_ride_units") or 0)
        total_miles += Decimal(str(trip.get("billable_miles") or 0))

    credit_available = int(district.get("credit_balance_cents") or 0)
    credit_cap = calc.round_half_up(Decimal(gross_total) * calc.CREDIT_APPLY_PCT)
    applied_credit = min(credit_available, credit_cap)
    total_amount = gross_total - applied_credit

    statement = db.new_record({
        "district_id": district_id,
        "contract_id": contract["id"],
        "period_key": period_key,
        "period_start": period_start,
        "period_end": period_end,
        "total_ride_units": total_ride_units,
        "total_miles": total_miles,
        "total_amount_cents": int(total_amount),
        "applied_credit_cents": int(applied_credit),
        "issued_at": None,
        "status": "OPEN",
    })
    db.save("billing_statements", statement)

    # The applied credit is reserved out of the pool at computation time.
    district["credit_balance_cents"] = credit_available - applied_credit
    db.touch(district)
    return object_response(models.billing_statement_out(statement), 201)


# --- Supply planning --------------------------------------------------------

@bp.get("/student-rides/districts/<district_id>/supply-plans")
@requires("DistrictAdmin", "PlatformAdmin")
def read_supply_plan(district_id):
    load_district(district_id)
    horizon_start = request.args.get("horizon_start")
    horizon_end = request.args.get("horizon_end")
    if not horizon_start or not horizon_end:
        raise ApiError(ERR_INVALID_REQUEST, "horizon_start and horizon_end are required.")
    try:
        start = parse_date(horizon_start)
        end = parse_date(horizon_end)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "horizon_start and horizon_end must be ISO dates.")
    seated_only = request.args.get("seated_demand_only") in ("true", "1", "True")
    plan = calc.supply_plan(district_id, start, end, seated_demand_only=seated_only)
    plan.pop("underdogs_placeholder", None)
    return object_response(plan)


DRIVER_BLOCK_INPUT = ("driver_id", "block_start_at", "block_end_at", "reason")


@bp.post("/student-rides/districts/<district_id>/driver-availability-blocks")
@requires("DistrictAdmin", "PlatformAdmin")
def create_availability_block(district_id):
    load_district(district_id)
    data = v.body()
    v.reject_unknown(data, DRIVER_BLOCK_INPUT)
    driver_id = v.as_string(data, "driver_id")
    driver = db.get("drivers", driver_id)
    if driver is None:
        raise not_found("The referenced driver does not exist.")
    block_start = v.as_iso_dt(data, "block_start_at")
    block_end = v.as_iso_dt(data, "block_end_at")
    reason = v.as_string(data, "reason", required_field=False)

    # Half-open semantics for availability blocking (PRD section 2.6): "a window
    # that begins exactly at another window's close is accepted and a gap of
    # zero minutes is permitted", so the block/trip boundary pair is compared
    # without the route-segment safety buffer. The twenty-minute buffer is a
    # route-segment planning allowance, not a widening of the collision window.
    affected = []
    for trip in db.all_of("trips"):
        if trip.get("driver_id") != driver_id:
            continue
        if trip["trip_state"] in ("COMPLETED", "CANCELLED"):
            continue
        w_start = trip.get("window_start_at_dt")
        w_end = trip.get("window_end_at_dt")
        if w_start is None or w_end is None:
            continue
        if calc.half_open_overlap(block_start, block_end, w_start, w_end):
            raise ApiError(
                ERR_DRIVER_WINDOW_OVERLAP,
                "The availability block overlaps a trip window already assigned to that driver.",
            )
        # A surviving trip is disjoint from the block, so no ride request is
        # affected by it.

    db.STORE.driver_blocks.append({
        "district_id": district_id,
        "driver_id": driver_id,
        "block_start_at": block_start,
        "block_end_at": block_end,
        "reason": reason,
    })

    rows = []
    seen = set()
    for rr_id in affected:
        if rr_id in seen:
            continue
        rr = db.get("ride_requests", rr_id)
        if rr:
            seen.add(rr_id)
            rows.append(models.ride_request_out(rr))
    return array_response(
        models.serialise_all("ride_requests", [db.get("ride_requests", i) for i in seen if db.get("ride_requests", i)]),
        status=201,
    )


DRIVER_SUPPLY_RUN_INPUT = ("horizon_start", "horizon_end")


@bp.post("/student-rides/districts/<district_id>/driver-supply-runs")
@requires("DistrictAdmin", "PlatformAdmin")
def create_driver_supply_run(district_id):
    load_district(district_id)
    data = v.body()
    v.reject_unknown(data, DRIVER_SUPPLY_RUN_INPUT)
    start = v.as_iso_date_string(data, "horizon_start")
    end = v.as_iso_date_string(data, "horizon_end")
    rows = [
        t for t in db.all_of("trips")
        if t["district_id"] == district_id and start <= t["scheduled_date"] <= end
    ]
    rows.sort(key=lambda t: t["created_at"])
    return array_response(models.serialise_all("trips", rows))


CREDIT_ADJUSTMENT_INPUT = ("amount_cents", "reason")


@bp.post("/student-rides/districts/<district_id>/credit-adjustments")
@requires("DistrictAdmin", "PlatformAdmin")
def create_credit_adjustment(district_id):
    district = load_district(district_id)
    data = v.body()
    v.reject_unknown(data, CREDIT_ADJUSTMENT_INPUT)
    amount = v.as_int(data, "amount_cents", required_field=True)
    v.as_string(data, "reason", required_field=False)
    district["credit_balance_cents"] = int(district.get("credit_balance_cents") or 0) + amount
    db.touch(district)
    return object_response(models.district_out(district))