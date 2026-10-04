"""Study endpoints: create under contract, list under contract, get one."""
from flask import Blueprint

import store
from errors import raise_err
from serialize import study_out
from services import studies_of_contract
from util import new_entity, ok_list, ok_obj, paginate, sort_created
from validation import (ROLE_PRINCIPAL_INVESTIGATOR, STAFF_ROLES,
                        authenticate, authorize, check_schema, get_json_body)

bp = Blueprint("studies", __name__)


def get_study_or_404(study_id):
    study = store.studies.get(study_id)
    if study is None:
        raise_err("ERR_NOT_FOUND", "Study not found")
    return study


@bp.post("/evaluation/contracts/<contract_id>/studies")
def create_study(contract_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    contract = store.contracts.get(contract_id)
    if contract is None:
        raise_err("ERR_NOT_FOUND", "Contract not found")
    body = get_json_body()
    check_schema(body, {
        "title": ("str", True),
        "research_question": ("str", True),
    })
    if contract["status"] != "ACTIVE":
        raise_err("ERR_CONTRACT_NOT_ACTIVE",
                  "Studies may only be created under an ACTIVE contract")
    study = new_entity({
        "contract_id": contract_id,
        "title": body["title"],
        "research_question": body["research_question"],
        "status": "DESIGN",
        "committed_projected_n": 0,
        "pipeline_projected_n": 0,
        "enrolled_total": 0,
        "quarantined_record_count": 0,
        "sample_adequacy": "UNASSESSED",
    })
    store.studies[study["id"]] = study
    return ok_obj(study_out(study), 201)


@bp.get("/evaluation/contracts/<contract_id>/studies")
def list_studies(contract_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    if contract_id not in store.contracts:
        raise_err("ERR_NOT_FOUND", "Contract not found")
    items = sort_created(studies_of_contract(contract_id))
    page, limit, offset, total = paginate(items)
    return ok_list([study_out(s) for s in page], limit, offset, total)


@bp.get("/evaluation/studies/<study_id>")
def get_study(study_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    return ok_obj(study_out(get_study_or_404(study_id)))
