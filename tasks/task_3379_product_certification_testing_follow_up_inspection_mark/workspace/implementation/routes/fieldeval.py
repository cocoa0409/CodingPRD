"""Field evaluation endpoints (PRD 3.8): two parallel status dimensions —
eval_status (REQUESTED/EVALUATED_PASS/EVALUATED_FAIL) and acceptance_status
(PENDING/ACCEPTED/REJECTED) — evolving on independent triggers."""
from flask import Blueprint, request

import clock
import db
from constants import (
    ACCEPTANCE_DECISIONS, EVAL_OUTCOMES, ROLE_AHJ, ROLE_ENGINEER, ROLE_REP,
)
from errors import (
    ApiError, ERR_ALREADY_TERMINAL, ERR_FIELD_EVALUATION_NOT_PASSED,
    ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_RECIPROCITY_NOT_GRANTED,
)
from middleware import (
    any_authenticated, check_ahj_ownership, require_roles,
)
from response import paginated_list, success
from services import calc
from validation import body, req_enum, req_str

bp = Blueprint("field_evaluations", __name__)


def get_field_evaluation_or_404(fe_id):
    fe = db.field_evaluations.get(fe_id)
    if fe is None:
        raise ApiError(ERR_NOT_FOUND, "field evaluation not found")
    return fe


@bp.post("/field-evaluations")
@require_roles(ROLE_REP)
def create_field_evaluation(user_id, role):
    payload = body(required=True)
    standard_id = req_str(payload, "standard_id")
    evaluating_jurisdiction_id = req_str(payload, "evaluating_jurisdiction_id")
    site_jurisdiction_id = req_str(payload, "site_jurisdiction_id")
    equipment_description = req_str(payload, "equipment_description")
    site_address = req_str(payload, "site_address")

    if standard_id not in db.standards:
        raise ApiError(ERR_NOT_FOUND, "standard not found")
    if evaluating_jurisdiction_id not in db.jurisdictions:
        raise ApiError(ERR_NOT_FOUND, "evaluating jurisdiction not found")
    if site_jurisdiction_id not in db.jurisdictions:
        raise ApiError(ERR_NOT_FOUND, "site jurisdiction not found")

    fe = db.new_entity(db.field_evaluations, {
        "manufacturer_id": user_id,
        "standard_id": standard_id,
        "evaluating_jurisdiction_id": evaluating_jurisdiction_id,
        "site_jurisdiction_id": site_jurisdiction_id,
        "equipment_description": equipment_description,
        "site_address": site_address,
        "eval_status": "REQUESTED",
        "acceptance_status": "PENDING",
        "evaluated_by": None,
        "ahj_decided_by": None,
        "label_issued_on": None,
    })
    return success(fe, status=201)


@bp.get("/field-evaluations")
@any_authenticated
def list_field_evaluations(user_id, role):
    items = db.sorted_items(db.field_evaluations)
    for field in ("manufacturer_id", "standard_id",
                  "evaluating_jurisdiction_id", "site_jurisdiction_id"):
        wanted = request.args.get(field)
        if wanted is not None:
            items = [f for f in items if f[field] == wanted]
    page, pagination = paginated_list(items)
    return success(page, pagination=pagination)


@bp.get("/field-evaluations/<fe_id>")
@any_authenticated
def get_field_evaluation(fe_id, user_id, role):
    return success(get_field_evaluation_or_404(fe_id))


@bp.post("/field-evaluations/<fe_id>/evaluate")
@require_roles(ROLE_ENGINEER)
def evaluate_field_evaluation(fe_id, user_id, role):
    fe = get_field_evaluation_or_404(fe_id)
    payload = body(required=True)
    outcome = req_enum(payload, "outcome", EVAL_OUTCOMES)

    if fe["eval_status"] == "EVALUATED_FAIL":
        raise ApiError(ERR_ALREADY_TERMINAL,
                       "field evaluation is EVALUATED_FAIL (terminal)")
    if fe["eval_status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE,
                       "field evaluation is %s, not REQUESTED"
                       % fe["eval_status"])

    fe["eval_status"] = "EVALUATED_PASS" if outcome == "PASS" else "EVALUATED_FAIL"
    fe["evaluated_by"] = user_id
    db.mutate(fe)
    return success(fe)


@bp.post("/field-evaluations/<fe_id>/decide-acceptance")
@require_roles(ROLE_AHJ)
def decide_acceptance(fe_id, user_id, role):
    fe = get_field_evaluation_or_404(fe_id)
    check_ahj_ownership(user_id, role, fe["site_jurisdiction_id"])
    payload = body(required=True)
    decision = req_enum(payload, "decision", ACCEPTANCE_DECISIONS)

    if fe["acceptance_status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE,
                       "acceptance is already %s" % fe["acceptance_status"])

    if decision == "ACCEPT":
        if fe["eval_status"] != "EVALUATED_PASS":
            raise ApiError(ERR_FIELD_EVALUATION_NOT_PASSED,
                           "acceptance requires eval_status EVALUATED_PASS")
        site = db.jurisdictions[fe["site_jurisdiction_id"]]
        evaluating = db.jurisdictions[fe["evaluating_jurisdiction_id"]]
        if not calc.reciprocity_granted(site, evaluating):
            raise ApiError(ERR_RECIPROCITY_NOT_GRANTED,
                           "site jurisdiction does not accept this field label")
        fe["acceptance_status"] = "ACCEPTED"
        fe["label_issued_on"] = clock.now()
    else:  # REJECT: permitted on any evaluated status, not on REQUESTED
        if fe["eval_status"] == "REQUESTED":
            raise ApiError(ERR_FIELD_EVALUATION_NOT_PASSED,
                           "field evaluation has not been evaluated yet")
        fe["acceptance_status"] = "REJECTED"

    fe["ahj_decided_by"] = user_id
    db.mutate(fe)
    return success(fe)
