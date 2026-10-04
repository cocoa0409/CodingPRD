"""Recalls: initiation, classification, effectiveness verification, and
termination (PRD section 3.9).

Recall: INITIATED -> CLASSIFIED -> CLASSIFIED (record-effectiveness) ->
TERMINATED. The recall-quantity conservation invariant (quantity_recovered +
quantity_corrected + quantity_destroyed + quantity_outstanding ==
quantity_distributed) holds throughout.
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import serialize
import services
from auth import require_roles, ALL_ROLES
from envelope import ok, ok_list, json_body
from errors import ApiError
from pagination import page_params, paginate

bp = Blueprint("recalls", __name__)

CLASSIFICATIONS = ("CLASS_I", "CLASS_II", "CLASS_III")


def _get_recall_or_404(recall_id):
    r = db.recalls.get(recall_id)
    if r is None:
        raise ApiError("ERR_RECALL_NOT_FOUND")
    return r


def _pct(numerator, denominator):
    """Percentage rounded half up to exactly 1 decimal place (0.0 when the
    denominator is zero)."""
    if denominator == 0:
        return Decimal("0.0")
    return (Decimal(numerator) * 100 / Decimal(denominator)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


def _recompute_recall(r):
    accounted = (
        r["quantity_recovered"] + r["quantity_corrected"] + r["quantity_destroyed"]
    )
    r["quantity_outstanding"] = r["quantity_distributed"] - accounted
    r["effectiveness_pct"] = _pct(accounted, r["quantity_distributed"])
    r["consignee_contact_pct"] = _pct(r["consignees_contacted"], r["consignees_total"])


@bp.post("/registry/recalls")
@require_roles("RecallCoordinator")
def create_recall(caller_id, caller_role):
    body = json_body()
    # Tier 12: request shape.
    facility_id = body.get("facility_id")
    product_code = body.get("product_code")
    quantity_distributed = body.get("quantity_distributed")
    if not isinstance(facility_id, str) or not facility_id:
        raise ApiError("ERR_INVALID_REQUEST", "facility_id is required")
    if not isinstance(product_code, str) or not product_code:
        raise ApiError("ERR_INVALID_REQUEST", "product_code is required")
    if not services.is_int(quantity_distributed) or quantity_distributed <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "quantity_distributed must be an integer greater than 0"
        )

    r = db.new_common()
    r.update(
        {
            "facility_id": facility_id,
            "product_code": product_code,
            "quantity_distributed": quantity_distributed,
            "classification": "NONE",
            "status": "INITIATED",
            "quantity_recovered": 0,
            "quantity_corrected": 0,
            "quantity_destroyed": 0,
            "quantity_outstanding": quantity_distributed,
            "effectiveness_pct": Decimal("0.0"),
            "consignees_contacted": 0,
            "consignees_total": 0,
            "consignee_contact_pct": Decimal("0.0"),
        }
    )
    db.recalls[r["id"]] = r
    return ok(serialize.recall(r), 201)


@bp.get("/registry/recalls/<rid>")
@require_roles(*ALL_ROLES)
def get_recall(rid, caller_id, caller_role):
    return ok(serialize.recall(_get_recall_or_404(rid)))


@bp.get("/registry/recalls")
@require_roles(*ALL_ROLES)
def list_recalls(caller_id, caller_role):
    limit, offset = page_params()
    items = list(db.recalls.values())
    for field in ("facility_id", "classification", "status", "product_code"):
        value = request.args.get(field)
        if value is not None:
            items = [r for r in items if r[field] == value]
    items.sort(key=db.sort_key)
    total, page = paginate(items, limit, offset)
    return ok_list([serialize.recall(r) for r in page], total, limit, offset)


@bp.post("/registry/recalls/<rid>/classify")
@require_roles("RecallCoordinator")
def classify_recall(rid, caller_id, caller_role):
    # Tier 4: existence.
    r = _get_recall_or_404(rid)
    # Tier 5: only while INITIATED.
    if r["status"] != "INITIATED":
        raise ApiError("ERR_RECALL_INVALID_STATE")
    # Tier 12: classification must be a real class.
    classification = json_body().get("classification")
    if classification not in CLASSIFICATIONS:
        raise ApiError(
            "ERR_INVALID_REQUEST", "classification must be CLASS_I, CLASS_II, or CLASS_III"
        )
    r["classification"] = classification
    r["status"] = "CLASSIFIED"
    db.touch(r)
    return ok(serialize.recall(r))


@bp.post("/registry/recalls/<rid>/record-effectiveness")
@require_roles("RecallCoordinator")
def record_effectiveness(rid, caller_id, caller_role):
    # Tier 4: existence.
    r = _get_recall_or_404(rid)
    # Tier 5: only while CLASSIFIED.
    if r["status"] != "CLASSIFIED":
        raise ApiError("ERR_RECALL_INVALID_STATE")
    body = json_body()
    delta_recovered = body.get("delta_recovered")
    delta_corrected = body.get("delta_corrected")
    delta_destroyed = body.get("delta_destroyed")
    consignees_contacted = body.get("consignees_contacted")
    consignees_total = body.get("consignees_total")
    # Tier 9: quantity-delta accounting against the outstanding balance.
    deltas = (delta_recovered, delta_corrected, delta_destroyed)
    if all(services.is_int(d) for d in deltas):
        if any(d < 0 for d in deltas) or sum(deltas) > r["quantity_outstanding"]:
            raise ApiError("ERR_UNITS_ACCOUNTING_MISMATCH")
    # Tier 12: all five figures are required integers; consignee semantics.
    if not all(services.is_int(d) for d in deltas):
        raise ApiError(
            "ERR_INVALID_REQUEST", "quantity deltas must be integers"
        )
    if not services.is_int(consignees_contacted) or consignees_contacted < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "consignees_contacted must be a non-negative integer delta"
        )
    if not services.is_int(consignees_total) or consignees_total < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "consignees_total must be a non-negative integer"
        )
    new_contacted = r["consignees_contacted"] + consignees_contacted
    if consignees_total < new_contacted:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "consignees_total must be at least the new cumulative contacted count",
        )

    r["quantity_recovered"] += delta_recovered
    r["quantity_corrected"] += delta_corrected
    r["quantity_destroyed"] += delta_destroyed
    r["consignees_contacted"] = new_contacted
    r["consignees_total"] = consignees_total
    _recompute_recall(r)
    db.touch(r)
    return ok(serialize.recall(r))


@bp.post("/registry/recalls/<rid>/terminate")
@require_roles("RecallCoordinator")
def terminate_recall(rid, caller_id, caller_role):
    # Tier 4: existence.
    r = _get_recall_or_404(rid)
    # Tier 5: only while CLASSIFIED.
    if r["status"] != "CLASSIFIED":
        raise ApiError("ERR_RECALL_INVALID_STATE")
    # Tier 9: the classification's effectiveness/contact thresholds.
    effectiveness = r["effectiveness_pct"]
    contact = r["consignee_contact_pct"]
    if r["classification"] == "CLASS_I":
        met = effectiveness == Decimal("100.0") and contact == Decimal("100.0")
    elif r["classification"] == "CLASS_II":
        met = effectiveness >= services.CLASS_II_THRESHOLD
    else:
        met = effectiveness >= services.CLASS_III_THRESHOLD
    if not met:
        raise ApiError("ERR_EFFECTIVENESS_THRESHOLD_NOT_MET")
    r["status"] = "TERMINATED"
    db.touch(r)
    return ok(serialize.recall(r))
