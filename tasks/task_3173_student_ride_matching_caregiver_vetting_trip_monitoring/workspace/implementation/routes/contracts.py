"""Contract endpoints: drafting and the DRAFT/ACTIVE/SUSPENDED/EXPIRED machine."""

import calculations as calc
import db
import models
import validators as v
from clock import clock_date, parse_date
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CONTRACT_DATE_ORDER,
    ERR_CONTRACT_OVERLAP,
    ERR_CONTRACT_TERM_ENDED,
    ERR_INVALID_STATE,
    ApiError,
    not_found,
)
from flask import Blueprint
from middleware import requires
from response import object_response

bp = Blueprint("contracts", __name__)

CONTRACT_INPUT = (
    "district_id", "effective_from", "through_date", "per_ride_rate_cents",
    "per_mile_rate_cents", "minimum_billable_cents", "billing_period",
)


def load_contract(contract_id):
    contract = db.get("contracts", contract_id)
    if contract is None:
        raise not_found("The addressed contract does not exist.")
    return contract


def _state_gate(current, required, msg):
    """Priority 9 with the terminal-lockdown distinction (PRD section 3.1).

    An EXPIRED contract is terminal, so every later suspension, reactivation or
    second activation is ERR_ALREADY_TERMINAL rather than ERR_INVALID_STATE.
    """
    if isinstance(required, str):
        required = (required,)
    if current in required:
        return
    if current == "EXPIRED":
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "The contract has already reached its terminal EXPIRED state.",
        )
    raise ApiError(ERR_INVALID_STATE, msg)


@bp.post("/student-rides/contracts")
@requires("DistrictAdmin", "PlatformAdmin")
def create_contract():
    data = v.body()
    v.reject_unknown(data, CONTRACT_INPUT)
    district_id = v.as_string(data, "district_id")
    if db.get("districts", district_id) is None:
        raise not_found("The addressed district does not exist.")

    contract = db.new_record({
        "district_id": district_id,
        "effective_from": v.as_iso_date_string(data, "effective_from"),
        "through_date": v.as_iso_date_string(data, "through_date"),
        "per_ride_rate_cents": v.as_int(data, "per_ride_rate_cents", required_field=True),
        "per_mile_rate_cents": v.as_int(data, "per_mile_rate_cents", required_field=True),
        "minimum_billable_cents": v.as_int(data, "minimum_billable_cents", default=0),
        "billing_period": v.enum_value("billing_period", v.required(data, "billing_period")),
        "status": "DRAFT",
    })
    db.save("contracts", contract)
    return object_response(models.contract_out(contract), 201)


@bp.get("/student-rides/contracts/<contract_id>")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def get_contract(contract_id):
    contract = load_contract(contract_id)
    return object_response(models.contract_out(contract))


@bp.post("/student-rides/contracts/<contract_id>/activate")
@requires("DistrictAdmin", "PlatformAdmin")
def activate_contract(contract_id):
    contract = load_contract(contract_id)
    district = db.get("districts", contract["district_id"])

    _state_gate(contract["status"], "DRAFT", "Only a DRAFT contract may be activated.")
    if parse_date(contract["effective_from"]) > parse_date(contract["through_date"]):
        raise ApiError(
            ERR_CONTRACT_DATE_ORDER,
            "effective_from must fall on or before through_date.",
        )
    for other in db.all_of("contracts"):
        if other["id"] == contract["id"] or other["district_id"] != contract["district_id"]:
            continue
        if other["status"] == "ACTIVE":
            raise ApiError(
                ERR_CONTRACT_OVERLAP,
                "Another contract for this district is already ACTIVE.",
            )

    contract["status"] = "ACTIVE"
    db.bump_version(contract)
    for other in db.all_of("contracts"):
        if other["id"] == contract["id"] or other["district_id"] != contract["district_id"]:
            continue
        if other["status"] == "DRAFT":
            other["status"] = "EXPIRED"
            db.bump_version(other)
    if district:
        district["account_status"] = "ACTIVE"
    return object_response(models.contract_out(contract))


@bp.post("/student-rides/contracts/<contract_id>/suspend")
@requires("DistrictAdmin", "PlatformAdmin")
def suspend_contract(contract_id):
    contract = load_contract(contract_id)
    district = db.get("districts", contract["district_id"])

    _state_gate(contract["status"], "ACTIVE", "Only an ACTIVE contract may be suspended.")

    contract["status"] = "SUSPENDED"
    db.bump_version(contract)
    if district:
        district["account_status"] = "SUSPENDED"
    # Every OPEN statement for the district becomes VOIDED, returning its
    # applied credit to the pool (PRD section 3.10).
    for statement in db.all_of("billing_statements"):
        if statement["district_id"] != contract["district_id"]:
            continue
        if statement["status"] == "OPEN":
            statement["status"] = "VOIDED"
            db.bump_version(statement)
            if district:
                district["credit_balance_cents"] = (
                    int(district.get("credit_balance_cents") or 0)
                    + int(statement.get("applied_credit_cents") or 0)
                )
    return object_response(models.contract_out(contract))


@bp.post("/student-rides/contracts/<contract_id>/reactivate")
@requires("DistrictAdmin", "PlatformAdmin")
def reactivate_contract(contract_id):
    contract = load_contract(contract_id)
    district = db.get("districts", contract["district_id"])

    _state_gate(contract["status"], "SUSPENDED", "Only a SUSPENDED contract may be reactivated.")
    if clock_date() > parse_date(contract["through_date"]):
        raise ApiError(
            ERR_CONTRACT_TERM_ENDED,
            "The contract term has ended and cannot be reactivated.",
        )

    contract["status"] = "ACTIVE"
    db.bump_version(contract)
    if district:
        district["account_status"] = "ACTIVE"
    return object_response(models.contract_out(contract))