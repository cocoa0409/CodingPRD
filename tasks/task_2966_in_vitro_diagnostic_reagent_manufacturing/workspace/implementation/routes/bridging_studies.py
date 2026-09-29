"""Lot-to-lot consistency bridging studies (PRD 3.7)."""

from flask import Blueprint

import cascades
import lookup
import recompute
import serialize
from errors import ApiError
from response import created_response, list_response, object_response
from store import create_row, db, now_clock, rows, touch
from validation import (ALL_ROLES, BRIDGING_DECISIONS, BRIDGING_STATUSES, Body,
                        EQUIVALENCE_VERDICTS, authenticate_and_authorize,
                        enum_filter, json_body, pagination, paginate, str_filter)

bp = Blueprint("bridging_studies", __name__)


@bp.post("/bridging-studies")
def create_bridging_study():
    authenticate_and_authorize(("RegulatoryAffairs",))
    body = Body(json_body())
    predicate_lot_id = body.req_str("predicate_lot_id")
    candidate_lot_id = body.req_str("candidate_lot_id")
    changed_material_lot_id = body.req_str("changed_material_lot_id")
    paired_test_codes = body.req_code_array("paired_test_codes")

    # Rung 45 - body foreign keys, in entity field-declaration order.
    lookup.reagent_lot(predicate_lot_id)
    lookup.reagent_lot(candidate_lot_id)
    lookup.material_lot(changed_material_lot_id)

    row = create_row(db.bridging_studies, {
        "predicate_lot_id": predicate_lot_id,
        "candidate_lot_id": candidate_lot_id,
        "changed_material_lot_id": changed_material_lot_id,
        "paired_test_codes": paired_test_codes,
        "status": "DRAFT",
        "mean_bias_pct": None,
        "max_bias_pct": None,
        "equivalence_verdict": "PENDING",
        "decided_by_user_id": None,
        "decided_at": None,
    })
    # The bias figures are computed immediately from whatever data both lots
    # already carry.
    recompute.bridging_study_figures(row)
    return created_response(serialize.bridging_study(row))


@bp.get("/bridging-studies/<study_id>")
def read_bridging_study(study_id):
    authenticate_and_authorize(ALL_ROLES)
    row = lookup.bridging_study(study_id)
    return object_response(serialize.bridging_study(row))


@bp.get("/bridging-studies")
def list_bridging_studies():
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    predicate_lot_id = str_filter("predicate_lot_id")
    candidate_lot_id = str_filter("candidate_lot_id")
    changed_material_lot_id = str_filter("changed_material_lot_id")
    status = enum_filter("status", BRIDGING_STATUSES)
    verdict = enum_filter("equivalence_verdict", EQUIVALENCE_VERDICTS)
    items = rows(db.bridging_studies)
    if predicate_lot_id is not None:
        items = [r for r in items if r["predicate_lot_id"] == predicate_lot_id]
    if candidate_lot_id is not None:
        items = [r for r in items if r["candidate_lot_id"] == candidate_lot_id]
    if changed_material_lot_id is not None:
        items = [r for r in items
                 if r["changed_material_lot_id"] == changed_material_lot_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if verdict is not None:
        items = [r for r in items if r["equivalence_verdict"] == verdict]
    page = paginate(items, limit, offset)
    return list_response([serialize.bridging_study(r) for r in page],
                         limit, offset, len(items))


@bp.post("/bridging-studies/<study_id>/decision")
def decide_bridging_study(study_id):
    user_id, _role = authenticate_and_authorize(("QAReleaser",))
    body = Body(json_body())
    decision = body.req_enum("decision", BRIDGING_DECISIONS)
    body.opt_str("rationale")
    study = lookup.bridging_study(study_id)

    # Rung 60 - state precondition.
    if study["status"] != "DRAFT":
        raise ApiError("ERR_BRIDGING_STUDY_STATE_INVALID",
                       "A study in %s is terminal." % study["status"])

    if decision == "APPROVE":
        # Rung 125 - paired data availability, before rung 127.
        if study["equivalence_verdict"] == "PENDING":
            raise ApiError("ERR_PAIRED_DATA_MISSING")
        # Rung 127 - equivalence.
        if study["equivalence_verdict"] != "EQUIVALENT":
            raise ApiError("ERR_NOT_EQUIVALENT")

    clock = now_clock()
    if decision == "APPROVE":
        study["status"] = "APPROVED"
    else:
        study["status"] = "FAILED"
    study["decided_by_user_id"] = user_id
    study["decided_at"] = clock
    touch(study)

    if decision == "REJECT":
        cascades.bridging_failure(study)
    return object_response(serialize.bridging_study(study))
