"""Salesperson licensure, renewal and the discipline dimension (PRD 3.3)."""

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

bp = Blueprint("salespersons", __name__)

READ_ROLES = ["BoardAdmin", "LicensingAnalyst", "ComplaintInvestigator", "Dealer"]


def _find(record_id):
    record = db.get("salesperson", record_id)
    if record is None:
        raise ApiError("ERR_SALESPERSON_NOT_FOUND", "No such salesperson")
    return record


@bp.post("/salespersons")
def sponsor_salesperson():
    caller = guard(["Dealer"])
    peeked = v.peek_body()
    if isinstance(peeked.get("sponsoring_dealer_id"), str):
        require_dealer_owner(caller, peeked["sponsoring_dealer_id"])

    body = v.read_body()
    sponsoring_dealer_id = v.req_string(body, "sponsoring_dealer_id", 1, 100)
    full_name = v.req_string(body, "full_name", 1, 200)
    disclosed_prior_discipline = v.req_bool(body, "disclosed_prior_discipline")

    dealer = db.get("dealer", sponsoring_dealer_id)
    if dealer is None:
        raise ApiError("ERR_DEALER_NOT_FOUND", "No such dealership")
    if dealer["license_status"] != "LICENSED":
        raise ApiError("ERR_DEALER_LICENSE_NOT_ACTIVE", "Only a LICENSED dealership may sponsor an applicant")

    record = db.insert("salesperson", {
        "sponsoring_dealer_id": sponsoring_dealer_id,
        "full_name": full_name,
        "disclosed_prior_discipline": disclosed_prior_discipline,
        "license_status": "PENDING",
        "discipline_status": "CLEAR",
        "disciplinary_points": 0,
        "waiver_granted": False,
        "license_effective_on": None,
        "license_expires_on": None,
        "renewal_count": 0,
        "denial_reason_code": None,
    })
    derive.recompute_all()
    return response.object_response(serializers.salesperson(record), 201)


@bp.post("/salespersons/<record_id>/license-decision")
def decide_salesperson_license(record_id):
    guard(["LicensingAnalyst"])
    body = v.read_body()
    outcome = v.req_enum(body, "outcome", enums.DECISION_OUTCOMES)
    waiver_granted = v.opt_bool(body, "waiver_granted")
    denial_reason_code = v.opt_string(body, "denial_reason_code", 1, 500)
    if outcome == "DENIED" and denial_reason_code is None:
        raise ApiError("ERR_INVALID_REQUEST", "denial_reason_code is required when the decision denies")

    person = _find(record_id)
    if person["license_status"] not in ("PENDING", "RENEWAL_PENDING"):
        raise ApiError(
            "ERR_INVALID_SALESPERSON_STATE",
            "A salesperson in %s has no licence decision pending" % person["license_status"],
        )
    from_renewal = person["license_status"] == "RENEWAL_PENDING"
    dealer = db.get("dealer", person["sponsoring_dealer_id"])
    waived = waiver_granted is True

    if outcome == "APPROVED":
        if dealer is None or dealer["license_status"] != "LICENSED":
            if not waived:
                raise ApiError("ERR_SPONSOR_NOT_LICENSED", "The sponsoring dealership is not LICENSED")
        if not from_renewal:
            points = derive.salesperson_points(person["id"])
            if person["disclosed_prior_discipline"] is False and points > 0 and not waived:
                raise ApiError("ERR_UNDISCLOSED_DISCIPLINE", "Prior discipline was not disclosed")
        else:
            points = derive.salesperson_points(person["id"])
            if points >= calc.SALESPERSON_SUSPENSION_POINTS:
                raise ApiError("ERR_SALESPERSON_DISCIPLINE_BAR", "The rolling point total bars a renewal")

    if waiver_granted is not None:
        person["waiver_granted"] = waiver_granted

    if outcome == "APPROVED":
        if from_renewal:
            previous_expiry = person.get("license_expires_on")
            effective_on = (
                previous_expiry + calc._timedelta(1) if previous_expiry is not None else db.today()
            )
            person["renewal_count"] += 1
        else:
            effective_on = db.today()
        person["license_effective_on"] = effective_on
        person["license_expires_on"] = calc.salesperson_term_expiry(effective_on)
        person["license_status"] = "LICENSED"
    else:
        person["license_status"] = "DENIED"
        person["denial_reason_code"] = denial_reason_code
    db.touch(person)
    derive.recompute_all()
    return response.object_response(serializers.salesperson(person), 200)


@bp.post("/salespersons/<record_id>/renewal")
def renew_salesperson(record_id):
    caller = guard(["Dealer"])
    person = db.get("salesperson", record_id)
    if person is not None:
        require_dealer_owner(caller, person["sponsoring_dealer_id"])
    person = _find(record_id)
    v.read_body()

    if person["license_status"] != "LICENSED":
        raise ApiError("ERR_INVALID_SALESPERSON_STATE", "Only a LICENSED salesperson may be renewed")
    if derive.salesperson_points(person["id"]) >= calc.SALESPERSON_SUSPENSION_POINTS:
        raise ApiError("ERR_SALESPERSON_DISCIPLINE_BAR", "The rolling point total bars a renewal")

    reference = db.today()
    expires_on = person.get("license_expires_on")
    if expires_on is not None:
        if reference < expires_on - calc._timedelta(calc.RENEWAL_WINDOW_OPENS_DAYS_BEFORE):
            raise ApiError("ERR_RENEWAL_WINDOW_NOT_OPEN", "The renewal window has not opened yet")
        if reference > expires_on + calc._timedelta(calc.RENEWAL_GRACE_DAYS_AFTER):
            raise ApiError("ERR_RENEWAL_GRACE_EXPIRED", "The renewal grace period has expired")

    person["license_status"] = "RENEWAL_PENDING"
    db.touch(person)
    derive.recompute_all()
    return response.object_response(serializers.salesperson(person), 200)


@bp.get("/salespersons/<record_id>")
def read_salesperson(record_id):
    guard(READ_ROLES)
    return response.object_response(serializers.salesperson(_find(record_id)), 200)


@bp.get("/salespersons")
def list_salespersons():
    guard(READ_ROLES)
    sponsoring_dealer_id = v.query_string("sponsoring_dealer_id")
    license_status = v.query_enum("license_status", enums.SALESPERSON_LICENSE_STATUSES)
    discipline_status = v.query_enum("discipline_status", enums.DISCIPLINE_STATUSES)
    limit, offset = response.read_pagination(request.args)
    rows = [
        row for row in db.ordered("salesperson")
        if (sponsoring_dealer_id is None or row["sponsoring_dealer_id"] == sponsoring_dealer_id)
        and (license_status is None or row["license_status"] == license_status)
        and (discipline_status is None or row["discipline_status"] == discipline_status)
    ]
    window, total = response.page(rows, limit, offset)
    return response.array_response(
        [serializers.salesperson(row) for row in window], limit, offset, len(rows)
    )
