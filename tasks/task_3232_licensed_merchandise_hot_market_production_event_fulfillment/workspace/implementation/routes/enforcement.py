"""Counterfeit enforcement endpoints.

Request-shape checks (the highest-precedence rung of the validation ladder),
authentication, role authorization and existence checks all live here; the
workflow rules they delegate to live in the service modules.
"""
from flask import request

import db
from errors import (
    ERR_ALREADY_COMMITTED, ERR_CAPACITY_EXCEEDED, ERR_COUNTERFEIT_OVERCOUNT,
    ERR_DESIGN_NOT_APPROVED, ERR_DESIGN_NOT_FOUND, ERR_EVENT_WINDOW_CLOSED,
    ERR_FORBIDDEN_ROLE, ERR_FULFILLMENT_ORDER_NOT_FOUND, ERR_GUARANTEE_FLOOR_BREACH,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_INVENTORY_INSUFFICIENT,
    ERR_LICENSOR_MISMATCH, ERR_LICENSOR_NOT_FOUND, ERR_LICENSOR_PROJECT_NOT_FOUND,
    ERR_LISTING_UNVERIFIED, ERR_LOT_EXHAUSTED, ERR_NO_ACCRUED_ROYALTY, ERR_NOT_FOUND,
    ERR_PICK_REMARK_REUSED, ERR_PRINT_QUANTITY_EXCEEDED, ERR_PRINT_TYPECAST_MISMATCH,
    ERR_PRODUCTION_ALREADY_COMMITTED, ERR_PRODUCTION_ORDER_NOT_FOUND,
    ERR_RUSH_COMMITMENT_BREACH, ERR_SEGREGATION_OF_DUTIES, ERR_SETTLEMENT_NOOP,
    ERR_STALE_VERSION, ERR_UNAUTHENTICATED, ERR_UNBALANCED_ALLOCATION, fail)
from response import (authenticate, ok_array, ok_object, paginate, pagination,
                      require_roles)
from routing import (
    CAPACITY_TYPES, CARRIERS, CHANNELS, DECISIONS, DEFAULT_HOURS_TO_OUTCOME,
    DESTROY_MODES, DISTRESS_REASONS, EVENT_OUTCOMES, EVENT_WINDOW_HOURS,
    GARMENT_SKUS, PRINT_TYPES, RETIRE_REASONS, TRIGGER_TYPES,
    api, body, check_licensor_ownership, check_licensor_project, check_segregation,
    get_capacity, get_design, get_layer, get_licensor, get_order, get_report, get_run,
    licensor_projects, optional_string, require_enum, require_field, require_int,
    require_instant, require_number, require_order_version, require_version)
from services import fulfillment, ledger, pricing, production



@api.route("/counterfeit-reports", methods=["POST"])
def create_counterfeit_report():
    payload = body()
    licensor_id = require_field(payload, "licensor_id")
    venue_code = require_field(payload, "venue_code")
    online_listing_id = require_field(payload, "online_listing_id")
    if not isinstance(online_listing_id, str) or not online_listing_id.strip():
        fail(ERR_INVALID_REQUEST, "field 'online_listing_id' must be a non-empty string")
    unit_count = require_int(payload, "unit_count", positive=True)
    suspect_quantity = require_int(payload, "suspect_quantity", optional=True, default=0)
    if suspect_quantity < 0:
        fail(ERR_INVALID_REQUEST, "field 'suspect_quantity' must not be negative")
    detected_at = require_instant(payload, "detected_at")

    caller = authenticate()
    require_roles(caller, ("EnforcementAgent",))

    get_licensor(licensor_id)

    report = {
        "licensor_id": licensor_id,
        "venue_code": venue_code,
        "online_listing_id": online_listing_id,
        "unit_count": unit_count,
        "suspect_quantity": int(suspect_quantity),
        "infringement_confirmed": None,
        "royalty_leakage_cents": 0,
        "penalty_cents": 0,
        "total_exposure_cents": 0,
        "report_status": "OPEN",
        "detected_at": db.fmt_iso(detected_at),
    }
    db.init_common(report)
    db.store.counterfeit_reports[report["id"]] = report
    return ok_object(report, 201)


@api.route("/counterfeit-reports", methods=["GET"])
def list_counterfeit_reports():
    caller = authenticate()
    require_roles(caller, ("EnforcementAgent", "AuditOnly"))
    limit, offset = pagination()
    items = db.created_order(list(db.store.counterfeit_reports.values()))
    for arg, field in (("licensor_id", "licensor_id"),
                       ("report_status", "report_status")):
        value = request.args.get(arg)
        if value:
            items = [r for r in items if r.get(field) == value]
    page, meta_extra = paginate(items, limit, offset)
    return ok_array(page, 200, meta_extra)


@api.route("/counterfeit-reports/<report_id>", methods=["GET"])
def read_counterfeit_report(report_id):
    caller = authenticate()
    require_roles(caller, ("EnforcementAgent", "AuditOnly"))
    return ok_object(get_report(report_id))


@api.route("/counterfeit-reports/<report_id>/enforce", methods=["POST"])
def enforce_counterfeit_report(report_id):
    payload = body()
    if "infringement_confirmed" not in payload or payload["infringement_confirmed"] is None:
        fail(ERR_INVALID_REQUEST, "field 'infringement_confirmed' is required")
    confirmed = payload["infringement_confirmed"]
    if not isinstance(confirmed, bool):
        fail(ERR_INVALID_REQUEST, "field 'infringement_confirmed' must be a boolean")
    suspect_quantity = require_int(payload, "suspect_quantity", optional=True, default=0)
    if suspect_quantity < 0:
        fail(ERR_INVALID_REQUEST, "field 'suspect_quantity' must not be negative")

    caller = authenticate()
    require_roles(caller, ("EnforcementAgent",))

    report = get_report(report_id)
    licensor = get_licensor(report.get("licensor_id"))

    # Counterfeit integrity: the constraint pair is evaluated before the listing
    # referential, so a confirmed overcount is reported even where the listing
    # also fails the VERIFIED- prefix test.
    if confirmed:
        if int(suspect_quantity) > int(report.get("unit_count", 0) or 0):
            fail(ERR_COUNTERFEIT_OVERCOUNT,
                 "suspect_quantity exceeds the report's unit_count")
        if int(suspect_quantity) <= 0:
            fail(ERR_COUNTERFEIT_OVERCOUNT,
                 "a confirmed infringement may not carry a zero suspect_quantity")
        if str(report.get("online_listing_id") or "").startswith("VERIFIED-"):
            fail(ERR_LISTING_UNVERIFIED,
                 "the marketplace listing has already been verified")

    report["suspect_quantity"] = int(suspect_quantity)
    report["infringement_confirmed"] = confirmed

    if confirmed:
        leakage, penalty, total = pricing.counterfeit_exposure(
            suspect_quantity, licensor.get("royalty_rate_pct", 0))
        report["royalty_leakage_cents"] = leakage
        report["penalty_cents"] = penalty
        report["total_exposure_cents"] = total
        report["report_status"] = "ENFORCED"
        db.touch(licensor)
    else:
        report["royalty_leakage_cents"] = 0
        report["penalty_cents"] = 0
        report["total_exposure_cents"] = 0
        report["report_status"] = "OPEN"

    db.touch(report)
    return ok_object(report, 200)