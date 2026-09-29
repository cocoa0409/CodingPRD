"""Dealer licensure: the revision loop and the board's decision (PRD 3.2)."""

from flask import Blueprint, request

import calc
import cascade
import db
import derive
import enums
import response
import serializers
import validation as v
from errors import ApiError
from middleware import guard, require_dealer_owner

bp = Blueprint("applications", __name__)

READ_ROLES = ["BoardAdmin", "LicensingAnalyst", "Dealer"]
LIVE_STATES = ("DRAFT", "SUBMITTED", "DEFICIENT")


def _find(record_id):
    record = db.get("license_application", record_id)
    if record is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", "No such licence application")
    return record


def _owned(caller, record_id):
    """Ownership precedes path existence only where the row resolves (PRD 2.10)."""
    record = db.get("license_application", record_id)
    if record is not None:
        require_dealer_owner(caller, record["dealer_id"])
    return _find(record_id)


def _rescan(application, dealer):
    codes = calc.sufficiency_scan(application, dealer)
    application["deficiency_codes"] = codes
    application["deficiency_count"] = len(codes)
    return codes


def _renewal_date_rules(application, dealer, reference_date):
    if application["application_type"] != "RENEWAL":
        return
    expires_on = dealer.get("license_expires_on")
    if expires_on is None:
        return
    if reference_date < expires_on - calc._timedelta(calc.RENEWAL_WINDOW_OPENS_DAYS_BEFORE):
        raise ApiError("ERR_RENEWAL_WINDOW_NOT_OPEN", "The renewal window has not opened yet")
    if reference_date > expires_on + calc._timedelta(calc.RENEWAL_GRACE_DAYS_AFTER):
        raise ApiError("ERR_RENEWAL_GRACE_EXPIRED", "The renewal grace period has expired")
    if application.get("requested_term_start_on") != expires_on + calc._timedelta(1):
        raise ApiError("ERR_TERM_NOT_CONTIGUOUS", "requested_term_start_on must abut the current term")


@bp.post("/license-applications")
def create_application():
    caller = guard(["Dealer", "BoardAdmin"])
    peeked = v.peek_body()
    if isinstance(peeked.get("dealer_id"), str):
        require_dealer_owner(caller, peeked["dealer_id"])

    body = v.read_body()
    dealer_id = v.req_string(body, "dealer_id", 1, 100)
    application_type = v.req_enum(body, "application_type", enums.APPLICATION_TYPES)
    facility_sqft = v.req_int(body, "facility_sqft", 0, 500000)
    display_spaces = v.req_int(body, "display_spaces", 0, 2000)
    service_bays = v.req_int(body, "service_bays", 0, 200)
    bond_amount_cents = v.req_int(body, "bond_amount_cents", 0)
    insurance_liability_cents = v.req_int(body, "insurance_liability_cents", 0)
    zoning = v.req_enum(body, "zoning_certificate_status", enums.ZONING_STATUSES)
    line_make_count = v.req_int(body, "line_make_count", 0, 12)
    requested_term_start_on = v.opt_date(body, "requested_term_start_on")
    relocation_x = v.opt_decimal(body, "relocation_site_x_km", -500, 500, 2)
    relocation_y = v.opt_decimal(body, "relocation_site_y_km", -500, 500, 2)
    new_owner_name = v.opt_string(body, "new_owner_name", 1, 200)

    if application_type == "RELOCATION" and (relocation_x is None or relocation_y is None):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "relocation_site_x_km and relocation_site_y_km are required for a RELOCATION",
        )
    if application_type == "CHANGE_OF_OWNERSHIP" and new_owner_name is None:
        raise ApiError("ERR_INVALID_REQUEST", "new_owner_name is required for a CHANGE_OF_OWNERSHIP")

    dealer = db.get("dealer", dealer_id)
    if dealer is None:
        raise ApiError("ERR_DEALER_NOT_FOUND", "No such dealership")

    for existing in db.where("license_application", dealer_id=dealer_id):
        if existing["application_type"] == application_type and existing["status"] in LIVE_STATES:
            raise ApiError(
                "ERR_OPEN_APPLICATION_EXISTS",
                "The dealership already holds a live %s application" % application_type,
            )

    record = db.insert("license_application", {
        "dealer_id": dealer_id,
        "application_type": application_type,
        "status": "DRAFT",
        "facility_sqft": facility_sqft,
        "display_spaces": display_spaces,
        "service_bays": service_bays,
        "bond_amount_cents": bond_amount_cents,
        "insurance_liability_cents": insurance_liability_cents,
        "zoning_certificate_status": zoning,
        "line_make_count": line_make_count,
        "requested_term_start_on": requested_term_start_on,
        "relocation_site_x_km": relocation_x,
        "relocation_site_y_km": relocation_y,
        "new_owner_name": new_owner_name,
        "deficiency_codes": [],
        "deficiency_count": 0,
        "fee_quoted_cents": None,
        "fee_total_cents": None,
        "fee_delta_cents": None,
        "resubmission_count": 0,
        "submitted_at": None,
        "decided_at": None,
        "decision_outcome": None,
        "denial_reason_code": None,
        "deficiency_note": None,
    })
    return response.object_response(serializers.license_application(record), 201)


@bp.post("/license-applications/<record_id>/submit")
def submit_application(record_id):
    caller = guard(["Dealer"])
    application = _owned(caller, record_id)
    if application["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_APPLICATION_STATE", "Only a DRAFT application may be submitted")
    dealer = db.get("dealer", application["dealer_id"])
    if dealer["license_status"] in ("REVOKED", "CANCELLED"):
        raise ApiError("ERR_DEALER_LICENSE_NOT_ACTIVE", "A revoked or cancelled dealership may not submit")

    reference_date = db.today()
    _renewal_date_rules(application, dealer, reference_date)

    application["submitted_at"] = db.now()
    application["status"] = "SUBMITTED"
    _rescan(application, dealer)
    application["fee_quoted_cents"] = calc.license_fee_cents(application, dealer, reference_date)
    db.touch(application)
    derive.recompute_all()
    return response.object_response(serializers.license_application(application), 200)


@bp.post("/license-applications/<record_id>/deficiency-notice")
def deficiency_notice(record_id):
    guard(["LicensingAnalyst"])
    body = v.read_body()
    note = v.req_string(body, "deficiency_note", 1, 2000)
    application = _find(record_id)
    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_APPLICATION_STATE", "Only a SUBMITTED application may be returned")
    if application["deficiency_count"] < 1:
        raise ApiError("ERR_INVALID_APPLICATION_STATE", "The application carries no deficiency")
    application["deficiency_note"] = note
    application["status"] = "DEFICIENT"
    db.touch(application)
    derive.recompute_all()
    return response.object_response(serializers.license_application(application), 200)


@bp.post("/license-applications/<record_id>/resubmit")
def resubmit_application(record_id):
    caller = guard(["Dealer"])
    application = _owned(caller, record_id)
    body = v.read_body()
    facility_sqft = v.opt_int(body, "facility_sqft", 0, 500000)
    display_spaces = v.opt_int(body, "display_spaces", 0, 2000)
    service_bays = v.opt_int(body, "service_bays", 0, 200)
    bond_amount_cents = v.opt_int(body, "bond_amount_cents", 0)
    insurance_liability_cents = v.opt_int(body, "insurance_liability_cents", 0)
    zoning = v.opt_enum(body, "zoning_certificate_status", enums.ZONING_STATUSES)
    line_make_count = v.opt_int(body, "line_make_count", 0, 12)

    if application["status"] != "DEFICIENT":
        raise ApiError("ERR_INVALID_APPLICATION_STATE", "Only a DEFICIENT application may be resubmitted")
    if application["resubmission_count"] >= 2:
        raise ApiError("ERR_RESUBMISSION_LIMIT_REACHED", "The revision loop is bounded at two resubmissions")

    supplied = {
        "facility_sqft": facility_sqft,
        "display_spaces": display_spaces,
        "service_bays": service_bays,
        "bond_amount_cents": bond_amount_cents,
        "insurance_liability_cents": insurance_liability_cents,
        "zoning_certificate_status": zoning,
        "line_make_count": line_make_count,
    }
    for field, value in supplied.items():
        if value is not None:
            application[field] = value

    dealer = db.get("dealer", application["dealer_id"])
    reference_date = db.today()
    application["resubmission_count"] += 1
    application["submitted_at"] = db.now()
    application["status"] = "SUBMITTED"
    _rescan(application, dealer)
    application["fee_quoted_cents"] = calc.license_fee_cents(application, dealer, reference_date)
    db.touch(application)
    derive.recompute_all()
    return response.object_response(serializers.license_application(application), 200)


@bp.post("/license-applications/<record_id>/decision")
def decide_application(record_id):
    guard(["BoardAdmin"])
    body = v.read_body()
    outcome = v.req_enum(body, "outcome", enums.DECISION_OUTCOMES)
    denial_reason_code = v.opt_string(body, "denial_reason_code", 1, 500)
    if outcome == "DENIED" and denial_reason_code is None:
        raise ApiError("ERR_INVALID_REQUEST", "denial_reason_code is required when the outcome denies")

    application = _find(record_id)
    admitted = ("SUBMITTED",) if outcome == "APPROVED" else ("SUBMITTED", "DEFICIENT")
    if application["status"] not in admitted:
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "An application in %s may not be %s" % (application["status"], outcome.lower()),
        )

    dealer = db.get("dealer", application["dealer_id"])
    reference_date = db.today()

    if outcome == "APPROVED":
        if _rescan(application, dealer):
            raise ApiError("ERR_APPLICATION_HAS_DEFICIENCIES", "The statutory minimums are not waivable")
        if dealer["license_status"] in ("SUSPENDED", "REVOKED", "CANCELLED"):
            raise ApiError("ERR_DEALER_LICENSE_NOT_ACTIVE", "The dealership's licence standing bars an approval")
        if dealer["restitution_outstanding_cents"] != 0:
            raise ApiError("ERR_DEALER_LICENSE_NOT_ACTIVE", "The dealership still owes restitution")
        if application["application_type"] == "RENEWAL" and dealer.get("license_expires_on") is not None:
            if application.get("requested_term_start_on") != dealer["license_expires_on"] + calc._timedelta(1):
                raise ApiError("ERR_TERM_NOT_CONTIGUOUS", "requested_term_start_on must abut the current term")

    application["decided_at"] = db.now()
    application["decision_outcome"] = outcome
    application["status"] = outcome
    application["fee_total_cents"] = calc.license_fee_cents(application, dealer, reference_date)
    quoted = application.get("fee_quoted_cents") or 0
    application["fee_delta_cents"] = application["fee_total_cents"] - quoted
    if outcome == "DENIED":
        application["denial_reason_code"] = denial_reason_code
    db.touch(application)

    if outcome == "APPROVED":
        was_licensed = dealer["license_status"] == "LICENSED"
        if application["application_type"] == "RENEWAL" and application.get("requested_term_start_on"):
            effective_on = application["requested_term_start_on"]
        else:
            effective_on = reference_date
        dealer["license_status"] = "LICENSED"
        dealer["suspension_reason"] = "NONE"
        dealer["license_effective_on"] = effective_on
        dealer["license_expires_on"] = calc.dealer_term_expiry(effective_on)
        if dealer["franchise_status"] == "NONE" and dealer["dealer_type"] == "NEW_MOTOR_VEHICLE":
            dealer["franchise_status"] = "FRANCHISED"
        if application["application_type"] == "RELOCATION":
            dealer["site_x_km"] = application["relocation_site_x_km"]
            dealer["site_y_km"] = application["relocation_site_y_km"]
        if application["application_type"] == "CHANGE_OF_OWNERSHIP":
            dealer["legal_name"] = application["new_owner_name"]
        db.touch(dealer)
        if not was_licensed:
            cascade.reinstate_sponsored_salespersons(dealer)

    derive.recompute_all()
    return response.object_response(serializers.license_application(application), 200)


@bp.get("/license-applications/<record_id>")
def read_application(record_id):
    guard(READ_ROLES)
    return response.object_response(serializers.license_application(_find(record_id)), 200)


@bp.get("/license-applications")
def list_applications():
    guard(READ_ROLES)
    dealer_id = v.query_string("dealer_id")
    status = v.query_enum("status", enums.APPLICATION_STATUSES)
    application_type = v.query_enum("application_type", enums.APPLICATION_TYPES)
    limit, offset = response.read_pagination(request.args)
    rows = [
        row for row in db.ordered("license_application")
        if (dealer_id is None or row["dealer_id"] == dealer_id)
        and (status is None or row["status"] == status)
        and (application_type is None or row["application_type"] == application_type)
    ]
    window, total = response.page(rows, limit, offset)
    return response.array_response(
        [serializers.license_application(row) for row in window], limit, offset, len(rows)
    )
