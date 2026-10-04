"""Concepts (PRD 3.2): pitch against a SELECTED trend at one of the five
fixed price points; selection derives the unit cost target.
"""
from flask import Blueprint

from core import clock
from core.auth import authenticate, require_role
from core.constants import PRICE_POINTS, ROLE_TREND_SCOUT
from core.envelope import pub, success_object
from core.errors import err, not_found
from core.pagination import list_response
from core.store import new_record, store, touch
from core.validate import get_body, req_enum, req_int, req_str
from services import calc

bp = Blueprint("concepts", __name__)

STATUSES = ("PITCHED", "SELECTED", "IN_DEVELOPMENT", "COMMERCIALIZED", "KILLED")


@bp.post("/concepts")
def create_concept():
    _, role = authenticate()
    require_role(role, ROLE_TREND_SCOUT)
    body = get_body()
    trend_signal_id = req_str(body, "trend_signal_id")
    name = req_str(body, "name")
    category = req_str(body, "category")
    price_point = req_int(body, "target_price_point_cents")
    trend = store.trend_signals.get(trend_signal_id)
    if trend is None:
        raise not_found("ERR_TREND_SIGNAL_NOT_FOUND", "trend signal not found")
    # Same referential step (priority 9): a category mismatch reports
    # ERR_INVALID_REQUEST rather than ERR_TREND_NOT_SELECTED.
    if category != trend["category"]:
        raise err(
            "ERR_INVALID_REQUEST",
            "concept category must equal the parent trend's category",
        )
    if trend["status"] != "SELECTED":
        raise err(
            "ERR_TREND_NOT_SELECTED",
            "the parent trend signal is not in SELECTED status",
        )
    for other in store.concepts.values():
        if other["name"] == name and other["status"] != "KILLED":
            raise err(
                "ERR_DUPLICATE_CONCEPT_NAME",
                "concept name is already used by a non-KILLED concept",
            )
    if price_point not in PRICE_POINTS:
        raise err(
            "ERR_INVALID_PRICE_POINT",
            "target_price_point_cents must be one of %s" % list(PRICE_POINTS),
        )
    rec = new_record(
        {
            "trend_signal_id": trend_signal_id,
            "name": name,
            "category": category,
            "target_price_point_cents": price_point,
            "status": "PITCHED",
            "target_unit_cost_cents": None,
            "selected_at": None,
        }
    )
    store.concepts[rec["id"]] = rec
    return success_object(pub(rec), code=201)


@bp.get("/concepts")
def list_concepts():
    authenticate()
    return list_response(
        store.concepts.values(),
        {"trend_signal_id": "trend_signal_id", "status": "status", "category": "category"},
        pub,
    )


@bp.get("/concepts/<rid>")
def get_concept(rid):
    authenticate()
    rec = store.concepts.get(rid)
    if rec is None:
        raise not_found("ERR_CONCEPT_NOT_FOUND", "concept not found")
    return success_object(pub(rec))


@bp.patch("/concepts/<rid>")
def patch_concept(rid):
    _, role = authenticate()
    require_role(role, ROLE_TREND_SCOUT)
    body = get_body()
    target = None
    if "status" in body and body["status"] is not None:
        target = req_enum(body, "status", STATUSES)
    rec = store.concepts.get(rid)
    if rec is None:
        raise not_found("ERR_CONCEPT_NOT_FOUND", "concept not found")
    if target is None:
        return success_object(pub(rec))
    current = rec["status"]
    if target == "SELECTED" and current == "PITCHED":
        # Selection derives the cost ceiling from the fixed price point.
        rec["target_unit_cost_cents"] = calc.target_unit_cost(
            rec["target_price_point_cents"]
        )
        rec["selected_at"] = clock.now()
        rec["status"] = "SELECTED"
    elif target == "KILLED" and current in ("PITCHED", "SELECTED"):
        rec["status"] = "KILLED"
    else:
        raise err(
            "ERR_INVALID_STATE",
            "cannot transition a concept from %s to %s" % (current, target),
        )
    touch(rec)
    return success_object(pub(rec))
