"""Shelf execution and stale-credit resources."""

from flask import Blueprint, request

import db as store
import services as svc
from errors import (
    ERR_INSUFFICIENT_TRUCK_STOCK,
    ERR_INVALID_STATE,
    ERR_PRODUCT_NOT_ALLOCATED,
    ERR_PRODUCT_NOT_STALE_ELIGIBLE,
    ERR_ROUTE_DAY_NOT_IN_PROGRESS,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STORE_CREDIT_CAP_EXCEEDED,
    ERR_STORE_NOT_ACTIVE,
    ERR_STORE_SCOPE_VIOLATION,
    ERR_VALIDATION,
    err,
)
from helpers import (
    auth,
    body,
    filter_sort_page,
    get,
    new_record,
    opt_str,
    req_bool,
    req_field,
    req_int,
    req_str,
    require_role,
    touch,
)
from response import list_response, success

bp = Blueprint("storeside", __name__)

SALVAGE_NUM = 2
SALVAGE_DEN = 5


def _round_half_up_div(num, den):
    return (2 * num + den) // (2 * den)


# ---------------------------------------------------------------------------
# shelf executions
# ---------------------------------------------------------------------------

@bp.post("/dsd/shelf-executions")
def create_shelf_execution():
    uid, role = auth()
    require_role(role, "RouteSalesRep")
    data = body()
    route_day_id = req_str(data, "route_day_id")
    store_id = req_str(data, "store_id")
    product_id = req_str(data, "product_id")
    qty_placed = req_int(data, "qty_placed_cases")
    rotated = req_bool(data, "rotated")
    display_built = req_bool(data, "display_built")
    day = get("route_days", route_day_id)
    st = get("stores", store_id)
    get("products", product_id)
    if qty_placed < 0:
        raise err(ERR_VALIDATION, "qty_placed_cases must be >= 0")
    if day["status"] != "IN_PROGRESS":
        raise err(ERR_ROUTE_DAY_NOT_IN_PROGRESS, "Route day is not IN_PROGRESS")
    if st["status"] != "ACTIVE":
        raise err(ERR_STORE_NOT_ACTIVE, "Store is not ACTIVE")
    if not svc.open_lots_for(day["id"], product_id):
        raise err(ERR_PRODUCT_NOT_ALLOCATED, "Product not allocated on this route day")
    rec = new_record()
    rec.update(
        route_day_id=route_day_id,
        store_id=store_id,
        product_id=product_id,
        qty_placed_cases=qty_placed,
        rotated=rotated,
        display_built=display_built,
        created_by_user_id=uid,
        verified_by_user_id=None,
        status="RECORDED",
    )
    store.db["shelf_executions"][rec["id"]] = rec
    return success(rec, 201)


@bp.get("/dsd/shelf-executions/<execId>")
def get_shelf_execution(execId):
    auth()
    return success(get("shelf_executions", execId), 200)


@bp.get("/dsd/shelf-executions")
def list_shelf_executions():
    auth()
    items, limit, offset, total = filter_sort_page(
        "shelf_executions",
        {
            "store_id": request.args.get("store_id"),
            "route_day_id": request.args.get("route_day_id"),
            "product_id": request.args.get("product_id"),
        },
    )
    return list_response(items, limit, offset, total)


@bp.post("/dsd/shelf-executions/<execId>/verify")
def verify_shelf_execution(execId):
    uid, role = auth()
    require_role(role, "StoreManager")
    rec = get("shelf_executions", execId)
    if uid != rec["store_id"]:
        raise err(ERR_STORE_SCOPE_VIOLATION, "Store manager is not scoped to this store")
    if rec["status"] != "RECORDED":
        raise err(ERR_INVALID_STATE, "Shelf execution is not RECORDED")
    data = body()
    outcome = req_field(data, "outcome")
    if outcome not in ("VERIFIED", "REJECTED"):
        raise err(ERR_VALIDATION, "outcome must be VERIFIED or REJECTED")
    if outcome == "REJECTED":
        reason = opt_str(data, "reject_reason")
        if not reason:
            raise err(ERR_VALIDATION, "reject_reason is required")
        rec["reject_reason"] = reason
    rec["status"] = outcome
    rec["verified_by_user_id"] = uid
    touch(rec)
    return success(rec, 200)


# ---------------------------------------------------------------------------
# stale credits
# ---------------------------------------------------------------------------

@bp.post("/dsd/stale-credits")
def create_stale_credit():
    uid, role = auth()
    require_role(role, "RouteSalesRep", "RouteSupervisor")
    data = body()
    route_day_id = req_str(data, "route_day_id")
    store_id = req_str(data, "store_id")
    product_id = req_str(data, "product_id")
    qty = req_int(data, "qty_cases")
    day = get("route_days", route_day_id)
    st = get("stores", store_id)
    product = get("products", product_id)
    if qty <= 0:
        raise err(ERR_VALIDATION, "qty_cases must be > 0")
    if day["status"] != "IN_PROGRESS":
        raise err(ERR_ROUTE_DAY_NOT_IN_PROGRESS, "Route day is not IN_PROGRESS")
    if st["status"] != "ACTIVE":
        raise err(ERR_STORE_NOT_ACTIVE, "Store is not ACTIVE")
    if not svc.open_lots_for(day["id"], product_id):
        raise err(ERR_PRODUCT_NOT_ALLOCATED, "Product not allocated on this route day")
    eligible = svc.stale_eligible_lots(day["id"], product_id, day)
    if not eligible:
        raise err(
            ERR_PRODUCT_NOT_STALE_ELIGIBLE,
            "No lot of this product has days_to_expiry <= 5",
        )
    available = sum(svc.lot_remaining(l) for l in eligible)
    if available < qty:
        raise err(ERR_INSUFFICIENT_TRUCK_STOCK, "Insufficient stale-eligible stock")
    pinned = eligible[0]
    variant = st["credit_policy"]
    if variant == "FULL_RETAIL":
        credit_cents = qty * product["case_price_cents"]
    else:
        credit_cents = _round_half_up_div(qty * product["case_price_cents"] * SALVAGE_NUM, SALVAGE_DEN)
    existing = 0
    for c in store.db["stale_credits"].values():
        if (
            c["store_id"] == store_id
            and c["route_day_id"] == route_day_id
            and c["status"] in ("PENDING_APPROVAL", "APPROVED")
        ):
            existing += c["credit_cents"]
    if existing + credit_cents > st["store_credit_cap_cents"]:
        raise err(ERR_STORE_CREDIT_CAP_EXCEEDED, "Store credit cap exceeded")
    rec = new_record()
    rec.update(
        route_day_id=route_day_id,
        store_id=store_id,
        product_id=product_id,
        lot_id=pinned["id"],
        qty_cases=qty,
        pricing_variant=variant,
        credit_cents=credit_cents,
        created_by_user_id=uid,
        decided_by_user_id=None,
        reject_reason=None,
        status="PENDING_APPROVAL",
    )
    store.db["stale_credits"][rec["id"]] = rec
    return success(rec, 201)


@bp.get("/dsd/stale-credits/<creditId>")
def get_stale_credit(creditId):
    auth()
    return success(get("stale_credits", creditId), 200)


@bp.get("/dsd/stale-credits")
def list_stale_credits():
    auth()
    items, limit, offset, total = filter_sort_page(
        "stale_credits",
        {
            "store_id": request.args.get("store_id"),
            "route_day_id": request.args.get("route_day_id"),
            "product_id": request.args.get("product_id"),
            "lot_id": request.args.get("lot_id"),
            "status": request.args.get("status"),
        },
    )
    return list_response(items, limit, offset, total)


@bp.post("/dsd/stale-credits/<creditId>/approve")
def approve_stale_credit(creditId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    rec = get("stale_credits", creditId)
    if rec["status"] != "PENDING_APPROVAL":
        raise err(ERR_INVALID_STATE, "Credit is not PENDING_APPROVAL")
    if uid == rec["created_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Approver must differ from creator")
    lot = get("lots", rec["lot_id"])
    day = get("route_days", rec["route_day_id"])
    rec["status"] = "APPROVED"
    rec["decided_by_user_id"] = uid
    touch(rec)
    lot["stale_pulled_cases"] += rec["qty_cases"]
    lot["remaining_cases"] = svc.lot_remaining(lot)
    touch(lot)
    svc.recompute_day_totals(day)
    svc.ledger_moved(day["id"])
    return success(rec, 200)


@bp.post("/dsd/stale-credits/<creditId>/reject")
def reject_stale_credit(creditId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    rec = get("stale_credits", creditId)
    if rec["status"] != "PENDING_APPROVAL":
        raise err(ERR_INVALID_STATE, "Credit is not PENDING_APPROVAL")
    if uid == rec["created_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Rejecter must differ from creator")
    data = body()
    reason = opt_str(data, "reject_reason")
    if not reason:
        raise err(ERR_VALIDATION, "reject_reason is required")
    rec["status"] = "REJECTED"
    rec["decided_by_user_id"] = uid
    rec["reject_reason"] = reason
    touch(rec)
    return success(rec, 200)


@bp.post("/dsd/stale-credits/<creditId>/resubmit")
def resubmit_stale_credit(creditId):
    uid, role = auth()
    require_role(role, "RouteSalesRep")
    rec = get("stale_credits", creditId)
    if rec["status"] != "REJECTED":
        raise err(ERR_INVALID_STATE, "Credit is not REJECTED")
    day = get("route_days", rec["route_day_id"])
    if day["status"] != "IN_PROGRESS":
        raise err(ERR_ROUTE_DAY_NOT_IN_PROGRESS, "Route day is not IN_PROGRESS")
    rec["status"] = "PENDING_APPROVAL"
    rec["reject_reason"] = None
    rec["decided_by_user_id"] = None
    touch(rec)
    return success(rec, 200)
