"""Recall coordination and effectiveness verification (PRD §3.8)."""
from flask import Blueprint, request

import calc
import store
from authz import require_roles
from envelope import get_body, pagination_params, sort_and_page, success_list, success_object
from errors import (
    raise_err,
    ERR_EFFECTIVENESS_CRITERIA_NOT_MET,
    ERR_INVALID_STATE,
    ERR_RECALL_CLASS_REQUIRED,
    ERR_RECALL_NOT_FOUND,
)
from guards import entity_or_404, establishment_or_404, require_not_withdrawn
from store import insert, stamp_new, touch
from validate import (
    CHECK_OUTCOMES,
    REASON_CODES,
    RECALL_CLASSES,
    not_future,
    require_enum,
    require_number,
    require_string,
    require_timestamp,
)

bp = Blueprint("recalls", __name__)

READ_ROLES = ("EstablishmentManager", "Inspector", "DistrictManager", "RecallCoordinator", "ProgramAdministrator")


def _recall_or_404(recall_id):
    return entity_or_404("recalls", recall_id, ERR_RECALL_NOT_FOUND)


@bp.post("/inspection/recalls")
def create_recall():
    require_roles("RecallCoordinator")
    body = get_body()
    establishment_id = require_string(body, "establishment_id")
    product_description = require_string(body, "product_description")
    quantity_lbs = require_number(body, "quantity_lbs", gt=0)
    reason_code = require_enum(body, "reason_code", REASON_CODES)

    establishment = establishment_or_404(establishment_id)
    require_not_withdrawn(establishment)

    recall = {
        "establishment_id": establishment_id,
        "product_description": product_description,
        "quantity_lbs": quantity_lbs,
        "reason_code": reason_code,
        "recall_class": None,
        "status": "INITIATED",
        "required_min_checks": None,
        "required_effectiveness_ratio": None,
        "checks_performed": 0,
        "checks_effective": 0,
        "effectiveness_ratio": None,
    }
    stamp_new(recall)
    insert("recalls", recall)
    return success_object(recall, status=201)


@bp.get("/inspection/recalls/<recall_id>")
def get_recall(recall_id):
    require_roles(*READ_ROLES)
    return success_object(_recall_or_404(recall_id))


@bp.get("/inspection/establishments/<est_id>/recalls")
def list_recalls(est_id):
    require_roles(*READ_ROLES)
    establishment_or_404(est_id)
    rows = [r for r in store.all_of("recalls") if r["establishment_id"] == est_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    class_filter = request.args.get("recall_class")
    if class_filter is not None:
        rows = [r for r in rows if r["recall_class"] == class_filter]
    limit, offset = pagination_params()
    page, total = sort_and_page(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.post("/inspection/recalls/<recall_id>/determine-class")
def determine_class(recall_id):
    require_roles("DistrictManager")
    recall = _recall_or_404(recall_id)
    require_not_withdrawn(establishment_or_404(recall["establishment_id"]))
    if recall["status"] not in ("INITIATED", "CLOSED_INEFFECTIVE"):
        raise_err(ERR_INVALID_STATE, "determine-class requires status INITIATED or CLOSED_INEFFECTIVE")
    body = get_body()
    recall_class = require_enum(body, "recall_class", RECALL_CLASSES)

    min_checks, min_ratio = calc.RECALL_CLASS_REQUIREMENTS[recall_class]
    recall["recall_class"] = recall_class
    recall["required_min_checks"] = min_checks
    recall["required_effectiveness_ratio"] = float(min_ratio)
    if recall["status"] == "CLOSED_INEFFECTIVE":
        # Re-classification cycle: fresh effectiveness evidence (PRD §3.8).
        recall["checks_performed"] = 0
        recall["checks_effective"] = 0
        recall["effectiveness_ratio"] = None
    recall["status"] = "CLASS_DETERMINED"
    touch(recall)
    return success_object(recall)


@bp.post("/inspection/recalls/<recall_id>/effectiveness-checks")
def record_check(recall_id):
    require_roles("RecallCoordinator")
    recall = _recall_or_404(recall_id)
    require_not_withdrawn(establishment_or_404(recall["establishment_id"]))
    body = get_body()
    consignee_name = require_string(body, "consignee_name")
    outcome = require_enum(body, "outcome", CHECK_OUTCOMES)
    checked_at = require_timestamp(body, "checked_at")
    if recall["status"] != "CLASS_DETERMINED":
        raise_err(ERR_RECALL_CLASS_REQUIRED, "effectiveness checks require a determined class")
    not_future(checked_at, "checked_at")

    # Append-only event: id + created_at only, never modified (PRD §2.6).
    check = {
        "recall_id": recall["id"],
        "consignee_name": consignee_name,
        "outcome": outcome,
        "checked_at": checked_at,
    }
    stamp_new(check, with_version=False)
    insert("effectiveness_checks", check)

    recall["checks_performed"] += 1
    if outcome == "EFFECTIVE":
        recall["checks_effective"] += 1
    ratio = calc.effectiveness_ratio(recall["checks_effective"], recall["checks_performed"])
    recall["effectiveness_ratio"] = float(ratio) if ratio is not None else None
    touch(recall)
    return success_object(check, status=201)


@bp.get("/inspection/recalls/<recall_id>/effectiveness-checks")
def list_checks(recall_id):
    require_roles(*READ_ROLES)
    _recall_or_404(recall_id)
    rows = [c for c in store.all_of("effectiveness_checks") if c["recall_id"] == recall_id]
    outcome_filter = request.args.get("outcome")
    if outcome_filter is not None:
        rows = [c for c in rows if c["outcome"] == outcome_filter]
    limit, offset = pagination_params()
    page, total = sort_and_page(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.post("/inspection/recalls/<recall_id>/close")
def close_recall(recall_id):
    require_roles("RecallCoordinator")
    recall = _recall_or_404(recall_id)
    require_not_withdrawn(establishment_or_404(recall["establishment_id"]))
    if recall["status"] != "CLASS_DETERMINED":
        raise_err(ERR_INVALID_STATE, "close requires status CLASS_DETERMINED")
    if recall["checks_performed"] < recall["required_min_checks"]:
        raise_err(ERR_EFFECTIVENESS_CRITERIA_NOT_MET, "required minimum checks not performed")
    # Closure is computed: ratio >= requirement closes EFFECTIVE (equality
    # closes effective), otherwise INEFFECTIVE.
    _, required_ratio = calc.RECALL_CLASS_REQUIREMENTS[recall["recall_class"]]
    ratio = calc.effectiveness_ratio(recall["checks_effective"], recall["checks_performed"])
    if ratio is not None and ratio >= required_ratio:
        recall["status"] = "CLOSED_EFFECTIVE"
    else:
        recall["status"] = "CLOSED_INEFFECTIVE"
    touch(recall)
    return success_object(recall)
