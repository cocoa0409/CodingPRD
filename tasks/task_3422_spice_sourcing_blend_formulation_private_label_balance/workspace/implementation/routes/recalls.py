"""RecallCase routes (PRD 3.7): open / read / initiate / close.

Initiation freezes the scope (PROVISIONAL or FINAL per
calculations.recall_scope) and holds affected CLEAR batches; closing moves
affected held batches to RECALLED (BRANDED) or WITHDRAWN (PRIVATE_LABEL).
"""
from flask import Blueprint, request

from errors import ApiError
from helpers import (D, F, filter_enum, invalid_state, new_entity, not_found,
                     paged, pub, require_roles, respond, touch, validate_body)
from services.recall import compute_scope
from state import DB

bp = Blueprint("recalls", __name__)

RECALL_STATUSES = ["DRAFT", "INITIATED", "CLOSED"]
RECALL_READ_ROLES = ("RecallCoordinator", "QualityManager", "PlatformAdmin")


@bp.post("/spice/recall-cases")
@require_roles("RecallCoordinator")
def create_case():
    data = validate_body({
        "trigger_type": F("enum", enum=["LOT_SUSPECT", "BATCH_SUSPECT", "REGULATORY"],
                          required=True),
        "suspect_lot_id": F("str", nullable=True, default=None),
        "suspect_batch_id": F("str", nullable=True, default=None),
        "scope_policy": F("enum", enum=["PROVISIONAL", "FINAL"], required=True),
    })
    if data["suspect_lot_id"] is not None and data["suspect_lot_id"] not in DB.lots:
        not_found("suspect lot not found")
    if data["suspect_batch_id"] is not None and data["suspect_batch_id"] not in DB.batches:
        not_found("suspect batch not found")
    if (data["suspect_lot_id"] is None) == (data["suspect_batch_id"] is None):
        raise ApiError("ERR_RECALL_SCOPE_INVALID", 422,
                       "Exactly one of suspect_lot_id / suspect_batch_id is required")
    case = new_entity({
        "trigger_type": data["trigger_type"],
        "suspect_lot_id": data["suspect_lot_id"],
        "suspect_batch_id": data["suspect_batch_id"],
        "scope_policy": data["scope_policy"],
        "source": "MANUAL",
        "affected_batch_ids": [],
        "affected_quantity_kg": D(0),
        "status": "DRAFT",
    })
    DB.recall_cases[case["id"]] = case
    return respond(pub(case), 201)


@bp.get("/spice/recall-cases/<case_id>")
@require_roles(*RECALL_READ_ROLES)
def get_case(case_id):
    case = DB.recall_cases.get(case_id)
    if case is None:
        not_found("recall case not found")
    return respond(pub(case))


@bp.get("/spice/recall-cases")
@require_roles(*RECALL_READ_ROLES)
def list_cases():
    status = filter_enum("status", RECALL_STATUSES)
    suspect_lot_id = request.args.get("suspect_lot_id")
    suspect_batch_id = request.args.get("suspect_batch_id")
    items = []
    for c in DB.recall_cases.values():
        if status is not None and c["status"] != status:
            continue
        if suspect_lot_id is not None and c["suspect_lot_id"] != suspect_lot_id:
            continue
        if suspect_batch_id is not None and c["suspect_batch_id"] != suspect_batch_id:
            continue
        items.append(c)
    data, meta = paged(items)
    return respond(data, page=meta)


@bp.post("/spice/recall-cases/<case_id>/initiate")
@require_roles("RecallCoordinator")
def initiate_case(case_id):
    case = DB.recall_cases.get(case_id)
    if case is None:
        not_found("recall case not found")
    if case["status"] != "DRAFT":
        invalid_state("Only a DRAFT recall case can be initiated")
    affected = compute_scope(case)
    case["affected_batch_ids"] = [b["id"] for b in affected]
    case["affected_quantity_kg"] = sum((b["quantity_kg"] for b in affected), D(0))
    case["status"] = "INITIATED"
    touch(case)
    for b in affected:
        if b["quality_status"] == "CLEAR":
            # Recall-driven hold: cause/lot fields stay NONE/null.
            b["quality_status"] = "QUALITY_HOLD"
            touch(b)
    return respond(pub(case))


@bp.post("/spice/recall-cases/<case_id>/close")
@require_roles("RecallCoordinator")
def close_case(case_id):
    case = DB.recall_cases.get(case_id)
    if case is None:
        not_found("recall case not found")
    if case["status"] != "INITIATED":
        invalid_state("Only an INITIATED recall case can be closed")
    case["status"] = "CLOSED"
    touch(case)
    for batch_id in case["affected_batch_ids"]:
        b = DB.batches.get(batch_id)
        if b is not None and b["quality_status"] == "QUALITY_HOLD":
            b["quality_status"] = ("RECALLED" if b["brand_type"] == "BRANDED"
                                   else "WITHDRAWN")
            touch(b)
    return respond(pub(case))
