"""Vendor production requests, escalation and as-applied data submissions (PRD 3.5, 3.6)."""

from flask import Blueprint

import calc
import recompute
import serialize
import shape
from auth import guard
from enums import ALL_ROLES, LIVE_FULFILLMENT_STATUSES, SUBMISSION_TYPES
from envelope import success
from errors import ApiError
from helpers import list_response
from store import add_days, clock_now, db, lookup_path, new_row, touch

bp = Blueprint("vendor_requests", __name__)


@bp.route("/vendor-requests", methods=["POST"])
@guard("PlanSponsor")
def create_vendor_request():
    payload = shape.body()
    # Step 5: administrator_id, then plan_year_id, then the optional nqtl_item_id.
    raw_admin = shape.raw_fk(payload, "administrator_id")
    if raw_admin is not None and raw_admin not in db.administrators:
        raise ApiError("ERR_ADMINISTRATOR_NOT_FOUND")
    raw_plan_year = shape.raw_fk(payload, "plan_year_id")
    if raw_plan_year is not None and raw_plan_year not in db.plan_years:
        raise ApiError("ERR_PLAN_YEAR_NOT_FOUND")
    raw_item = shape.raw_fk(payload, "nqtl_item_id")
    if raw_item is not None and raw_item not in db.nqtl_items:
        raise ApiError("ERR_NQTL_ITEM_NOT_FOUND")

    administrator_id = shape.req_string(payload, "administrator_id", 1, None)
    plan_year_id = shape.req_string(payload, "plan_year_id", 1, None)
    item_id = shape.opt_string(payload, "nqtl_item_id", 1, None)
    requested_item_count = shape.req_int(payload, "requested_item_count", 1, 10)
    requested_types = shape.req_enum_array(payload, "requested_submission_types",
                                           SUBMISSION_TYPES)

    administrator = db.administrators[administrator_id]
    plan_year = db.plan_years[plan_year_id]
    item = db.nqtl_items[item_id] if item_id else None

    # Step 12: a scoped request must name an item of the same plan year.
    if item is not None and item["plan_year_id"] != plan_year_id:
        raise ApiError("ERR_CROSS_PLAN_YEAR_REFERENCE")
    # Step 14.
    recompute.gate_not_closed(plan_year)

    issued_at = clock_now()
    due_at = add_days(issued_at, administrator["contractual_production_days"])
    regulatory_due_at = add_days(issued_at, calc.REGULATORY_PRODUCTION_DAYS)

    # Step 29: half-open windows, no buffer, live requests only.
    for existing in db.vendor_requests.values():
        if (existing["administrator_id"] != administrator_id
                or existing["plan_year_id"] != plan_year_id
                or existing["fulfillment_status"] not in LIVE_FULFILLMENT_STATUSES):
            continue
        if issued_at < existing["due_at"] and existing["issued_at"] < due_at:
            raise ApiError("ERR_PRODUCTION_WINDOW_OVERLAP")

    row = new_row({
        "administrator_id": administrator_id,
        "plan_year_id": plan_year_id,
        "nqtl_item_id": item_id,
        "requested_item_count": requested_item_count,
        "requested_submission_types": requested_types,
        "issued_at": issued_at,
        "due_at": due_at,
        "regulatory_due_at": regulatory_due_at,
        "validated_submission_count": 0,
        "fulfillment_status": "OPEN",
        "escalation_status": "NONE",
    })
    db.vendor_requests[row["id"]] = row
    recompute.recompute_administrator(administrator)
    return success(serialize.vendor_request(row), 201)


@bp.route("/vendor-requests/<request_id>", methods=["GET"])
@guard(*ALL_ROLES)
def read_vendor_request(request_id):
    row = lookup_path(db.vendor_requests, request_id, "ERR_VENDOR_REQUEST_NOT_FOUND")
    return success(serialize.vendor_request(row))


@bp.route("/vendor-requests", methods=["GET"])
@guard(*ALL_ROLES)
def list_vendor_requests():
    return list_response(db.vendor_requests.values(), serialize.vendor_request,
                         ("administrator_id", "plan_year_id", "nqtl_item_id",
                          "fulfillment_status", "escalation_status"))


@bp.route("/vendor-requests/<request_id>/escalate", methods=["POST"])
@guard("PlanSponsor")
def escalate_vendor_request(request_id):
    vendor_request = lookup_path(db.vendor_requests, request_id,
                                 "ERR_VENDOR_REQUEST_NOT_FOUND")
    shape.body()
    plan_year = db.plan_years.get(vendor_request["plan_year_id"])
    # Step 14.
    recompute.gate_not_closed(plan_year)
    # Step 16: both rungs require a live, not-yet-breached request.
    if vendor_request["escalation_status"] == "BREACH_DECLARED":
        raise ApiError("ERR_ESCALATION_ALREADY_DECLARED")
    if vendor_request["fulfillment_status"] == "FULFILLED":
        raise ApiError("ERR_REQUEST_ALREADY_FULFILLED")

    now = clock_now()
    if vendor_request["escalation_status"] == "NONE":
        # Step 30: strictly later than due_at.
        if not now > vendor_request["due_at"]:
            raise ApiError("ERR_NOT_YET_OVERDUE")
        vendor_request["escalation_status"] = "NOTICE_SENT"
        touch(vendor_request)
        return success(serialize.vendor_request(vendor_request))

    grace_end = add_days(vendor_request["due_at"], calc.BREACH_GRACE_DAYS)
    if not now > grace_end:
        raise ApiError("ERR_NOT_YET_OVERDUE")
    vendor_request["escalation_status"] = "BREACH_DECLARED"
    touch(vendor_request)
    administrator = db.administrators.get(vendor_request["administrator_id"])
    if administrator is not None:
        recompute.recompute_administrator(administrator)
        for candidate in list(db.plan_years.values()):
            if candidate["administrator_id"] == administrator["id"]:
                recompute.recompute_plan_year(candidate)
    return success(serialize.vendor_request(vendor_request))


@bp.route("/vendor-requests/<request_id>/data-submissions", methods=["POST"])
@guard("Administrator")
def create_data_submission(request_id):
    vendor_request = lookup_path(db.vendor_requests, request_id,
                                 "ERR_VENDOR_REQUEST_NOT_FOUND")
    payload = shape.body()
    raw_classification = shape.raw_fk(payload, "classification_id")
    if raw_classification is not None and raw_classification not in db.classifications:
        raise ApiError("ERR_CLASSIFICATION_NOT_FOUND")

    classification_id = shape.req_string(payload, "classification_id", 1, None)
    submission_type = shape.req_enum(payload, "submission_type", SUBMISSION_TYPES)
    mh_denials = shape.opt_int(payload, "mh_denials", 0, None, 0)
    mh_claims = shape.opt_int(payload, "mh_adjudicated_claims", 0, None, 0)
    ms_denials = shape.opt_int(payload, "ms_denials", 0, None, 0)
    ms_claims = shape.opt_int(payload, "ms_adjudicated_claims", 0, None, 0)
    mh_pct = shape.opt_decimal(payload, "mh_in_network_provider_pct", 0, 1, None)
    ms_pct = shape.opt_decimal(payload, "ms_in_network_provider_pct", 0, 1, None)
    benchmark_note = shape.opt_string(payload, "benchmark_note", 1, 200)

    classification = db.classifications[classification_id]
    plan_year = db.plan_years.get(vendor_request["plan_year_id"])

    # Step 10: denials cannot exceed the claims they are drawn from.
    if mh_denials > mh_claims or ms_denials > ms_claims:
        raise ApiError("ERR_DENIALS_EXCEED_CLAIMS")
    # Step 11: the material must be material the sponsor asked for.
    if submission_type not in vendor_request["requested_submission_types"]:
        raise ApiError("ERR_SUBMISSION_TYPE_NOT_REQUESTED")
    # Step 12: the classification must belong to the request's plan year.
    if classification["plan_year_id"] != vendor_request["plan_year_id"]:
        raise ApiError("ERR_CROSS_PLAN_YEAR_REFERENCE")
    # Step 14.
    recompute.gate_not_closed(plan_year)
    # Step 16.
    if vendor_request["fulfillment_status"] == "FULFILLED":
        raise ApiError("ERR_REQUEST_ALREADY_FULFILLED")
    if vendor_request["escalation_status"] == "BREACH_DECLARED":
        raise ApiError("ERR_PRODUCTION_WINDOW_CLOSED")

    status, rejection_reason = _validate_submission(
        submission_type, mh_claims, ms_claims, ms_denials, mh_pct, ms_pct)

    row = new_row({
        "vendor_request_id": request_id,
        "classification_id": classification_id,
        "submission_type": submission_type,
        "mh_denials": mh_denials,
        "mh_adjudicated_claims": mh_claims,
        "ms_denials": ms_denials,
        "ms_adjudicated_claims": ms_claims,
        "mh_in_network_provider_pct": mh_pct,
        "ms_in_network_provider_pct": ms_pct,
        "benchmark_note": benchmark_note,
        "mh_denial_rate": None,
        "ms_denial_rate": None,
        "disparity_ratio": None,
        "network_composition_gap": None,
        "as_applied_flag": False,
        "rejection_reason": rejection_reason,
        "status": status,
    })
    if status == "VALIDATED" and submission_type == "DENIAL_RATES":
        (row["mh_denial_rate"], row["ms_denial_rate"], row["disparity_ratio"],
         row["as_applied_flag"]) = calc.denial_rate_disparity_index(
             mh_denials, mh_claims, ms_denials, ms_claims)
    if status == "VALIDATED" and submission_type == "NETWORK_COMPOSITION":
        row["network_composition_gap"] = calc.network_composition_gap(ms_pct, mh_pct)
    db.data_submissions[row["id"]] = row

    if status == "VALIDATED":
        _apply_validated_cascade(vendor_request, row, plan_year)
    return success(serialize.data_submission(row), 201)


def _validate_submission(submission_type, mh_claims, ms_claims, ms_denials, mh_pct, ms_pct):
    if submission_type == "DENIAL_RATES":
        if mh_claims < 1 or ms_claims < 1:
            return "REJECTED", "ZERO_ADJUDICATED_CLAIMS"
        if ms_denials < 1:
            return "REJECTED", "ZERO_COMPARATOR_DENIALS"
        return "VALIDATED", "NONE"
    if submission_type == "NETWORK_COMPOSITION":
        if mh_pct is None or ms_pct is None:
            return "REJECTED", "MISSING_NETWORK_PCT"
        return "VALIDATED", "NONE"
    return "VALIDATED", "NONE"


def _apply_validated_cascade(vendor_request, submission, plan_year):
    validated_count = len([s for s in db.data_submissions.values()
                           if s["vendor_request_id"] == vendor_request["id"]
                           and s["status"] == "VALIDATED"])
    vendor_request["validated_submission_count"] = validated_count
    fulfilled = False
    if validated_count >= vendor_request["requested_item_count"]:
        vendor_request["fulfillment_status"] = "FULFILLED"
        fulfilled = True
    elif vendor_request["fulfillment_status"] == "OPEN":
        vendor_request["fulfillment_status"] = "PARTIAL"
    touch(vendor_request)

    administrator = db.administrators.get(vendor_request["administrator_id"])
    if administrator is not None:
        recompute.recompute_administrator(administrator)

    for item in list(db.nqtl_items.values()):
        if item["classification_id"] == submission["classification_id"]:
            recompute.recompute_stringency(item, bump=True)
    if plan_year is not None:
        recompute.recompute_plan_year(plan_year)
    return fulfilled
