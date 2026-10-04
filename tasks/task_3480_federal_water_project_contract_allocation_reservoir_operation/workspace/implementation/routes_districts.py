"""Districts and WaterContracts (PRD section 3.1).

Validation order per PRD 2.9: auth -> role -> shape -> existence -> ownership ->
state -> safety -> business -> temporal -> referential -> fiscal.
"""
from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from calc import singleton_reservoir
from envelope import list_response, success
from errors import ApiError, not_found
from serial import contract_view, district_view
from store import DB, new_record, touch
from validate import as_enum, as_int_range, as_str, get_body, required

bp = Blueprint("districts_contracts", __name__)

PRIORITY_CLASSES = ("SENIOR", "JUNIOR")


def _q(name):
    return request.args.get(name)


@bp.post("/water/districts")
def create_district():
    authenticate(["SystemAdmin"])
    body = get_body()
    name = as_str(required(body, "name"), "name")
    acres = as_int_range(required(body, "service_area_acres"), "service_area_acres", 1)
    email = as_str(required(body, "contact_email"), "contact_email")
    rec = new_record()
    rec.update({
        "name": name,
        "service_area_acres": acres,
        "contact_email": email,
    })
    DB["districts"][rec["id"]] = rec
    return success(district_view(rec), 201)


@bp.get("/water/districts/<string:district_id>")
def get_district(district_id):
    authenticate(ALL_ROLES)
    district = DB["districts"].get(district_id)
    if district is None:
        not_found("District")
    return success(district_view(district))


@bp.post("/water/contracts")
def create_contract():
    authenticate(["SystemAdmin"])
    body = get_body()
    district_id = as_str(required(body, "district_id"), "district_id")
    contract_number = as_str(required(body, "contract_number"), "contract_number")
    priority_class = as_enum(required(body, "priority_class"), "priority_class",
                             PRIORITY_CLASSES)
    max_af = as_int_range(required(body, "max_annual_quantity_af"),
                          "max_annual_quantity_af", 1)
    obligation = as_int_range(required(body, "repayment_obligation_cents"),
                              "repayment_obligation_cents", 0)
    # existence: body FK in declared input order
    if district_id not in DB["districts"]:
        not_found("District")
    # business: unique contract_number
    for c in DB["contracts"].values():
        if c["contract_number"] == contract_number:
            raise ApiError("ERR_DUPLICATE_CONTRACT_NUMBER", 409,
                           "contract_number already in use")
    rec = new_record()
    rec.update({
        "district_id": district_id,
        "contract_number": contract_number,
        "priority_class": priority_class,
        "max_annual_quantity_af": max_af,
        "repayment_obligation_cents": obligation,
        "repaid_credits_cents": 0,
        "status": "ACTIVE",
    })
    DB["contracts"][rec["id"]] = rec
    # reservoir repayment totals recompute on read; the reservoir record mutated
    reservoir = singleton_reservoir()
    if reservoir is not None:
        touch(reservoir)
    return success(contract_view(rec), 201)


@bp.get("/water/contracts/<string:contract_id>")
def get_contract(contract_id):
    authenticate(ALL_ROLES)
    contract = DB["contracts"].get(contract_id)
    if contract is None:
        not_found("WaterContract")
    return success(contract_view(contract))


@bp.get("/water/contracts")
def list_contracts():
    authenticate(ALL_ROLES)
    filters = {
        "district_id": _q("district_id"),
        "status": _q("status"),
        "priority_class": _q("priority_class"),
    }
    return list_response(list(DB["contracts"].values()), contract_view, filters)


@bp.post("/water/contracts/<string:contract_id>/suspend")
def suspend_contract(contract_id):
    authenticate(["FinanceOfficer"])
    contract = DB["contracts"].get(contract_id)
    if contract is None:
        not_found("WaterContract")
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an ACTIVE contract can be suspended")
    contract["status"] = "SUSPENDED"
    touch(contract)
    return success(contract_view(contract), 200)
