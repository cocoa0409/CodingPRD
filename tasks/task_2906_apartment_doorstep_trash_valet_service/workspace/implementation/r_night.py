"""ServiceNight endpoints (PRD s3.4, s3.5 close)."""

from datetime import timedelta

from flask import Blueprint

import shape
from authz import admit, contract_of_night, get_contract, get_night
from calc import (
    expected_door_count,
    nights_of_contract,
    recompute_assigned_unit_coverage,
    recompute_night_counters,
    routes_of_night,
    select_verification_outcome,
)
from envelope import array_response, object_response
from errors import ApiError
from rollups import cancel_night
from serializers import night_out
from shape import pagination, paginate, q
from store import (
    MAKEUP_WINDOW_DAYS,
    OPEN_ROUTE_STATUSES,
    db,
    iso,
    parse_date,
    parse_instant,
    sort_rows,
    stamp_new,
    touch,
    weekday_name,
)

bp = Blueprint("night", __name__)

TERMINAL_NIGHT = ("VERIFIED", "PARTIAL", "MISSED", "CANCELLED")
RESCHEDULE_ROUTE_STATUSES = ("ASSIGNED", "ACCEPTED")


def _new_night(contract, service_date_text, window_start, window_end, seasonal, holiday,
               rescheduled_from_night_id=None):
    row = {
        "contract_id": contract["id"],
        "rescheduled_from_night_id": rescheduled_from_night_id,
        "service_date": service_date_text,
        "service_window_start": iso(window_start),
        "service_window_end": iso(window_end),
        "seasonal_volume_index": seasonal,
        "holiday_flag": holiday,
        "verification_status": "SCHEDULED",
        "billing_status": "UNBILLED",
        "expected_door_count": 0,
        "scanned_door_count": 0,
        "coverage_bps": 0,
        "assigned_unit_coverage_count": 0,
        "reschedule_action": None,
    }
    stamp_new(row)
    db.nights[row["id"]] = row
    row["expected_door_count"] = expected_door_count(row)
    return row


@bp.route("/valet/contracts/<contract_id>/service-nights", methods=["POST"])
def create_night(contract_id):
    admit(("PlatformAdmin", "ValetOpsManager"))
    contract = get_contract(contract_id)
    body = shape.body()
    service_date = shape.req_date(body, "service_date")
    window_start = shape.req_instant(body, "service_window_start")
    window_end = shape.req_instant(body, "service_window_end")
    if window_end <= window_start:
        shape.bad("Field 'service_window_end' must be strictly after 'service_window_start'.")
    seasonal = shape.opt_int(body, "seasonal_volume_index", lo=50, hi=300, default=100)
    holiday = shape.opt_bool(body, "holiday_flag", default=False)

    # rung 16
    if weekday_name(service_date) not in contract["service_night_days"]:
        raise ApiError("ERR_SERVICE_DATE_NOT_SCHEDULED")
    eff_from = parse_date(contract["effective_from"])
    eff_to = parse_date(contract["effective_to"])
    if service_date < eff_from or service_date > eff_to:
        raise ApiError("ERR_SERVICE_DATE_NOT_SCHEDULED")

    row = _new_night(
        contract, body["service_date"].strip(), window_start, window_end, seasonal, holiday
    )
    return object_response(night_out(row), 201)


@bp.route("/valet/service-nights/<night_id>", methods=["GET"])
def read_night(night_id):
    admit((
        "PlatformAdmin",
        "ValetOpsManager",
        "PropertyManager",
        "BillingAnalyst",
        "Valet",
    ))
    row = get_night(night_id)
    return object_response(night_out(row))


@bp.route("/valet/service-nights", methods=["GET"])
def list_nights():
    admit(("PlatformAdmin", "ValetOpsManager", "PropertyManager", "BillingAnalyst"))
    limit, offset = pagination()
    f_contract = q("contract_id")
    f_rescheduled = q("rescheduled_from_night_id")
    f_verification = q("verification_status")
    f_billing = q("billing_status")
    f_date = q("service_date")
    rows = sort_rows(list(db.nights.values()))
    if f_contract is not None:
        rows = [r for r in rows if r["contract_id"] == f_contract]
    if f_rescheduled is not None:
        rows = [r for r in rows if r["rescheduled_from_night_id"] == f_rescheduled]
    if f_verification is not None:
        rows = [r for r in rows if r["verification_status"] == f_verification]
    if f_billing is not None:
        rows = [r for r in rows if r["billing_status"] == f_billing]
    if f_date is not None:
        rows = [r for r in rows if r["service_date"] == f_date]
    page, total, has_more = paginate(rows, limit, offset)
    return array_response([night_out(r) for r in page], limit, offset, total, has_more)


@bp.route("/valet/service-nights/<night_id>/close", methods=["POST"])
def close_night(night_id):
    admit(("PlatformAdmin", "ValetOpsManager"))
    night = get_night(night_id)
    shape.body()

    # rung 8
    if night["verification_status"] in TERMINAL_NIGHT:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if night["verification_status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE")

    recompute_night_counters(night)
    night["verification_status"] = select_verification_outcome(night)
    night["billing_status"] = "ACCRUED"
    for route in routes_of_night(night["id"]):
        if route["status"] in OPEN_ROUTE_STATUSES:
            route["status"] = "ABANDONED"
            route["abandon_reason"] = "NIGHT_CLOSED"
            touch(route)
    recompute_assigned_unit_coverage(night)
    touch(night)
    return object_response(night_out(night))


@bp.route("/valet/service-nights/<night_id>/reschedule", methods=["POST"])
def reschedule_night(night_id):
    admit(("PlatformAdmin", "ValetOpsManager"))
    night = get_night(night_id)
    body = shape.body()
    action = shape.req_enum(body, "action", ("SKIP", "SHIFT"))
    makeup_date = shape.opt_date(body, "makeup_service_date")
    shape.opt_str(body, "reason", max_len=500)

    # rung 8
    if night["verification_status"] in TERMINAL_NIGHT:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if night["verification_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    if night["rescheduled_from_night_id"] is not None:
        raise ApiError("ERR_INVALID_STATE")

    contract = contract_of_night(night)
    original_date = parse_date(night["service_date"])

    if action == "SHIFT":
        # rung 17
        if makeup_date is None:
            raise ApiError("ERR_INVALID_MAKEUP_DATE")
        if makeup_date <= original_date:
            raise ApiError("ERR_INVALID_MAKEUP_DATE")
        if (makeup_date - original_date).days > MAKEUP_WINDOW_DAYS:
            raise ApiError("ERR_INVALID_MAKEUP_DATE")
        eff_from = parse_date(contract["effective_from"])
        eff_to = parse_date(contract["effective_to"])
        if makeup_date < eff_from or makeup_date > eff_to:
            raise ApiError("ERR_INVALID_MAKEUP_DATE")
        for other in nights_of_contract(contract["id"]):
            if other["verification_status"] == "CANCELLED":
                continue
            if parse_date(other["service_date"]) == makeup_date:
                raise ApiError("ERR_INVALID_MAKEUP_DATE")

    cancel_night(
        night,
        cancel_route_statuses=RESCHEDULE_ROUTE_STATUSES,
        reschedule_action=action,
    )

    if action == "SHIFT":
        delta = timedelta(days=(makeup_date - original_date).days)
        window_start = parse_instant(night["service_window_start"]) + delta
        window_end = parse_instant(night["service_window_end"]) + delta
        _new_night(
            contract,
            makeup_date.isoformat(),
            window_start,
            window_end,
            night["seasonal_volume_index"],
            False,
            rescheduled_from_night_id=night["id"],
        )

    return object_response(night_out(night))
