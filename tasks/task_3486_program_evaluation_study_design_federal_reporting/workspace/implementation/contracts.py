"""EvaluationContract endpoints: award, get, terminate, closeout."""
from flask import Blueprint

import store
from errors import raise_err
from serialize import contract_out
from services import studies_of_contract, terminate_study_cascade
from util import new_entity, ok_obj, touch
from validation import (ROLE_AGENCY_OFFICER, STAFF_ROLES, authenticate,
                        authorize, check_schema, get_json_body)

bp = Blueprint("contracts", __name__)


def get_contract_or_404(contract_id):
    contract = store.contracts.get(contract_id)
    if contract is None:
        raise_err("ERR_NOT_FOUND", "Contract not found")
    return contract


@bp.post("/evaluation/contracts")
def create_contract():
    _uid, role = authenticate()
    authorize(role, [ROLE_AGENCY_OFFICER])
    body = get_json_body()
    check_schema(body, {
        "agency_code": ("str", True),
        "title": ("str", True),
        "award_amount_cents": ("int", True),
        "deliverable_report_count": ("int", False),
    })
    award = body["award_amount_cents"]
    if award <= 0:
        raise_err("ERR_INVALID_REQUEST", "award_amount_cents must be > 0")
    drc = body.get("deliverable_report_count")
    if drc is None:
        drc = 1
    if drc < 1:
        raise_err("ERR_INVALID_REQUEST",
                  "deliverable_report_count must be >= 1")
    contract = new_entity({
        "agency_code": body["agency_code"],
        "title": body["title"],
        "award_amount_cents": award,
        "deliverable_report_count": drc,
        "disbursed_cents": 0,
        "forfeited_cents": 0,
        "remaining_cents": award,
        "status": "ACTIVE",
        "terminated_reason": None,
    })
    store.contracts[contract["id"]] = contract
    return ok_obj(contract_out(contract), 201)


@bp.get("/evaluation/contracts/<contract_id>")
def get_contract(contract_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    return ok_obj(contract_out(get_contract_or_404(contract_id)))


@bp.post("/evaluation/contracts/<contract_id>/terminate")
def terminate_contract(contract_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_AGENCY_OFFICER])
    contract = get_contract_or_404(contract_id)
    body = get_json_body()
    check_schema(body, {"reason": ("str", True)})
    if contract["status"] != "ACTIVE":
        raise_err("ERR_CONTRACT_NOT_ACTIVE",
                  "Only an ACTIVE contract can be terminated")
    contract["forfeited_cents"] = contract["remaining_cents"]
    contract["remaining_cents"] = 0
    contract["status"] = "TERMINATED"
    contract["terminated_reason"] = body["reason"]
    touch(contract)
    for study in studies_of_contract(contract_id):
        if study["status"] not in ("COMPLETED", "TERMINATED"):
            terminate_study_cascade(study)
    return ok_obj(contract_out(contract))


@bp.post("/evaluation/contracts/<contract_id>/closeout")
def closeout_contract(contract_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_AGENCY_OFFICER])
    contract = get_contract_or_404(contract_id)
    body = get_json_body()
    check_schema(body, {})
    if contract["status"] != "ACTIVE":
        raise_err("ERR_CONTRACT_NOT_ACTIVE",
                  "Only an ACTIVE contract can be closed out")
    for study in studies_of_contract(contract_id):
        if study["status"] != "COMPLETED":
            raise_err("ERR_STUDIES_NOT_COMPLETED",
                      "Every study of the contract must be COMPLETED")
    contract["forfeited_cents"] = contract["remaining_cents"]
    contract["remaining_cents"] = 0
    contract["status"] = "CLOSED"
    touch(contract)
    return ok_obj(contract_out(contract))
