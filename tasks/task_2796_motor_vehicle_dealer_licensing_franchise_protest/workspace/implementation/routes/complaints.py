"""Consumer complaints, sanctions and the restitution ledger (PRD 3.9)."""

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

bp = Blueprint("complaints", __name__)

READ_ROLES = ["BoardAdmin", "ComplaintInvestigator", "LicensingAnalyst", "Dealer"]
NO_VIOLATION_FOUND = "NO_VIOLATION_FOUND"


def _find(record_id):
    record = db.get("consumer_complaint", record_id)
    if record is None:
        raise ApiError("ERR_COMPLAINT_NOT_FOUND", "No such consumer complaint")
    return record


@bp.post("/consumer-complaints")
def intake_complaint():
    guard(["ComplaintInvestigator"])
    body = v.read_body()
    dealer_id = v.req_string(body, "dealer_id", 1, 100)
    complainant_name = v.req_string(body, "complainant_name", 1, 200)
    allegation_code = v.req_enum(body, "allegation_code", enums.ALLEGATION_CODES)
    alleged_loss_cents = v.req_int(body, "alleged_loss_cents", 0)
    salesperson_id = v.opt_string(body, "salesperson_id", 1, 100)

    dealer = db.get("dealer", dealer_id)
    if dealer is None:
        raise ApiError("ERR_DEALER_NOT_FOUND", "No such dealership")
    salesperson = None
    if salesperson_id is not None:
        salesperson = db.get("salesperson", salesperson_id)
        if salesperson is None:
            raise ApiError("ERR_SALESPERSON_NOT_FOUND", "No such salesperson")
        if salesperson["sponsoring_dealer_id"] != dealer_id:
            raise ApiError(
                "ERR_SALESPERSON_DEALER_MISMATCH",
                "That salesperson is not sponsored by the dealership complained of",
            )

    record = db.insert("consumer_complaint", {
        "dealer_id": dealer_id,
        "salesperson_id": salesperson_id,
        "complainant_name": complainant_name,
        "allegation_code": allegation_code,
        "alleged_loss_cents": alleged_loss_cents,
        "status": "RECEIVED",
        "investigator_user_id": None,
        "findings_code": None,
        "substantiated": None,
        "sanction_type": None,
        "points_assessed": 0,
        "civil_penalty_cents": None,
        "restitution_ordered_cents": None,
        "restitution_paid_cents": 0,
        "restitution_due_on": None,
        "resolved_at": None,
    })
    derive.recompute_all()
    return response.object_response(serializers.consumer_complaint(record), 201)


@bp.post("/consumer-complaints/<record_id>/investigation")
def open_investigation(record_id):
    caller = guard(["ComplaintInvestigator"])
    body = v.read_body()
    findings_code = v.req_string(body, "findings_code", 1, 100)

    complaint = _find(record_id)
    if complaint["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE", "Only a RECEIVED complaint may be investigated")
    dealer = db.get("dealer", complaint["dealer_id"])
    if dealer is not None and dealer["license_status"] == "CANCELLED":
        raise ApiError("ERR_DEALER_LICENSE_NOT_ACTIVE", "The dealership's licence has been cancelled")

    complaint["findings_code"] = findings_code
    complaint["investigator_user_id"] = caller.user_id
    complaint["status"] = "UNDER_INVESTIGATION"
    db.touch(complaint)
    derive.recompute_all()
    return response.object_response(serializers.consumer_complaint(complaint), 200)


@bp.post("/consumer-complaints/<record_id>/resolution")
def resolve_complaint(record_id):
    caller = guard(["BoardAdmin"])
    complaint = _find(record_id)
    if complaint.get("investigator_user_id") is not None and (
        caller.user_id == complaint["investigator_user_id"]
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The investigator may not resolve its own file")

    body = v.read_body()
    substantiated = v.req_bool(body, "substantiated")
    sanction_type = v.opt_enum(body, "sanction_type", enums.SANCTION_TYPES)

    if complaint["status"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE", "Only a complaint under investigation may be resolved")
    if substantiated and complaint.get("findings_code") == NO_VIOLATION_FOUND:
        raise ApiError(
            "ERR_INVALID_COMPLAINT_STATE",
            "A substantiated resolution requires findings other than NO_VIOLATION_FOUND",
        )
    if substantiated and complaint["alleged_loss_cents"] <= 0:
        raise ApiError("ERR_LOSS_REQUIRED_FOR_SANCTION", "A sanction requires a loss greater than zero")
    if substantiated and sanction_type is None:
        raise ApiError("ERR_SANCTION_TYPE_NOT_ALLOWED", "sanction_type is required on a substantiated resolution")
    if not substantiated and sanction_type is not None:
        raise ApiError(
            "ERR_SANCTION_TYPE_NOT_ALLOWED",
            "sanction_type is not permitted on an unsubstantiated resolution",
        )

    dealer = db.get("dealer", complaint["dealer_id"])
    salesperson = db.get("salesperson", complaint.get("salesperson_id"))
    complaint["substantiated"] = substantiated

    if not substantiated:
        complaint["resolved_at"] = db.now()
        complaint["status"] = "CLOSED_UNSUBSTANTIATED"
        db.touch(complaint)
        derive.recompute_all()
        return response.object_response(serializers.consumer_complaint(complaint), 200)

    ordered = calc.restitution_ordered_cents(complaint["alleged_loss_cents"])
    complaint["sanction_type"] = sanction_type
    complaint["points_assessed"] = calc.SANCTION_POINTS[sanction_type]
    complaint["restitution_ordered_cents"] = ordered
    complaint["civil_penalty_cents"] = calc.civil_penalty_cents(
        sanction_type, complaint["allegation_code"], ordered
    )
    complaint["restitution_due_on"] = db.today() + calc._timedelta(calc.RESTITUTION_DUE_DAYS)
    complaint["restitution_paid_cents"] = 0
    complaint["status"] = "SANCTIONED"
    db.touch(complaint)

    if dealer is not None:
        cascade.apply_dealer_point_thresholds(dealer)
    cascade.advance_salesperson_discipline(salesperson)

    derive.recompute_all()
    return response.object_response(serializers.consumer_complaint(complaint), 200)


@bp.post("/consumer-complaints/<record_id>/restitution-payment")
def pay_restitution(record_id):
    caller = guard(["Dealer"])
    complaint = db.get("consumer_complaint", record_id)
    if complaint is not None:
        require_dealer_owner(caller, complaint["dealer_id"])
    complaint = _find(record_id)

    body = v.read_body()
    amount_cents = v.req_int(body, "amount_cents", 1)

    if complaint["status"] != "SANCTIONED":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE", "Only a SANCTIONED complaint accepts restitution")
    paid = complaint["restitution_paid_cents"] + amount_cents
    if paid > complaint["restitution_ordered_cents"]:
        raise ApiError("ERR_RESTITUTION_OVERPAYMENT", "The payment exceeds the outstanding balance")

    complaint["restitution_paid_cents"] = paid
    if paid == complaint["restitution_ordered_cents"]:
        complaint["resolved_at"] = db.now()
        complaint["status"] = "CLOSED_SATISFIED"
    db.touch(complaint)

    dealer = db.get("dealer", complaint["dealer_id"])
    if dealer is not None:
        derive.set_counter(
            dealer, "restitution_outstanding_cents", derive.restitution_outstanding_cents(dealer["id"])
        )
        db.touch(dealer)
        if complaint["status"] == "CLOSED_SATISFIED":
            cascade.restore_dealer_after_settlement(dealer)

    derive.recompute_all()
    return response.object_response(serializers.consumer_complaint(complaint), 200)


@bp.get("/consumer-complaints/<record_id>")
def read_complaint(record_id):
    guard(READ_ROLES)
    return response.object_response(serializers.consumer_complaint(_find(record_id)), 200)


@bp.get("/consumer-complaints")
def list_complaints():
    guard(READ_ROLES)
    dealer_id = v.query_string("dealer_id")
    salesperson_id = v.query_string("salesperson_id")
    status = v.query_enum("status", enums.COMPLAINT_STATUSES)
    allegation_code = v.query_enum("allegation_code", enums.ALLEGATION_CODES)
    limit, offset = response.read_pagination(request.args)
    rows = [
        row for row in db.ordered("consumer_complaint")
        if (dealer_id is None or row["dealer_id"] == dealer_id)
        and (salesperson_id is None or row["salesperson_id"] == salesperson_id)
        and (status is None or row["status"] == status)
        and (allegation_code is None or row["allegation_code"] == allegation_code)
    ]
    window, total = response.page(rows, limit, offset)
    return response.array_response(
        [serializers.consumer_complaint(row) for row in window], limit, offset, len(rows)
    )
