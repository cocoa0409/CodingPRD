"""Cost allocations, in-kind contributions, outcome reports and the clock."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from common import resolve_grant, resolve_outcome_report
from errors import ApiError
from response import (
    array_envelope,
    auth_context,
    body,
    object_envelope,
    page,
    pagination_args,
    require_fields,
    require_role,
)
from services import inkind, outcome

bp = Blueprint("finance", __name__)

MEASURE_CODES = ("HOUSING_PLACEMENTS", "FOOD_UNITS_DISTRIBUTED", "COUNSELING_COMPLETION",
                 "IMMIGRATION_CASES_CLOSED", "REFUGEE_EMPLOYMENT")
DONOR_TYPES = ("PARISH", "VOLUNTEER", "CORPORATE")
VALUATION_METHODS = ("IRS_STANDARD_RATE", "APPRAISAL", "ACTUAL_COST", "UNVALUED")


def _filter(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]


@bp.get("/cost-allocations")
def list_cost_allocations():
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("FinanceOfficer", "ComplianceOfficer"))
    limit, offset = pagination_args()
    matches = _filter(db.ordered("cost_allocations"), "service_delivery_id",
                      request.args.get("service_delivery_id"))
    matches = _filter(matches, "grant_id", request.args.get("grant_id"))
    matches = _filter(matches, "status", request.args.get("status"))
    rows = [db.public(row) for row in page(matches, limit, offset)]
    return array_envelope(rows, limit, offset, len(matches))


@bp.get("/cost-allocations/<allocation_id>")
def read_cost_allocation(allocation_id):
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("FinanceOfficer", "ComplianceOfficer"))
    row = db.get("cost_allocations", allocation_id)
    if row is None:
        raise ApiError("ERR_INVALID_STATE", "The cost allocation line does not resolve.")
    return object_envelope(db.public(row))


@bp.post("/in-kind-donations")
def create_in_kind():
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("ProgramManager", "FinanceOfficer"))
    payload = body()
    require_fields(payload, ("grant_id", "donor_type", "donor_reference", "donation_date",
                             "hours", "valuation_method", "rate_cents"))
    grant = resolve_grant(payload["grant_id"])
    if payload["donor_type"] not in DONOR_TYPES:
        raise ApiError("ERR_BAD_REQUEST", "donor_type is not a declared donor type.")
    if payload["valuation_method"] not in VALUATION_METHODS:
        raise ApiError("ERR_BAD_REQUEST", "valuation_method is not a declared method.")
    donation_date = clock.parse(payload["donation_date"])
    hours = float(payload["hours"])
    if inkind.donor_hours_in_window(payload["donor_reference"], donation_date) + hours > \
            inkind.MAX_DONOR_HOURS:
        raise ApiError(
            "ERR_INKIND_HOURS_EXCEEDED",
            "This donor_reference would exceed 40 documented hours within the "
            "rolling seven-day window.",
        )
    if payload["valuation_method"] == "IRS_STANDARD_RATE" \
            and int(payload["rate_cents"]) != inkind.IRS_VOLUNTEER_HOUR_RATE_CENTS:
        raise ApiError(
            "ERR_INKIND_VALUATION_INVALID",
            "IRS_STANDARD_RATE valuations must use exactly %d cents per hour."
            % inkind.IRS_VOLUNTEER_HOUR_RATE_CENTS,
        )
    row = db.create("in_kind_donations", {
        "grant_id": grant["id"],
        "donor_type": payload["donor_type"],
        "donor_reference": payload["donor_reference"],
        "donation_date": donation_date,
        "hours": hours,
        "valuation_method": payload["valuation_method"],
        "rate_cents": int(payload["rate_cents"]),
        "value_cents": 0,
        "uncapped_value_cents": 0,
        "match_credit_cents": 0,
        "status": "ACCEPTED",
    })
    already = sum(
        other.get("match_credit_cents", 0)
        for other in inkind.eligible_rows(grant)
        if (other["created_at"], other["_seq"]) < (row["created_at"], row["_seq"])
    )
    value_cents, uncapped, credit = inkind.compute_values(row, grant, already)
    row["value_cents"] = value_cents
    row["uncapped_value_cents"] = uncapped
    row["match_credit_cents"] = credit
    return object_envelope(db.public(row)), 201


@bp.post("/outcome-reports")
def create_outcome_report():
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("ProgramManager",))
    payload = body()
    require_fields(payload, ("grant_id", "measure_code", "reporting_period_start",
                             "reporting_period_end", "numerator", "denominator"))
    grant = resolve_grant(payload["grant_id"])
    if payload["measure_code"] not in MEASURE_CODES:
        raise ApiError("ERR_BAD_REQUEST", "measure_code is not a declared measure.")
    start = clock.parse(payload["reporting_period_start"])
    end = clock.parse(payload["reporting_period_end"])
    gap = timedelta(days=1)
    for other in db.rows("outcome_reports"):
        if other.get("grant_id") != grant["id"]:
            continue
        if other.get("measure_code") != payload["measure_code"]:
            continue
        if other.get("status") not in ("DRAFT", "SUBMITTED", "ACCEPTED"):
            continue
        if start < other["reporting_period_end"] + gap \
                and other["reporting_period_start"] < end + gap:
            raise ApiError(
                "ERR_OUTCOME_PERIOD_OVERLAP",
                "The requested reporting window overlaps an existing report for "
                "this grant and measure; closed windows require a one-day gap.",
            )
    report = db.create("outcome_reports", {
        "grant_id": grant["id"],
        "measure_code": payload["measure_code"],
        "reporting_period_start": start,
        "reporting_period_end": end,
        "numerator": int(payload["numerator"]),
        "denominator": int(payload["denominator"]),
        "denominator_basis": "ALL_SERVED",
        "rate_pct": None,
        "status": "DRAFT",
    })
    return object_envelope(db.public(report)), 201


@bp.post("/outcome-reports/<report_id>/submit")
def submit_outcome_report(report_id):
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("ProgramManager",))
    report = resolve_outcome_report(report_id)
    status = report.get("status")
    if status not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT or RETURNED report may be submitted.")
    if (report.get("denominator") or 0) < outcome.MIN_DENOMINATOR:
        raise ApiError("ERR_INVALID_STATE", "The report's denominator must be at least 5.")
    grant = db.get("grants", report.get("grant_id"))
    if status == "DRAFT":
        if grant is None or report["reporting_period_start"] < grant["period_start"] \
                or report["reporting_period_end"] > grant["period_end"]:
            raise ApiError(
                "ERR_INVALID_STATE",
                "The reporting window must sit inside the grant's award period.",
            )
    rate, basis, _effective = outcome.compute(report)
    report["rate_pct"] = rate
    report["denominator_basis"] = basis
    # §3.8 states the match position as a precondition of submission ("Before an
    # outcome report for a grant may be submitted ..."), so the refusal is not
    # masked by the §3.9 denominator floor: a below-the-line submission is
    # refused with ERR_MATCH_REQUIREMENT_UNMET and the report lands in RETURNED.
    if status == "DRAFT" and grant is not None and not inkind.match_satisfied(grant):
        report["status"] = "RETURNED"
        db.touch(report)
        raise ApiError(
            "ERR_MATCH_REQUIREMENT_UNMET",
            "The grant's credited in-kind total is below its matching requirement.",
        )
    if rate is None:
        report["status"] = "RETURNED"
        db.touch(report)
        return object_envelope(db.public(report))
    report["status"] = "SUBMITTED"
    db.touch(report)
    return object_envelope(db.public(report))


@bp.post("/outcome-reports/<report_id>/accept")
def accept_outcome_report(report_id):
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("ComplianceOfficer",))
    report = resolve_outcome_report(report_id)
    if report.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED report may be accepted.")
    report["status"] = "ACCEPTED"
    db.touch(report)
    return object_envelope(db.public(report))


@bp.post("/outcome-reports/<report_id>/reject")
def reject_outcome_report(report_id):
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("ComplianceOfficer",))
    report = resolve_outcome_report(report_id)
    if report.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED report may be rejected.")
    report["status"] = "RETURNED"
    report["rate_pct"] = None
    db.touch(report)
    return object_envelope(db.public(report))


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth_context()
    require_role(request.headers.get("X-User-Role"), ("PlatformAdmin",))
    payload = body()
    require_fields(payload, ("to_iso8601",))
    clock.set_clock(payload["to_iso8601"])
    return object_envelope({})
