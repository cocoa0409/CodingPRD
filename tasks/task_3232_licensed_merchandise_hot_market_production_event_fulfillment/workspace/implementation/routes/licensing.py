"""Licensing endpoints.

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



@api.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    caller = authenticate()
    require_roles(caller, ("PlatformAdmin",))
    payload = body()
    instant = require_instant(payload, "current_utc")
    db.set_clock(instant)
    return ok_object({})



@api.route("/licensors", methods=["POST"])
def create_licensor():
    payload = body()
    name = require_field(payload, "name")
    if not isinstance(name, str) or not name.strip():
        fail(ERR_INVALID_REQUEST, "field 'name' must be a non-empty string")
    league_code = require_field(payload, "league_code")
    if not isinstance(league_code, str) or not league_code.strip():
        fail(ERR_INVALID_REQUEST, "field 'league_code' must be a non-empty string")
    rate = require_number(payload, "royalty_rate_pct", low=0, high=1)
    guarantee = require_int(payload, "minimum_guarantee_cents")
    if guarantee < 0:
        fail(ERR_INVALID_REQUEST,
             "field 'minimum_guarantee_cents' must be zero or greater")
    currency = optional_string(payload, "currency", "USD")

    caller = authenticate()
    require_roles(caller, ("PlatformAdmin",))

    licensor = {
        "name": name,
        "league_code": league_code,
        "royalty_rate_pct": rate,
        "minimum_guarantee_cents": guarantee,
        "accrued_royalty_cents": 0,
        "guarantee_recovery_block_cents": 0,
        "accrued_unsettled_cents": 0,
        "currency": currency,
    }
    db.init_common(licensor)
    db.store.licensors[licensor["id"]] = licensor
    return ok_object(licensor, 201)


@api.route("/licensors/<licensor_id>", methods=["GET"])
def read_licensor(licensor_id):
    caller = authenticate()
    require_roles(caller, ("LicensingOps", "AuditOnly", "EnforcementAgent"))
    licensor = get_licensor(licensor_id)
    if caller.role == "LicensingOps" and caller.user_id != licensor_id:
        fail(ERR_LICENSOR_MISMATCH, "a LicensingOps caller may only read its own licensor")
    return ok_object(licensor)


@api.route("/licensors/<licensor_id>/minimum-guarantee/apply", methods=["POST"])
def apply_minimum_guarantee(licensor_id):
    payload = body()
    reserved = require_int(payload, "reserved_cents")
    if reserved < 0:
        fail(ERR_INVALID_REQUEST, "field 'reserved_cents' must not be negative")
    breach = payload.get("accept_guarantee_breach", False)
    if breach is not None and not isinstance(breach, bool):
        fail(ERR_INVALID_REQUEST, "field 'accept_guarantee_breach' must be a boolean")
    expected = payload.get("expected_licensor_version")

    caller = authenticate()
    require_roles(caller, ("LicensingOps",))
    check_licensor_ownership(caller, licensor_id)

    licensor = get_licensor(licensor_id)
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        fail(ERR_INVALID_REQUEST, "field 'expected_licensor_version' is required")
    if expected != int(licensor.get("version", 0) or 0):
        fail(ERR_STALE_VERSION,
             "expected_licensor_version does not match the licensor's current version")

    settlement = ledger.apply_settlement(licensor, reserved, bool(breach))
    return ok_object(settlement, 201)


@api.route("/licensors/<licensor_id>/minimum-guarantee-settlements", methods=["GET"])
def list_settlements(licensor_id):
    caller = authenticate()
    require_roles(caller, ("LicensingOps", "AuditOnly"))
    get_licensor(licensor_id)
    if caller.role == "LicensingOps" and caller.user_id != licensor_id:
        fail(ERR_LICENSOR_MISMATCH, "a LicensingOps caller may only read its own licensor")
    limit, offset = pagination()
    items = db.created_order([s for s in db.store.settlements.values()
                              if s.get("licensor_id") == licensor_id])
    page, meta_extra = paginate(items, limit, offset)
    return ok_array(page, 200, meta_extra)


@api.route("/licensors/<licensor_id>/minimum-guarantee/reverse", methods=["POST"])
def reverse_minimum_guarantee(licensor_id):
    payload = body()
    expected = payload.get("expected_licensor_version")

    caller = authenticate()
    require_roles(caller, ("LicensingOps",))
    check_licensor_ownership(caller, licensor_id)

    licensor = get_licensor(licensor_id)
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        fail(ERR_INVALID_REQUEST, "field 'expected_licensor_version' is required")
    if expected != int(licensor.get("version", 0) or 0):
        fail(ERR_STALE_VERSION,
             "expected_licensor_version does not match the licensor's current version")

    settlement = ledger.reverse_settlement(licensor)
    return ok_object(settlement, 200)



@api.route("/designs", methods=["POST"])
def create_design():
    payload = body()
    licensor_id = require_field(payload, "licensor_id")
    team_code = require_field(payload, "team_code")
    if not isinstance(team_code, str) or not team_code.strip():
        fail(ERR_INVALID_REQUEST, "field 'team_code' must be a non-empty string")
    garment_sku = require_enum(payload, "garment_sku", GARMENT_SKUS)
    design_name = require_field(payload, "design_name")
    if not isinstance(design_name, str) or not design_name.strip():
        fail(ERR_INVALID_REQUEST, "field 'design_name' must be a non-empty string")
    player_code = optional_string(payload, "player_code", None)

    caller = authenticate()
    require_roles(caller, ("DesignOps",))

    licensor = get_licensor(licensor_id)

    design = {
        "licensor_id": licensor_id,
        "team_code": team_code,
        "player_code": player_code,
        "garment_sku": garment_sku,
        "design_name": design_name,
        "approval_state": "PENDING_LICENSOR_APPROVAL",
        "approved_version": None,
        "rejection_reason": None,
    }
    # Rights clearance: the licensor must hold a recorded project covering the
    # garment this design prints on.
    if garment_sku not in licensor_projects(licensor):
        fail(ERR_LICENSOR_PROJECT_NOT_FOUND,
             "the licensor holds no recorded rights project for garment_sku %s" % garment_sku)

    db.init_common(design)
    db.store.designs[design["id"]] = design
    return ok_object(design, 201)


@api.route("/designs", methods=["GET"])
def list_designs():
    caller = authenticate()
    require_roles(caller, ("DesignOps", "ProductionPlanner", "AuditOnly"))
    limit, offset = pagination()
    items = db.created_order(list(db.store.designs.values()))
    licensor_id = request.args.get("licensor_id")
    if licensor_id:
        items = [d for d in items if d.get("licensor_id") == licensor_id]
    approval_state = request.args.get("approval_state")
    if approval_state:
        items = [d for d in items if d.get("approval_state") == approval_state]
    page, meta_extra = paginate(items, limit, offset)
    return ok_array(page, 200, meta_extra)


@api.route("/designs/<design_id>", methods=["GET"])
def read_design(design_id):
    caller = authenticate()
    require_roles(caller, ("DesignOps", "LicensingOps", "ProductionPlanner", "AuditOnly"))
    # A bare path identifier that resolves to nothing is ERR_NOT_FOUND (PRD 2.11);
    # the reference-specific codes are reserved for request-body references.
    return ok_object(get_design(design_id, error_id=ERR_NOT_FOUND))


@api.route("/designs/<design_id>/submit", methods=["PUT"])
def submit_design(design_id):
    payload = body()
    expected = payload.get("expected_design_version")

    caller = authenticate()
    require_roles(caller, ("DesignOps",))

    design = get_design(design_id)
    if design.get("approval_state") != "APPROVAL_REJECTED":
        fail(ERR_INVALID_STATE, "only a rejected design may be resubmitted")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        fail(ERR_INVALID_REQUEST, "field 'expected_design_version' is required")
    if expected != int(design.get("version", 0) or 0):
        fail(ERR_STALE_VERSION,
             "expected_design_version does not match the design's current version")

    design["approval_state"] = "PENDING_LICENSOR_APPROVAL"
    design["rejection_reason"] = None
    db.touch(design)
    return ok_object(design, 200)


@api.route("/designs/<design_id>/licensor-decision", methods=["PUT"])
def licensor_decision(design_id):
    payload = body()
    decision = require_enum(payload, "decision", DECISIONS)
    expected = payload.get("expected_design_version")
    rejection_reason = payload.get("rejection_reason")
    if decision == "REJECT":
        if not isinstance(rejection_reason, str) or not rejection_reason.strip():
            fail(ERR_INVALID_REQUEST,
                 "field 'rejection_reason' is required and non-empty for a rejection")
    if rejection_reason is not None and not isinstance(rejection_reason, str):
        fail(ERR_INVALID_REQUEST, "field 'rejection_reason' must be a string")

    caller = authenticate()
    require_roles(caller, ("LicensingOps",))

    design = get_design(design_id)
    check_licensor_ownership(caller, design.get("licensor_id"))

    # A rejection is the revocation rail described by §3.1: it acts on artwork
    # the licensor has already cleared, so the approved design is the state that
    # admits it.  A design still awaiting a decision has nothing to revoke.
    if design.get("approval_state") == "APPROVAL_REJECTED":
        fail(ERR_INVALID_STATE,
             "the design has already been rejected")
    if decision == "APPROVE" and design.get("approval_state") != "PENDING_LICENSOR_APPROVAL":
        fail(ERR_INVALID_STATE,
             "the design is not awaiting a licensor decision")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        fail(ERR_INVALID_REQUEST, "field 'expected_design_version' is required")
    if expected != int(design.get("version", 0) or 0):
        fail(ERR_STALE_VERSION,
             "expected_design_version does not match the design's current version")

    licensor = db.store.licensors.get(design.get("licensor_id"))
    db.store.design_deciders[design_id] = caller.user_id

    if decision == "APPROVE":
        db.touch(design)
        design["approval_state"] = "APPROVED"
        design["approved_version"] = int(design["version"])
    else:
        design["approval_state"] = "APPROVAL_REJECTED"
        design["rejection_reason"] = rejection_reason
        db.touch(design)
        production.cascade_design_rejection(design, licensor)
    return ok_object(design, 200)


