"""Sourcing commitments (PRD section 3.1).

Create order of checks: supplier existence, OCC stale-version, APPROVED
state, then window validity. A new commitment lands ACTIVE and supersedes
the prior ACTIVE commitment for the same (supplier, ingredient_category);
the supplier's version bumps as part of the write.
"""
from flask import Blueprint, request

from auth import authenticate, authorize
from db import STORE, new_resource, public, sorted_items, touch
from envelope import ok, ok_list, pagination_args
from errors import fail
from suppliers import get_supplier
from timeutil import fmt_dt
from validate import (INGREDIENT_CATEGORIES, get_body, req_bool, req_dt,
                      req_enum, req_int, req_num)

bp = Blueprint("commitments", __name__)


@bp.post("/suppliers/<sid>/commitments")
def create_commitment(sid):
    _, role = authenticate()
    authorize(role, ("SourcingManager",))
    supplier = get_supplier(sid)
    body = get_body()
    category = req_enum(body, "ingredient_category", INGREDIENT_CATEGORIES)
    fair_trade = req_bool(body, "fair_trade_required")
    min_score = req_int(body, "min_social_score", 0, 100)
    premium = req_num(body, "premium_over_commodity_pct", 0)
    eff_from = req_dt(body, "effective_from")
    eff_to = req_dt(body, "effective_to")
    expected = req_int(body, "expected_supplier_version")
    if expected != supplier["version"]:
        fail("ERR_STALE_VERSION",
             "expected_supplier_version does not match the supplier's "
             "current version")
    if supplier["status"] != "APPROVED":
        fail("ERR_SUPPLIER_NOT_APPROVED",
             "Commitment create requires supplier.status == APPROVED")
    if not eff_to > eff_from:
        fail("ERR_COMMITMENT_WINDOW_INVALID",
             "effective_to must be strictly later than effective_from")
    for c in STORE["commitments"].values():
        if (c["supplier_id"] == sid and c["ingredient_category"] == category
                and c["status"] == "ACTIVE"):
            c["status"] = "SUPERSEDED"
            touch(c)
    r = new_resource()
    r.update({
        "supplier_id": sid,
        "ingredient_category": category,
        "fair_trade_required": fair_trade,
        "min_social_score": min_score,
        "premium_over_commodity_pct": premium,
        "effective_from": fmt_dt(eff_from),
        "effective_to": fmt_dt(eff_to),
        "status": "ACTIVE",
    })
    STORE["commitments"][r["id"]] = r
    touch(supplier)
    return ok(public(r), 201)


@bp.get("/suppliers/<sid>/commitments")
def list_commitments(sid):
    _, role = authenticate()
    authorize(role, ("SourcingManager", "ParentOpsController"))
    get_supplier(sid)
    status = request.args.get("status")
    items = [c for c in STORE["commitments"].values() if c["supplier_id"] == sid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = [public(c) for c in sorted_items(items)]
    limit, offset = pagination_args()
    return ok_list(items, limit, offset)
