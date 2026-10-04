"""All /route-settlement endpoints (SCAFFOLD §1.5)."""

from flask import Blueprint, request, g

import calculations as calc
import services as svc
from db import db, iso_now, parse_iso
from errors import (
    ApiError,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_CHARGEBACK_CLAIM_NOT_FOUND,
    ERR_DISPUTE_NOT_FOUND,
    ERR_DISPUTE_WINDOW_EXPIRED,
    ERR_DRIVER_HOURS_EXCEEDED,
    ERR_DRIVER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PEAK_DECLARATION_NOT_FOUND,
    ERR_PROVIDER_NOT_FOUND,
    ERR_SERVICE_AREA_NOT_FOUND,
    ERR_SETTLEMENT_PERIOD_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_VEHICLE_NOT_FOUND,
)
from middleware import (
    ROLE_ACCOUNT_MANAGER as AM,
    ROLE_COMPLIANCE_OFFICER as CO,
    ROLE_PLATFORM_ADMIN as PA,
    ROLE_SERVICE_PROVIDER as SP,
    ROLE_SETTLEMENT_ANALYST as SA,
    body_json,
    bool_field,
    check_terminal,
    check_transition,
    datetime_field,
    enum_field,
    find_row,
    int_field,
    number_field,
    protected,
    resolve_body_fk,
    sort_by_created,
    string_field,
)
from response import entity_payload, paginate, success

api = Blueprint("api", __name__)

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _typed(row, entity_type):
    row["__type"] = entity_type
    return row


def _result(data, status=200):
    return success(data, "object", status=status)


def _serialize(entity_type, row):
    return entity_payload(entity_type, row)


def _get(entity_type, row_id, not_found):
    return find_row(entity_type, row_id, not_found)


def _filtered(entity_type, filters):
    rows = db.all(entity_type)
    for key, value in filters.items():
        if value is None:
            continue
        rows = [r for r in rows if r.get(key) == value]
    return rows


def _paginated_response(entity_type, rows, args):
    ordered = sort_by_created(rows)
    page, meta = paginate(ordered, args)
    return success([_serialize(entity_type, r) for r in page], "array", pagination=meta)


def _check_occ(entity_type, row, body, field_name):
    """The three OCC-guarded writes (PRD §2.11).

    The expected version is required, not optional: a caller that omits the
    field receives the stale-version rejection rather than a silent success.
    """
    supplied = body.get(field_name)
    if supplied is None:
        raise ApiError(ERR_STALE_VERSION, "%s is required" % field_name)
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise ApiError(ERR_STALE_VERSION, "%s must be an integer" % field_name)
    if supplied != int(row.get("version", 0)):
        raise ApiError(ERR_STALE_VERSION)


# ===========================================================================
# Service providers
# ===========================================================================

@api.route("/service-providers", methods=["POST"])
@protected([AM])
def create_service_provider():
    body = body_json()
    legal_name = string_field(body, "legal_name")
    tax_id = string_field(body, "tax_id")
    provider_type = enum_field(body, "provider_type", {"AGREED", "SUCCESSOR"}, default="AGREED")
    for existing in db.all("ServiceProvider"):
        if existing["tax_id"] == tax_id:
            raise ApiError(ERR_INVALID_REQUEST, "tax_id must be unique across ServiceProvider rows")

    row = {
        "legal_name": legal_name,
        "provider_type": provider_type,
        "tax_id": tax_id,
        "brand_compliance_pct": None,
        "qualification_pct": 100.0,
        "safety_index": None,
        "lifetime_paid_cents": 0,
        "chargeback_outstanding_cents": 0,
        "status": "UNDER_REVIEW",
    }
    db.insert("ServiceProvider", row)
    _typed(row, "ServiceProvider")
    # Derived at registration: with no fleet on file this legitimately yields 0.00.
    row["brand_compliance_pct"] = calc.brand_compliance_pct(row["id"])
    return success(_serialize("ServiceProvider", row), status=201)


@api.route("/service-providers", methods=["GET"])
@protected([AM, SA, CO])
def list_service_providers():
    rows = _filtered("ServiceProvider", {"status": request.args.get("status")})
    return _paginated_response("ServiceProvider", rows, request.args)


@api.route("/service-providers/<row_id>", methods=["GET"])
@protected([AM, SA, CO, SP])
def get_service_provider(row_id):
    row = _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    return _result(_serialize("ServiceProvider", row))


@api.route("/service-providers/<row_id>/approve", methods=["POST"])
@protected([AM])
def approve_service_provider(row_id):
    provider = _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    check_terminal(provider["status"], ["SUSPENDED"])
    if provider["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "only a provider under review may be approved")
    # The optional `expected` field is accepted; the provider's version is never
    # an OCC-guarded parent, so its presence never causes a rejection.
    body_json()
    svc.provider_approve(provider)
    return _result(_serialize("ServiceProvider", provider))


@api.route("/service-providers/<row_id>/reopen-review", methods=["POST"])
@protected([AM])
def reopen_service_provider(row_id):
    provider = _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    check_terminal(provider["status"], ["SUSPENDED"])
    if provider["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "only an approved provider may be reopened")
    provider["status"] = "UNDER_REVIEW"
    db.touch("ServiceProvider", provider)
    return _result(_serialize("ServiceProvider", provider))


@api.route("/service-providers/<row_id>/suspend", methods=["POST"])
@protected([AM])
def suspend_service_provider(row_id):
    provider = _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    check_terminal(provider["status"], ["SUSPENDED"])
    if provider["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "only an approved provider may be suspended")
    svc.provider_suspend(provider)
    return _result(_serialize("ServiceProvider", provider))


# ===========================================================================
# Service areas
# ===========================================================================

@api.route("/service-areas", methods=["POST"])
@protected([AM])
def create_service_area():
    body = body_json()
    area_code = string_field(body, "area_code")
    state_code = string_field(body, "state_code")
    zip_low = string_field(body, "zip_prefix_low")
    zip_high = string_field(body, "zip_prefix_high")
    capacity = int_field(body, "stop_capacity_weekly", minimum=1, maximum=10 ** 12)

    if len(state_code) != 2 or not state_code.isupper() or not state_code.isalpha():
        raise ApiError(ERR_INVALID_REQUEST, "state_code must be two uppercase letters")
    for value, label in ((zip_low, "zip_prefix_low"), (zip_high, "zip_prefix_high")):
        if len(value) != 3 or not value.isdigit():
            raise ApiError(ERR_INVALID_REQUEST, "%s must be exactly three digits" % label)
    if int(zip_high) < int(zip_low):
        raise ApiError(ERR_INVALID_REQUEST, "zip_prefix_high must be >= zip_prefix_low")

    for existing in db.all("ServiceArea"):
        if existing["area_code"] == area_code and existing["status"] != "ARCHIVED":
            raise ApiError(ERR_INVALID_REQUEST, "area_code must be unique across non-ARCHIVED areas")

    row = {
        "area_code": area_code,
        "state_code": state_code,
        "zip_prefix_low": zip_low,
        "zip_prefix_high": zip_high,
        "stop_capacity_weekly": capacity,
        "assigned_provider_id": None,
        "status": "UNASSIGNED",
    }
    db.insert("ServiceArea", row)
    _typed(row, "ServiceArea")
    return success(_serialize("ServiceArea", row), status=201)


@api.route("/service-areas", methods=["GET"])
@protected([AM, SA, CO, SP])
def list_service_areas():
    rows = _filtered("ServiceArea", {
        "status": request.args.get("status"),
        "state_code": request.args.get("state_code"),
    })
    return _paginated_response("ServiceArea", rows, request.args)


@api.route("/service-areas/<row_id>", methods=["GET"])
@protected([AM, SA, CO, SP])
def get_service_area(row_id):
    row = _get("ServiceArea", row_id, ERR_SERVICE_AREA_NOT_FOUND)
    return _result(_serialize("ServiceArea", row))


@api.route("/service-areas/<row_id>/decommission", methods=["POST"])
@protected([AM])
def decommission_service_area(row_id):
    area = _get("ServiceArea", row_id, ERR_SERVICE_AREA_NOT_FOUND)
    # ARCHIVED is terminal: it accepts no further transition.
    check_terminal(area["status"], ["ARCHIVED"])
    area["status"] = "ARCHIVED"
    db.touch("ServiceArea", area)
    return _result(_serialize("ServiceArea", area))


@api.route("/service-areas/<row_id>/route-assignments", methods=["GET"])
@protected([AM, SA, SP])
def area_route_assignments(row_id):
    _get("ServiceArea", row_id, ERR_SERVICE_AREA_NOT_FOUND)
    rows = _filtered("RouteAssignment", {"service_area_id": row_id})
    return _paginated_response("RouteAssignment", rows, request.args)


@api.route("/service-areas/<row_id>/settlement-periods", methods=["GET"])
@protected([AM, SA, SP])
def area_settlement_periods(row_id):
    _get("ServiceArea", row_id, ERR_SERVICE_AREA_NOT_FOUND)
    rows = _filtered("SettlementPeriod", {"service_area_id": row_id})
    return _paginated_response("SettlementPeriod", rows, request.args)


@api.route("/service-areas/<row_id>/vehicles", methods=["GET"])
@protected([AM, CO, SP])
def area_vehicles(row_id):
    _get("ServiceArea", row_id, ERR_SERVICE_AREA_NOT_FOUND)
    rows = _filtered("Vehicle", {"service_area_id": row_id})
    return _paginated_response("Vehicle", rows, request.args)


@api.route("/service-areas/<row_id>/drivers", methods=["GET"])
@protected([AM, CO, SP])
def area_drivers(row_id):
    _get("ServiceArea", row_id, ERR_SERVICE_AREA_NOT_FOUND)
    rows = _filtered("Driver", {"service_area_id": row_id})
    return _paginated_response("Driver", rows, request.args)


@api.route("/service-areas/<row_id>/agreements", methods=["GET"])
@protected([AM, SA, SP])
def area_agreements(row_id):
    _get("ServiceArea", row_id, ERR_SERVICE_AREA_NOT_FOUND)
    rows = _filtered("Agreement", {"service_area_id": row_id})
    return _paginated_response("Agreement", rows, request.args)


@api.route("/service-areas/<row_id>/peak-season-declarations", methods=["GET"])
@protected([AM, SA, SP])
def area_declarations(row_id):
    _get("ServiceArea", row_id, ERR_SERVICE_AREA_NOT_FOUND)
    rows = _filtered("PeakSeasonDeclaration", {"service_area_id": row_id})
    return _paginated_response("PeakSeasonDeclaration", rows, request.args)


@api.route("/service-areas/<row_id>/service-providers", methods=["GET"])
@protected([AM, SA, SP])
def area_holding_providers(row_id):
    area = _get("ServiceArea", row_id, ERR_SERVICE_AREA_NOT_FOUND)
    rows = []
    holder = area.get("assigned_provider_id")
    if holder:
        row = db.get("ServiceProvider", holder)
        if row is not None:
            rows = [row]
    ordered = sort_by_created(rows)
    page, meta = paginate(ordered, request.args)
    return success([_serialize("ServiceProvider", r) for r in page], "array", pagination=meta)


# ===========================================================================
# Route assignments
# ===========================================================================

@api.route("/route-assignments", methods=["POST"])
@protected([AM])
def create_route_assignment():
    body = body_json()
    area_id = string_field(body, "service_area_id")
    provider_id = string_field(body, "provider_id")
    effective_at = datetime_field(body, "effective_date")
    transfer_price = int_field(body, "transfer_price_cents", default=0, required=False, minimum=0)

    provider = _get("ServiceProvider", provider_id, ERR_PROVIDER_NOT_FOUND)
    area = _get("ServiceArea", area_id, ERR_SERVICE_AREA_NOT_FOUND)
    # Priority 12: every body-declared foreign key resolves at a single point.
    acquiring_id = body.get("acquiring_provider_id")
    if acquiring_id is not None:
        resolve_body_fk("ServiceProvider", acquiring_id, ERR_PROVIDER_NOT_FOUND, "acquiring_provider_id")
    # Priority 16: OCC the create against the service area, before any business rule.
    _check_occ("ServiceArea", area, body, "expected_service_area_version")

    if area["status"] == "ARCHIVED":
        raise ApiError(ERR_INVALID_STATE, "an ARCHIVED area rejects new assignments")
    # Priority 17, then priority 18.
    svc.require_area_free(area["id"])
    svc.require_no_overlap(area["id"], effective_at)
    # Priority 21: the provider's coverage must clear the governing agreement floor.
    floor = svc.agreement_floor_for_area(provider["id"], area["id"])
    svc.require_insurance(provider["id"], floor, allow_submitted=True)

    row = {
        "service_area_id": area_id,
        "provider_id": provider_id,
        "acquiring_provider_id": acquiring_id,
        "superseded_by_assignment_id": None,
        "effective_date": iso_now(effective_at),
        "effective_date_dt": effective_at,
        "transfer_price_cents": transfer_price or 0,
        "occupancy_ends_at": None,
        "occupancy_ends_at_dt": None,
        "compliance_failures_count": 0,
        "status": "DRAFT",
    }
    db.insert("RouteAssignment", row)
    _typed(row, "RouteAssignment")
    db.touch("ServiceArea", area)
    return success(_serialize("RouteAssignment", row), status=201)


@api.route("/route-assignments", methods=["GET"])
@protected([AM, SA, SP])
def list_route_assignments():
    rows = _filtered("RouteAssignment", {
        "service_area_id": request.args.get("service_area_id"),
        "provider_id": request.args.get("provider_id"),
        "status": request.args.get("status"),
    })
    return _paginated_response("RouteAssignment", rows, request.args)


@api.route("/route-assignments/<row_id>", methods=["GET"])
@protected([AM, SA, SP])
def get_route_assignment(row_id):
    row = _get("RouteAssignment", row_id, ERR_ASSIGNMENT_NOT_FOUND)
    return _result(_serialize("RouteAssignment", row))


@api.route("/route-assignments/<row_id>/activate", methods=["POST"])
@protected([AM])
def activate_route_assignment(row_id):
    assignment = _get("RouteAssignment", row_id, ERR_ASSIGNMENT_NOT_FOUND)
    check_transition(assignment["status"], ["DRAFT"], svc.ROUTE_ASSIGNMENT_TERMINAL)
    svc.assignment_activate(assignment)
    return _result(_serialize("RouteAssignment", assignment))


@api.route("/route-assignments/<row_id>/terminate", methods=["POST"])
@protected([AM])
def terminate_route_assignment(row_id):
    assignment = _get("RouteAssignment", row_id, ERR_ASSIGNMENT_NOT_FOUND)
    check_transition(assignment["status"], ["ACTIVE"], svc.ROUTE_ASSIGNMENT_TERMINAL)
    svc.assignment_terminate(assignment)
    return _result(_serialize("RouteAssignment", assignment))


@api.route("/route-assignments/<row_id>/request-transfer", methods=["POST"])
@protected([SP])
def request_transfer(row_id):
    assignment = _get("RouteAssignment", row_id, ERR_ASSIGNMENT_NOT_FOUND)
    check_transition(assignment["status"], ["ACTIVE"], svc.ROUTE_ASSIGNMENT_TERMINAL)
    # Entity-backed identity: the acting provider must hold this title.
    if assignment["provider_id"] != g.uid:
        raise ApiError(ERR_INVALID_STATE, "the acting provider does not hold this title")
    body = body_json()
    acquiring_id = string_field(body, "acquiring_provider_id")
    price = int_field(body, "transfer_price_cents", minimum=0)
    acquiring = resolve_body_fk("ServiceProvider", acquiring_id, ERR_PROVIDER_NOT_FOUND, "acquiring_provider_id")
    svc.assignment_request_transfer(assignment, acquiring, price)
    return _result(_serialize("RouteAssignment", assignment))


@api.route("/route-assignments/<row_id>/approve-transfer", methods=["POST"])
@protected([AM])
def approve_transfer(row_id):
    assignment = _get("RouteAssignment", row_id, ERR_ASSIGNMENT_NOT_FOUND)
    check_transition(assignment["status"], ["PENDING_TRANSFER"], svc.ROUTE_ASSIGNMENT_TERMINAL)
    body = body_json()
    area = _get("ServiceArea", assignment["service_area_id"], ERR_SERVICE_AREA_NOT_FOUND)
    _check_occ("ServiceArea", area, body, "expected_service_area_version")
    svc.assignment_approve_transfer(assignment)
    return _result(_serialize("RouteAssignment", assignment))


@api.route("/route-assignments/<row_id>/withdraw-transfer", methods=["POST"])
@protected([SP])
def withdraw_transfer(row_id):
    assignment = _get("RouteAssignment", row_id, ERR_ASSIGNMENT_NOT_FOUND)
    check_transition(assignment["status"], ["PENDING_TRANSFER"], svc.ROUTE_ASSIGNMENT_TERMINAL)
    if assignment["provider_id"] != g.uid:
        raise ApiError(ERR_INVALID_STATE, "the acting provider does not hold this title")
    svc.assignment_withdraw_transfer(assignment)
    return _result(_serialize("RouteAssignment", assignment))


@api.route("/route-assignments/<row_id>/reaffirm", methods=["POST"])
@protected([AM])
def reaffirm_assignment(row_id):
    assignment = _get("RouteAssignment", row_id, ERR_ASSIGNMENT_NOT_FOUND)
    check_transition(assignment["status"], ["ACTIVE"], svc.ROUTE_ASSIGNMENT_TERMINAL)
    svc.assignment_reaffirm(assignment)
    return _result(_serialize("RouteAssignment", assignment))


@api.route("/route-assignments/<row_id>/successors", methods=["GET"])
@protected([AM, SA])
def assignment_successors(row_id):
    assignment = _get("RouteAssignment", row_id, ERR_ASSIGNMENT_NOT_FOUND)
    rows = []
    # The transferring title's own back-pointer names the successor that replaced it.
    successor_id = assignment.get("superseded_by_assignment_id")
    if successor_id:
        successor = db.get("RouteAssignment", successor_id)
        if successor is not None:
            rows = [successor]
    return _paginated_response("RouteAssignment", rows, request.args)


# ===========================================================================
# Agreements
# ===========================================================================

@api.route("/agreements", methods=["POST"])
@protected([AM])
def create_agreement():
    body = body_json()
    provider_id = string_field(body, "provider_id")
    area_id = string_field(body, "service_area_id")
    base_rate = int_field(body, "base_rate_cents_per_stop", minimum=0)
    package_rate = int_field(body, "package_rate_cents", minimum=0)
    peak_surcharge = int_field(body, "peak_surcharge_cents", minimum=0)
    coverage = int_field(body, "insurance_coverage_cents", minimum=0)
    negotiated_by = string_field(body, "negotiated_by")

    _get("ServiceProvider", provider_id, ERR_PROVIDER_NOT_FOUND)
    _get("ServiceArea", area_id, ERR_SERVICE_AREA_NOT_FOUND)

    row = {
        "provider_id": provider_id,
        "service_area_id": area_id,
        "base_rate_cents_per_stop": base_rate,
        "package_rate_cents": package_rate,
        "peak_surcharge_cents": peak_surcharge,
        "insurance_coverage_cents": coverage,
        "negotiated_by": negotiated_by,
        "renewal_due_at": None,
        "renewal_due_at_dt": None,
        "activated_at": None,
        "rounds_used": 0,
        "status": "DRAFT",
    }
    db.insert("Agreement", row)
    _typed(row, "Agreement")
    return success(_serialize("Agreement", row), status=201)


@api.route("/agreements", methods=["GET"])
@protected([AM, SA, SP])
def list_agreements():
    rows = _filtered("Agreement", {
        "provider_id": request.args.get("provider_id"),
        "service_area_id": request.args.get("service_area_id"),
        "status": request.args.get("status"),
    })
    return _paginated_response("Agreement", rows, request.args)


@api.route("/agreements/<row_id>", methods=["GET"])
@protected([AM, SA, SP])
def get_agreement(row_id):
    row = _get("Agreement", row_id, ERR_AGREEMENT_NOT_FOUND)
    return _result(_serialize("Agreement", row))


@api.route("/agreements/<row_id>/submit", methods=["POST"])
@protected([SP])
def submit_agreement(row_id):
    agreement = _get("Agreement", row_id, ERR_AGREEMENT_NOT_FOUND)
    check_transition(agreement["status"], ["DRAFT", "RE_NEGOTIATION"], svc.AGREEMENT_TERMINAL)
    # Entity-backed identity: the submitting provider must be named on the agreement.
    if agreement["provider_id"] != g.uid:
        raise ApiError(ERR_INVALID_STATE, "the acting provider is not named on this agreement")
    svc.agreement_submit(agreement)
    return _result(_serialize("Agreement", agreement))


@api.route("/agreements/<row_id>/sign", methods=["POST"])
@protected([AM])
def sign_agreement(row_id):
    agreement = _get("Agreement", row_id, ERR_AGREEMENT_NOT_FOUND)
    check_transition(agreement["status"], ["PENDING_REVIEW"], svc.AGREEMENT_TERMINAL)
    svc.agreement_sign(agreement, g.uid)
    return _result(_serialize("Agreement", agreement))


@api.route("/agreements/<row_id>/renegotiate", methods=["POST"])
@protected([AM])
def renegotiate_agreement(row_id):
    agreement = _get("Agreement", row_id, ERR_AGREEMENT_NOT_FOUND)
    check_transition(agreement["status"], ["PENDING_REVIEW", "ACTIVE"], svc.AGREEMENT_TERMINAL)
    svc.agreement_renegotiate(agreement)
    return _result(_serialize("Agreement", agreement))


@api.route("/agreements/<row_id>/amend", methods=["POST"])
@protected([AM])
def amend_agreement(row_id):
    agreement = _get("Agreement", row_id, ERR_AGREEMENT_NOT_FOUND)
    check_transition(agreement["status"], ["ACTIVE"], svc.AGREEMENT_TERMINAL)
    svc.agreement_amend(agreement)
    return _result(_serialize("Agreement", agreement))


@api.route("/agreements/<row_id>/expire", methods=["POST"])
@protected([AM])
def expire_agreement(row_id):
    agreement = _get("Agreement", row_id, ERR_AGREEMENT_NOT_FOUND)
    # The expiry branch of the state machine runs from ACTIVE only.
    check_transition(agreement["status"], ["ACTIVE"], svc.AGREEMENT_TERMINAL)
    svc.agreement_expire(agreement)
    return _result(_serialize("Agreement", agreement))


@api.route("/agreements/<row_id>/terminate", methods=["POST"])
@protected([AM])
def terminate_agreement(row_id):
    agreement = _get("Agreement", row_id, ERR_AGREEMENT_NOT_FOUND)
    check_transition(agreement["status"], ["RE_NEGOTIATION"], svc.AGREEMENT_TERMINAL)
    svc.agreement_terminate(agreement)
    return _result(_serialize("Agreement", agreement))


@api.route("/agreements/<row_id>/renewal-recommendation", methods=["GET"])
@protected([AM, SA])
def agreement_renewal_recommendation(row_id):
    agreement = _get("Agreement", row_id, ERR_AGREEMENT_NOT_FOUND)
    return _result(calc.renewal_recommendation(agreement))


@api.route("/agreements/<row_id>/negotiation-rounds", methods=["GET"])
@protected([AM, SP])
def agreement_negotiation_rounds(row_id):
    agreement = _get("Agreement", row_id, ERR_AGREEMENT_NOT_FOUND)
    used = int(agreement.get("rounds_used") or 0)
    return _result({
        "agreement_id": agreement["id"],
        "rounds_used": used,
        "rounds_remaining": max(0, svc.RENEGOTIATION_ROUND_BUDGET - used),
        "renewal_due_at": agreement.get("renewal_due_at"),
    })


# ===========================================================================
# Vehicles
# ===========================================================================

@api.route("/vehicles", methods=["POST"])
@protected([SP, AM])
def create_vehicle():
    body = body_json()
    provider_id = string_field(body, "provider_id")
    area_id = string_field(body, "service_area_id")
    vehicle_class = enum_field(body, "vehicle_class", {"STEP_VAN", "BOX_TRUCK", "TRACTOR_TRAILER"})
    gvwr = int_field(body, "gvwr_pounds", minimum=1)
    is_temporary = bool_field(body, "is_temporary", default=False)

    _get("ServiceProvider", provider_id, ERR_PROVIDER_NOT_FOUND)
    area = _get("ServiceArea", area_id, ERR_SERVICE_AREA_NOT_FOUND)
    svc.require_vehicle_eligible(vehicle_class, area)
    if is_temporary:
        svc.require_temporary_capacity(area_id, "vehicle")

    row = {
        "provider_id": provider_id,
        "service_area_id": area_id,
        "vehicle_class": vehicle_class,
        "gvwr_pounds": gvwr,
        "is_temporary": is_temporary,
        "branding_compliance": "PASSED",
        "status": "PENDING",
    }
    db.insert("Vehicle", row)
    _typed(row, "Vehicle")
    return success(_serialize("Vehicle", row), status=201)


@api.route("/vehicles", methods=["GET"])
@protected([AM, CO, SP])
def list_vehicles():
    rows = _filtered("Vehicle", {
        "provider_id": request.args.get("provider_id"),
        "service_area_id": request.args.get("service_area_id"),
        "status": request.args.get("status"),
    })
    return _paginated_response("Vehicle", rows, request.args)


@api.route("/vehicles/<row_id>", methods=["GET"])
@protected([AM, CO, SP])
def get_vehicle(row_id):
    row = _get("Vehicle", row_id, ERR_VEHICLE_NOT_FOUND)
    return _result(_serialize("Vehicle", row))


@api.route("/vehicles/<row_id>/branding-check", methods=["POST"])
@protected([CO])
def branding_check(row_id):
    vehicle = _get("Vehicle", row_id, ERR_VEHICLE_NOT_FOUND)
    check_terminal(vehicle["status"], ["DECOMMISSIONED"])
    body = body_json()
    outcome = enum_field(body, "branding_compliance", {"PASSED", "FAILED"})
    vehicle["branding_compliance"] = outcome
    calc.recompute_brand_compliance(vehicle["provider_id"])
    db.touch("Vehicle", vehicle)
    return _result(_serialize("Vehicle", vehicle))


@api.route("/vehicles/<row_id>/activate", methods=["POST"])
@protected([AM])
def activate_vehicle(row_id):
    vehicle = _get("Vehicle", row_id, ERR_VEHICLE_NOT_FOUND)
    check_terminal(vehicle["status"], ["DECOMMISSIONED"])
    if vehicle["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "only a pending vehicle may be activated")
    area = _get("ServiceArea", vehicle["service_area_id"], ERR_SERVICE_AREA_NOT_FOUND)
    svc.require_vehicle_eligible(vehicle["vehicle_class"], area)
    vehicle["status"] = "ACTIVE"
    calc.recompute_brand_compliance(vehicle["provider_id"])
    db.touch("Vehicle", vehicle)
    return _result(_serialize("Vehicle", vehicle))


@api.route("/vehicles/<row_id>/chargeback-claims", methods=["GET"])
@protected([AM, SA, CO])
def vehicle_claims(row_id):
    _get("Vehicle", row_id, ERR_VEHICLE_NOT_FOUND)
    rows = _filtered("ChargebackClaim", {"vehicle_id": row_id})
    return _paginated_response("ChargebackClaim", rows, request.args)


# ===========================================================================
# Drivers
# ===========================================================================

@api.route("/drivers", methods=["POST"])
@protected([SP, AM])
def create_driver():
    body = body_json()
    provider_id = string_field(body, "provider_id")
    area_id = string_field(body, "service_area_id")
    full_name = string_field(body, "full_name")
    license_class = enum_field(body, "license_class", {"CLASS_C", "CLASS_B", "CLASS_A"})
    qualification = enum_field(body, "qualification_status", {"QUALIFIED", "UNQUALIFIED"}, default="UNQUALIFIED")
    is_temporary = bool_field(body, "is_temporary", default=False)

    _get("ServiceProvider", provider_id, ERR_PROVIDER_NOT_FOUND)
    _get("ServiceArea", area_id, ERR_SERVICE_AREA_NOT_FOUND)
    if is_temporary:
        svc.require_temporary_capacity(area_id, "driver")

    row = {
        "provider_id": provider_id,
        "service_area_id": area_id,
        "full_name": full_name,
        "license_class": license_class,
        "qualification_status": qualification,
        "is_temporary": is_temporary,
        "duty_window_starts_at": None,
        "duty_window_ends_at": None,
        "duty_window_ends_at_dt": None,
        "status": "PENDING",
    }
    db.insert("Driver", row)
    _typed(row, "Driver")
    return success(_serialize("Driver", row), status=201)


@api.route("/drivers", methods=["GET"])
@protected([AM, CO, SP])
def list_drivers():
    rows = _filtered("Driver", {
        "provider_id": request.args.get("provider_id"),
        "service_area_id": request.args.get("service_area_id"),
        "status": request.args.get("status"),
    })
    return _paginated_response("Driver", rows, request.args)


@api.route("/drivers/<row_id>", methods=["GET"])
@protected([AM, CO, SP])
def get_driver(row_id):
    row = _get("Driver", row_id, ERR_DRIVER_NOT_FOUND)
    return _result(_serialize("Driver", row))


@api.route("/drivers/<row_id>/qualify", methods=["POST"])
@protected([CO])
def qualify_driver(row_id):
    driver = _get("Driver", row_id, ERR_DRIVER_NOT_FOUND)
    check_terminal(driver["status"], ["TERMINATED"])
    body = body_json()
    outcome = enum_field(body, "qualification_status", {"QUALIFIED", "UNQUALIFIED"})
    driver["qualification_status"] = outcome
    calc.recompute_qualification_pct(driver["provider_id"])
    db.touch("Driver", driver)
    return _result(_serialize("Driver", driver))


@api.route("/drivers/<row_id>/suspend", methods=["POST"])
@protected([CO])
def suspend_driver(row_id):
    driver = _get("Driver", row_id, ERR_DRIVER_NOT_FOUND)
    check_terminal(driver["status"], ["TERMINATED"])
    driver["status"] = "SUSPENDED"
    calc.recompute_qualification_pct(driver["provider_id"])
    db.touch("Driver", driver)
    return _result(_serialize("Driver", driver))


@api.route("/drivers/<row_id>/duty-shifts", methods=["POST"])
@protected([SP])
def record_duty_shift(row_id):
    driver = _get("Driver", row_id, ERR_DRIVER_NOT_FOUND)
    check_terminal(driver["status"], ["TERMINATED"])
    if driver["provider_id"] != g.uid:
        raise ApiError(ERR_INVALID_STATE, "the acting provider does not employ this driver")
    body = body_json()
    starts_at = datetime_field(body, "starts_at")
    ends_at = datetime_field(body, "ends_at")

    prior_end = driver.get("duty_window_ends_at_dt")
    if prior_end is not None:
        buffered_end = prior_end + __import__("datetime").timedelta(minutes=1)
        # The buffer is inclusive and begins at the prior end instant, so a
        # candidate starting exactly at the prior end IS a violation.
        if starts_at < buffered_end and ends_at > prior_end:
            raise ApiError(
                ERR_DRIVER_HOURS_EXCEEDED,
                "the candidate interval intersects the guard buffer after the prior duty interval",
            )

    driver["duty_window_starts_at"] = iso_now(starts_at)
    driver["duty_window_ends_at"] = iso_now(ends_at)
    driver["duty_window_ends_at_dt"] = ends_at
    db.touch("Driver", driver)
    db.duty_shift_seq += 1
    shift = {
        "driver_id": driver["id"],
        "shift_id": str(__import__("uuid").uuid4()),
        "starts_at": iso_now(starts_at),
        "ends_at": iso_now(ends_at),
        "overlap_guard_minutes": calc.DRIVER_GUARD_MINUTES,
    }
    db.insert("DutyShift", shift)
    return success(_serialize("DutyShift", shift), status=201)


@api.route("/drivers/<row_id>/duty-shifts", methods=["GET"])
@protected([AM, CO, SP])
def list_duty_shifts(row_id):
    driver = _get("Driver", row_id, ERR_DRIVER_NOT_FOUND)
    shifts = [s for s in db.all("DutyShift") if s["driver_id"] == row_id]
    shifts.sort(key=lambda s: (s["starts_at"], s.get("_seq", 0)))
    payload = [{k: v for k, v in s.items() if not k.startswith("_")} for s in shifts]
    return _result({"driver_id": driver["id"], "shifts": payload})


# ===========================================================================
# Insurance policies
# ===========================================================================

@api.route("/insurance-policies", methods=["POST"])
@protected([SP])
def create_insurance_policy():
    body = body_json()
    provider_id = string_field(body, "provider_id")
    policy_type = enum_field(body, "policy_type", {"AUTO_LIABILITY", "CARGO", "GENERAL_LIABILITY"})
    coverage = int_field(body, "coverage_cents", minimum=0)
    expires_at = datetime_field(body, "expires_at")
    _get("ServiceProvider", provider_id, ERR_PROVIDER_NOT_FOUND)

    row = {
        "provider_id": provider_id,
        "policy_type": policy_type,
        "coverage_cents": coverage,
        "expires_at": iso_now(expires_at),
        "expires_at_dt": expires_at,
        "verified_by": None,
        "status": "SUBMITTED",
    }
    db.insert("InsurancePolicy", row)
    _typed(row, "InsurancePolicy")
    return success(_serialize("InsurancePolicy", row), status=201)


@api.route("/insurance-policies", methods=["GET"])
@protected([AM, CO, SP])
def list_insurance_policies():
    rows = _filtered("InsurancePolicy", {
        "provider_id": request.args.get("provider_id"),
        "status": request.args.get("status"),
    })
    return _paginated_response("InsurancePolicy", rows, request.args)


@api.route("/insurance-policies/<row_id>", methods=["GET"])
@protected([AM, CO, SP])
def get_insurance_policy(row_id):
    row = find_row("InsurancePolicy", row_id, ERR_INVALID_REQUEST)
    return _result(_serialize("InsurancePolicy", row))


@api.route("/insurance-policies/<row_id>/verify", methods=["POST"])
@protected([CO])
def verify_insurance_policy(row_id):
    policy = find_row("InsurancePolicy", row_id, ERR_INVALID_REQUEST)
    check_terminal(policy["status"], ["EXPIRED", "REJECTED"])
    if policy["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "only a submitted certificate may be verified")
    policy["status"] = "VERIFIED"
    policy["verified_by"] = g.uid
    db.touch("InsurancePolicy", policy)
    return _result(_serialize("InsurancePolicy", policy))


# ===========================================================================
# Settlement periods
# ===========================================================================

@api.route("/settlement-periods", methods=["POST"])
@protected([SA])
def create_settlement_period():
    body = body_json()
    provider_id = string_field(body, "provider_id")
    area_id = string_field(body, "service_area_id")
    week_start = datetime_field(body, "week_start_at")
    is_peak_week = bool_field(body, "is_peak_week", default=False)
    fuel_rate = int_field(body, "fuel_rate_cents_per_mile", minimum=0)

    provider = _get("ServiceProvider", provider_id, ERR_PROVIDER_NOT_FOUND)
    _get("ServiceArea", area_id, ERR_SERVICE_AREA_NOT_FOUND)
    _check_occ("ServiceProvider", provider, body, "expected_provider_version")

    row = {
        "provider_id": provider_id,
        "service_area_id": area_id,
        "week_start_at": iso_now(week_start),
        "week_start_at_dt": week_start,
        "is_peak_week": is_peak_week,
        "fuel_rate_cents_per_mile": fuel_rate,
        "base_gross_cents": 0,
        "net_amount_cents": 0,
        "performance_multiplier": 1.0,
        "over_cap_allowed": False,
        "status": "OPEN",
    }
    db.insert("SettlementPeriod", row)
    _typed(row, "SettlementPeriod")
    db.touch("ServiceProvider", provider)
    return success(_serialize("SettlementPeriod", row), status=201)


@api.route("/settlement-periods", methods=["GET"])
@protected([AM, SA, SP])
def list_settlement_periods():
    rows = _filtered("SettlementPeriod", {
        "provider_id": request.args.get("provider_id"),
        "service_area_id": request.args.get("service_area_id"),
        "status": request.args.get("status"),
    })
    return _paginated_response("SettlementPeriod", rows, request.args)


@api.route("/settlement-periods/<row_id>", methods=["GET"])
@protected([AM, SA, SP])
def get_settlement_period(row_id):
    row = _get("SettlementPeriod", row_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    return _result(_serialize("SettlementPeriod", row))


@api.route("/settlement-periods/<row_id>/stop-observations", methods=["POST"])
@protected([SA, SP])
def create_stop_observation(row_id):
    period = _get("SettlementPeriod", row_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    check_transition(period["status"], ["OPEN", "ACCRUAL_CLOSED"], svc.PERIOD_TERMINAL)
    body = body_json()
    observed_date = datetime_field(body, "observed_date")
    recorded_at = datetime_field(body, "recorded_at")
    stops = int_field(body, "stops_count", minimum=0)
    packages = int_field(body, "packages_count", minimum=0)
    miles = int_field(body, "miles_driven", minimum=0)
    accessorial = int_field(body, "accessorial_cents", minimum=0)

    row = {
        "settlement_period_id": period["id"],
        "observed_date": iso_now(observed_date),
        "observed_date_dt": observed_date,
        "recorded_at": iso_now(recorded_at),
        "recorded_at_dt": recorded_at,
        "stops_count": stops,
        "packages_count": packages,
        "miles_driven": miles,
        "accessorial_cents": accessorial,
    }
    db.insert("StopObservation", row)
    _typed(row, "StopObservation")
    return success(_serialize("StopObservation", row), status=201)


@api.route("/settlement-periods/<row_id>/stop-observations", methods=["GET"])
@protected([AM, SA, SP])
def list_stop_observations(row_id):
    _get("SettlementPeriod", row_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    rows = [o for o in db.all("StopObservation") if o["settlement_period_id"] == row_id]
    rows.sort(key=lambda o: (o["recorded_at"], o["created_at"], o.get("_seq", 0)))
    return _paginated_response("StopObservation", rows, request.args)


@api.route("/settlement-periods/<row_id>/deductions", methods=["POST"])
@protected([SA])
def create_deduction(row_id):
    period = _get("SettlementPeriod", row_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    check_transition(period["status"], ["OPEN", "ACCRUAL_CLOSED"], svc.PERIOD_TERMINAL)
    body = body_json()
    deduction_type = enum_field(body, "deduction_type", {"FUEL", "MAINTENANCE", "ACCESSORIAL", "CHARGEBACK"})
    amount = int_field(body, "amount_cents", minimum=0)
    eligible = bool_field(body, "performance_factor_eligible", default=True)
    category = body.get("chargeback_category")
    if deduction_type == "CHARGEBACK":
        category = enum_field(body, "chargeback_category", {"DAMAGE", "MISSED_PICKUP", "EQUIPMENT"})
    else:
        if category is not None:
            raise ApiError(ERR_INVALID_REQUEST,
                           "chargeback_category is only valid on a CHARGEBACK deduction")

    row = {
        "settlement_period_id": period["id"],
        "deduction_type": deduction_type,
        "amount_cents": amount,
        "chargeback_category": category,
        "performance_factor_eligible": eligible,
    }
    db.insert("SettlementDeduction", row)
    _typed(row, "SettlementDeduction")
    return success(_serialize("SettlementDeduction", row), status=201)


@api.route("/settlement-periods/<row_id>/deductions", methods=["GET"])
@protected([AM, SA, SP])
def list_deductions(row_id):
    _get("SettlementPeriod", row_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    rows = [d for d in db.all("SettlementDeduction") if d["settlement_period_id"] == row_id]
    rows.sort(key=lambda d: (d["created_at"], d.get("_seq", 0)))
    return _paginated_response("SettlementDeduction", rows, request.args)


@api.route("/settlement-periods/<row_id>/disputes", methods=["GET"])
@protected([AM, SA, SP])
def list_period_disputes(row_id):
    _get("SettlementPeriod", row_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    rows = [d for d in db.all("Dispute") if d["settlement_period_id"] == row_id]
    rows.sort(key=lambda d: (d["created_at"], d.get("_seq", 0)))
    return _paginated_response("Dispute", rows, request.args)


@api.route("/settlement-periods/<row_id>/chargeback-claims", methods=["GET"])
@protected([AM, SA, SP])
def list_period_claims(row_id):
    _get("SettlementPeriod", row_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    rows = _filtered("ChargebackClaim", {"settlement_period_id": row_id})
    return _paginated_response("ChargebackClaim", rows, request.args)


@api.route("/settlement-periods/<row_id>/summary", methods=["GET"])
@protected([AM, SA, SP])
def settlement_summary(row_id):
    period = _get("SettlementPeriod", row_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    # Provisional read: it refreshes the derived totals with the week's stored
    # multiplier and leaves the segment cap to the reconcile pass.
    calc.compute_gross_settlement(period, resolve=False)
    summary = calc.summary_breakdown(period)
    db.touch("SettlementPeriod", period)
    return _result(summary)


@api.route("/settlement-periods/<row_id>/close-accrual", methods=["POST"])
@protected([SA])
def close_accrual(row_id):
    period = _get("SettlementPeriod", row_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    check_transition(period["status"], ["OPEN", "ACCRUAL_CLOSED"], svc.PERIOD_TERMINAL)
    svc.period_close_accrual(period)
    return _result(_serialize("SettlementPeriod", period))


@api.route("/settlement-periods/<row_id>/reconcile", methods=["POST"])
@protected([SA])
def reconcile_period(row_id):
    period = _get("SettlementPeriod", row_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    check_transition(period["status"], ["ACCRUAL_CLOSED"], svc.PERIOD_TERMINAL)
    body = body_json()
    allow_over_cap = bool_field(body, "allow_over_cap", default=False)
    deduction_order = body.get("deduction_order")
    if deduction_order is not None and not isinstance(deduction_order, str):
        raise ApiError(ERR_INVALID_REQUEST, "deduction_order must be a string")
    svc.period_reconcile(period, allow_over_cap=allow_over_cap, deduction_order=deduction_order)
    return _result(_serialize("SettlementPeriod", period))


@api.route("/settlement-periods/<row_id>/dispute", methods=["POST"])
@protected([SP])
def dispute_period(row_id):
    period = _get("SettlementPeriod", row_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    check_transition(period["status"], ["RECONCILED"], svc.PERIOD_TERMINAL)
    if period["provider_id"] != g.uid:
        raise ApiError(ERR_INVALID_STATE, "the acting provider is not named on this settlement scope")
    body = body_json()
    reason = enum_field(body, "reason_code", {"STOP_COUNT", "FUEL_RATE", "ACCESSORIAL", "DEDUCTION", "CHARGEBACK"})
    disputed_amount = int_field(body, "disputed_amount_cents", minimum=0)
    if not db.clock < calc.week_end(period) + __import__("datetime").timedelta(days=90):
        raise ApiError(ERR_DISPUTE_WINDOW_EXPIRED)

    opened = db.clock
    row = {
        "settlement_period_id": period["id"],
        "filed_by_role": "ServiceProvider",
        "disputed_amount_cents": disputed_amount,
        "reason_code": reason,
        "rounds_used": 0,
        "opened_at": iso_now(opened),
        "expires_at": iso_now(opened + __import__("datetime").timedelta(days=90)),
        "status": "OPEN",
    }
    db.insert("Dispute", row)
    _typed(row, "Dispute")
    period["status"] = "DISPUTED"
    db.touch("SettlementPeriod", period)
    return success(_serialize("Dispute", row), status=201)


@api.route("/settlement-periods/<row_id>/release", methods=["POST"])
@protected([AM])
def release_period(row_id):
    period = _get("SettlementPeriod", row_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    check_transition(period["status"], ["RECONCILED", "DISPUTED"], svc.PERIOD_TERMINAL)
    svc.period_release(period)
    return _result(_serialize("SettlementPeriod", period))


# ===========================================================================
# Performance metrics
# ===========================================================================

@api.route("/performance-metrics", methods=["POST"])
@protected([SA])
def create_metric():
    body = body_json()
    provider_id = string_field(body, "provider_id")
    service = number_field(body, "service_score", minimum=0, maximum=100)
    safety = number_field(body, "safety_score", minimum=0, maximum=100)
    cx = number_field(body, "customer_experience_score", minimum=0, maximum=100)
    _get("ServiceProvider", provider_id, ERR_PROVIDER_NOT_FOUND)

    row = {
        "provider_id": provider_id,
        "service_score": service,
        "safety_score": safety,
        "customer_experience_score": cx,
        "composite_score": None,
        "renewal_recommendation": None,
    }
    db.insert("PerformanceMetric", row)
    _typed(row, "PerformanceMetric")
    return success(_serialize("PerformanceMetric", row), status=201)


@api.route("/performance-metrics", methods=["GET"])
@protected([AM, SA, CO, SP])
def list_metrics():
    rows = _filtered("PerformanceMetric", {"provider_id": request.args.get("provider_id")})
    return _paginated_response("PerformanceMetric", rows, request.args)


@api.route("/performance-metrics/<row_id>", methods=["GET"])
@protected([AM, SA, CO, SP])
def get_metric(row_id):
    row = find_row("PerformanceMetric", row_id, ERR_INVALID_REQUEST)
    return _result(_serialize("PerformanceMetric", row))


@api.route("/performance-metrics/<row_id>/compose", methods=["POST"])
@protected([SA])
def compose_metric(row_id):
    metric = find_row("PerformanceMetric", row_id, ERR_INVALID_REQUEST)
    calc.compose_metric(metric)
    provider = db.get("ServiceProvider", metric["provider_id"])
    # The safety cascade writes safety_index onto the provider, so this is a
    # modification of the provider row: refresh updated_at and bump version.
    provider["safety_index"] = float(metric["safety_score"])
    db.touch("PerformanceMetric", metric)
    demoted = False
    if metric["composite_score"] < 50.00:
        if provider["status"] == "APPROVED":
            provider["status"] = "UNDER_REVIEW"
            demoted = True
        elif provider["status"] == "UNDER_REVIEW" and metric["composite_score"] < 65.00:
            svc.provider_suspend(provider)
            demoted = True
    elif provider["status"] == "UNDER_REVIEW" and metric["composite_score"] < 65.00:
        svc.provider_suspend(provider)
        demoted = True
    if not demoted:
        db.touch("ServiceProvider", provider)
    return _result(_serialize("PerformanceMetric", metric))


# ===========================================================================
# Chargeback claims
# ===========================================================================

@api.route("/chargeback-claims", methods=["POST"])
@protected([AM])
def create_claim():
    body = body_json()
    provider_id = string_field(body, "provider_id")
    period_id = string_field(body, "settlement_period_id")
    claim_type = enum_field(body, "claim_type", {"DAMAGE", "MISSED_PICKUP", "EQUIPMENT"})
    amount = int_field(body, "amount_cents", minimum=1)
    recovery_rate = number_field(body, "recovery_rate_pct", default=0, required=False, minimum=0, maximum=100)
    vehicle_id = body.get("vehicle_id")

    _get("ServiceProvider", provider_id, ERR_PROVIDER_NOT_FOUND)
    _get("SettlementPeriod", period_id, ERR_SETTLEMENT_PERIOD_NOT_FOUND)
    if vehicle_id is not None:
        resolve_body_fk("Vehicle", vehicle_id, ERR_VEHICLE_NOT_FOUND, "vehicle_id")

    row = {
        "provider_id": provider_id,
        "settlement_period_id": period_id,
        "vehicle_id": vehicle_id,
        "claim_type": claim_type,
        "amount_cents": amount,
        "net_of_recovery_cents": None,
        "recovery_rate_pct": recovery_rate or 0,
        "status": "FILED",
    }
    db.insert("ChargebackClaim", row)
    _typed(row, "ChargebackClaim")
    return success(_serialize("ChargebackClaim", row), status=201)


@api.route("/chargeback-claims", methods=["GET"])
@protected([AM, SA, SP])
def list_claims():
    rows = _filtered("ChargebackClaim", {
        "provider_id": request.args.get("provider_id"),
        "status": request.args.get("status"),
    })
    return _paginated_response("ChargebackClaim", rows, request.args)


@api.route("/chargeback-claims/<row_id>", methods=["GET"])
@protected([AM, SA, SP])
def get_claim(row_id):
    row = _get("ChargebackClaim", row_id, ERR_CHARGEBACK_CLAIM_NOT_FOUND)
    return _result(_serialize("ChargebackClaim", row))


@api.route("/chargeback-claims/<row_id>/approve", methods=["POST"])
@protected([AM])
def approve_claim(row_id):
    claim = _get("ChargebackClaim", row_id, ERR_CHARGEBACK_CLAIM_NOT_FOUND)
    check_transition(claim["status"], ["FILED"], svc.CLAIM_TERMINAL)
    svc.claim_approve(claim)
    return _result(_serialize("ChargebackClaim", claim))


@api.route("/chargeback-claims/<row_id>/settle", methods=["POST"])
@protected([AM])
def settle_claim(row_id):
    claim = _get("ChargebackClaim", row_id, ERR_CHARGEBACK_CLAIM_NOT_FOUND)
    check_transition(claim["status"], ["APPROVED"], svc.CLAIM_TERMINAL)
    svc.claim_settle(claim)
    return _result(_serialize("ChargebackClaim", claim))


@api.route("/chargeback-claims/<row_id>/reject", methods=["POST"])
@protected([AM])
def reject_claim(row_id):
    claim = _get("ChargebackClaim", row_id, ERR_CHARGEBACK_CLAIM_NOT_FOUND)
    check_transition(claim["status"], ["FILED"], svc.CLAIM_TERMINAL)
    svc.claim_reject(claim)
    return _result(_serialize("ChargebackClaim", claim))


# ===========================================================================
# Disputes
# ===========================================================================

@api.route("/disputes/<row_id>/submit-evidence", methods=["POST"])
@protected([SP])
def dispute_submit_evidence(row_id):
    dispute = _get("Dispute", row_id, ERR_DISPUTE_NOT_FOUND)
    check_transition(dispute["status"], ["OPEN"], svc.DISPUTE_TERMINAL)
    dispute["status"] = "EVIDENCE_SUBMITTED"
    db.touch("Dispute", dispute)
    return _result(_serialize("Dispute", dispute))


@api.route("/disputes/<row_id>/counter", methods=["POST"])
@protected([SA])
def dispute_counter(row_id):
    dispute = _get("Dispute", row_id, ERR_DISPUTE_NOT_FOUND)
    check_transition(dispute["status"], ["EVIDENCE_SUBMITTED"], svc.DISPUTE_TERMINAL)
    body = body_json()
    amount = int_field(body, "counter_amount_cents", minimum=0)
    svc.dispute_counter(dispute, amount)
    return _result(_serialize("Dispute", dispute))


@api.route("/disputes/<row_id>/resubmit-evidence", methods=["POST"])
@protected([SP])
def dispute_resubmit(row_id):
    dispute = _get("Dispute", row_id, ERR_DISPUTE_NOT_FOUND)
    check_transition(dispute["status"], ["COUNTERED"], svc.DISPUTE_TERMINAL)
    svc.dispute_resubmit(dispute)
    return _result(_serialize("Dispute", dispute))


@api.route("/disputes/<row_id>/escalate", methods=["POST"])
@protected([SA])
def dispute_escalate(row_id):
    dispute = _get("Dispute", row_id, ERR_DISPUTE_NOT_FOUND)
    check_transition(dispute["status"], ["COUNTERED"], svc.DISPUTE_TERMINAL)
    if db.clock < parse_iso(dispute["opened_at"]):
        raise ApiError(ERR_INVALID_STATE, "the logical clock has not reached opened_at")
    dispute["status"] = "ESCALATED"
    db.touch("Dispute", dispute)
    return _result(_serialize("Dispute", dispute))


@api.route("/disputes/<row_id>/resolve", methods=["POST"])
@protected([SA, AM])
def dispute_resolve(row_id):
    dispute = _get("Dispute", row_id, ERR_DISPUTE_NOT_FOUND)
    if dispute["status"] == "EVIDENCE_SUBMITTED" and g.role == SA:
        pass
    elif dispute["status"] == "ESCALATED" and g.role == AM:
        pass
    else:
        check_transition(dispute["status"], ["EVIDENCE_SUBMITTED", "ESCALATED"], svc.DISPUTE_TERMINAL)
        raise ApiError(ERR_INVALID_STATE,
                       "this role may not resolve a dispute in its current status")
    dispute["status"] = "RESOLVED"
    db.touch("Dispute", dispute)
    return _result(_serialize("Dispute", dispute))


@api.route("/disputes/<row_id>/withdraw", methods=["POST"])
@protected([SP])
def dispute_withdraw(row_id):
    dispute = _get("Dispute", row_id, ERR_DISPUTE_NOT_FOUND)
    check_transition(dispute["status"], ["OPEN", "COUNTERED"], svc.DISPUTE_TERMINAL)
    svc.dispute_withdraw(dispute)
    return _result(_serialize("Dispute", dispute))


# ===========================================================================
# Peak-season declarations
# ===========================================================================

@api.route("/peak-season-declarations", methods=["POST"])
@protected([AM])
def create_declaration():
    body = body_json()
    area_id = string_field(body, "service_area_id")
    code = string_field(body, "declaration_code")
    starts_on = datetime_field(body, "starts_on")
    ends_on = datetime_field(body, "ends_on")
    authorized_vehicles = int_field(body, "authorized_vehicles", minimum=0)
    authorized_drivers = int_field(body, "authorized_drivers", minimum=0)
    _get("ServiceArea", area_id, ERR_SERVICE_AREA_NOT_FOUND)

    row = {
        "service_area_id": area_id,
        "declaration_code": code,
        "starts_on": iso_now(starts_on),
        "starts_on_dt": starts_on,
        "ends_on": iso_now(ends_on),
        "ends_on_dt": ends_on,
        "authorized_vehicles": authorized_vehicles,
        "authorized_drivers": authorized_drivers,
        "status": "DECLARED",
    }
    db.insert("PeakSeasonDeclaration", row)
    _typed(row, "PeakSeasonDeclaration")
    return success(_serialize("PeakSeasonDeclaration", row), status=201)


@api.route("/peak-season-declarations", methods=["GET"])
@protected([AM, SA, SP])
def list_declarations():
    rows = _filtered("PeakSeasonDeclaration", {
        "service_area_id": request.args.get("service_area_id"),
        "status": request.args.get("status"),
    })
    return _paginated_response("PeakSeasonDeclaration", rows, request.args)


@api.route("/peak-season-declarations/<row_id>", methods=["GET"])
@protected([AM, SA, SP])
def get_declaration(row_id):
    row = _get("PeakSeasonDeclaration", row_id, ERR_PEAK_DECLARATION_NOT_FOUND)
    return _result(_serialize("PeakSeasonDeclaration", row))


@api.route("/peak-season-declarations/<row_id>/activate", methods=["POST"])
@protected([AM])
def activate_declaration(row_id):
    declaration = _get("PeakSeasonDeclaration", row_id, ERR_PEAK_DECLARATION_NOT_FOUND)
    check_transition(declaration["status"], ["DECLARED"], svc.DECLARATION_TERMINAL)
    svc.declaration_activate(declaration)
    return _result(_serialize("PeakSeasonDeclaration", declaration))


@api.route("/peak-season-declarations/<row_id>/end", methods=["POST"])
@protected([AM])
def end_declaration(row_id):
    declaration = _get("PeakSeasonDeclaration", row_id, ERR_PEAK_DECLARATION_NOT_FOUND)
    check_transition(declaration["status"], ["ACTIVE"], svc.DECLARATION_TERMINAL)
    svc.declaration_end(declaration)
    return _result(_serialize("PeakSeasonDeclaration", declaration))


@api.route("/peak-season-declarations/<row_id>/cancel", methods=["POST"])
@protected([AM])
def cancel_declaration(row_id):
    declaration = _get("PeakSeasonDeclaration", row_id, ERR_PEAK_DECLARATION_NOT_FOUND)
    check_transition(declaration["status"], ["DECLARED"], svc.DECLARATION_TERMINAL)
    declaration["status"] = "CANCELED"
    db.touch("PeakSeasonDeclaration", declaration)
    return _result(_serialize("PeakSeasonDeclaration", declaration))


# ===========================================================================
# Fuel index rates
# ===========================================================================

@api.route("/fuel-index-rates", methods=["POST"])
@protected([PA])
def create_fuel_index_rate():
    body = body_json()
    state_code = string_field(body, "region_state_code")
    effective_on = datetime_field(body, "effective_on")
    rate = int_field(body, "rate_cents_per_mile", minimum=0)
    if len(state_code) != 2 or not state_code.isupper() or not state_code.isalpha():
        raise ApiError(ERR_INVALID_REQUEST, "region_state_code must be two uppercase letters")

    row = {
        "region_state_code": state_code,
        "effective_on": iso_now(effective_on),
        "effective_on_dt": effective_on,
        "rate_cents_per_mile": rate,
        "published_by": g.uid,
    }
    db.insert("FuelIndexRate", row)
    _typed(row, "FuelIndexRate")
    return success(_serialize("FuelIndexRate", row), status=201)


@api.route("/fuel-index-rates", methods=["GET"])
@protected([AM, SA, PA, SP])
def list_fuel_index_rates():
    rows = _filtered("FuelIndexRate", {"region_state_code": request.args.get("region_state_code")})
    return _paginated_response("FuelIndexRate", rows, request.args)


@api.route("/fuel-index-rates/<row_id>", methods=["GET"])
@protected([AM, SA, PA, SP])
def get_fuel_index_rate(row_id):
    row = find_row("FuelIndexRate", row_id, ERR_INVALID_REQUEST)
    return _result(_serialize("FuelIndexRate", row))


# ===========================================================================
# Logical clock
# ===========================================================================

@api.route("/_clock/set_current_utc", methods=["POST"])
@protected([PA])
def set_current_utc():
    body = body_json()
    to_iso = body.get("to_iso8601")
    target = parse_iso(to_iso)
    previous = db.clock
    db.clock = target
    return _result({"current_utc": iso_now(db.clock), "previous_utc": iso_now(previous)})


@api.route("/_clock/current_utc", methods=["GET"])
@protected([PA])
def current_utc():
    return _result({"current_utc": iso_now(db.clock)})


# ===========================================================================
# Provider reverse lookups
# ===========================================================================

@api.route("/service-providers/<row_id>/service-areas", methods=["GET"])
@protected([AM, SA, CO, SP])
def provider_service_areas(row_id):
    _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    rows = [a for a in db.all("ServiceArea") if a.get("assigned_provider_id") == row_id]
    return _paginated_response("ServiceArea", rows, request.args)


@api.route("/service-providers/<row_id>/route-assignments", methods=["GET"])
@protected([AM, SA, SP])
def provider_route_assignments(row_id):
    _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    rows = [a for a in db.all("RouteAssignment")
            if a["provider_id"] == row_id or a.get("acquiring_provider_id") == row_id]
    return _paginated_response("RouteAssignment", rows, request.args)


@api.route("/service-providers/<row_id>/agreements", methods=["GET"])
@protected([AM, SA, SP])
def provider_agreements(row_id):
    _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    rows = _filtered("Agreement", {"provider_id": row_id})
    return _paginated_response("Agreement", rows, request.args)


@api.route("/service-providers/<row_id>/vehicles", methods=["GET"])
@protected([AM, CO, SP])
def provider_vehicles(row_id):
    _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    rows = _filtered("Vehicle", {"provider_id": row_id})
    return _paginated_response("Vehicle", rows, request.args)


@api.route("/service-providers/<row_id>/drivers", methods=["GET"])
@protected([AM, CO, SP])
def provider_drivers(row_id):
    _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    rows = _filtered("Driver", {"provider_id": row_id})
    return _paginated_response("Driver", rows, request.args)


@api.route("/service-providers/<row_id>/insurance-policies", methods=["GET"])
@protected([AM, CO, SP])
def provider_policies(row_id):
    _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    rows = _filtered("InsurancePolicy", {"provider_id": row_id})
    return _paginated_response("InsurancePolicy", rows, request.args)


@api.route("/service-providers/<row_id>/settlement-periods", methods=["GET"])
@protected([AM, SA, SP])
def provider_periods(row_id):
    _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    rows = _filtered("SettlementPeriod", {"provider_id": row_id})
    return _paginated_response("SettlementPeriod", rows, request.args)


@api.route("/service-providers/<row_id>/performance-metrics", methods=["GET"])
@protected([AM, SA, CO, SP])
def provider_metrics(row_id):
    _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    rows = _filtered("PerformanceMetric", {"provider_id": row_id})
    return _paginated_response("PerformanceMetric", rows, request.args)


@api.route("/service-providers/<row_id>/chargeback-claims", methods=["GET"])
@protected([AM, SA, SP])
def provider_claims(row_id):
    _get("ServiceProvider", row_id, ERR_PROVIDER_NOT_FOUND)
    rows = _filtered("ChargebackClaim", {"provider_id": row_id})
    return _paginated_response("ChargebackClaim", rows, request.args)