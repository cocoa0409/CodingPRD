"""Route settlement (dual-ledger reconciliation) and service-level snapshots."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, request

import db as store
import services as svc
from errors import (
    ERR_INVALID_STATE,
    ERR_NO_DELIVERED_ORDERS,
    ERR_REP_NOT_ASSIGNED,
    ERR_ROUTE_DAY_NOT_IN_PROGRESS,
    ERR_SETTLEMENT_ALREADY_EXISTS,
    ERR_UNRESOLVED_ORDERS,
    ERR_VALIDATION,
    err,
)
from helpers import (
    auth,
    body,
    clock_now_iso,
    filter_sort_page,
    get,
    new_record,
    req_date,
    req_int,
    req_str,
    require_role,
    touch,
)
from response import list_response, success

bp = Blueprint("settlement", __name__)


# ---------------------------------------------------------------------------
# settlements
# ---------------------------------------------------------------------------

@bp.post("/dsd/route-settlements")
def create_settlement():
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    data = body()
    route_day_id = req_str(data, "route_day_id")
    day = get("route_days", route_day_id)
    if day["status"] != "IN_PROGRESS":
        raise err(ERR_ROUTE_DAY_NOT_IN_PROGRESS, "Route day is not IN_PROGRESS")
    if svc.find_settlement(route_day_id) is not None:
        raise err(ERR_SETTLEMENT_ALREADY_EXISTS, "A settlement already exists for this route day")
    rec = new_record()
    rec.update(
        route_day_id=route_day_id,
        status="OPEN",
        gross_delivered_cents=0,
        credits_cents=0,
        forward_expected_cents=0,
        chronological_expected_cents=0,
        recon_delta_cents=0,
        cash_collected_cents=None,
        variance_cents=None,
        posted_at=None,
    )
    store.db["settlements"][rec["id"]] = rec
    svc.recompute_settlement(rec)
    return success(rec, 201)


@bp.get("/dsd/route-settlements/<settlementId>")
def get_settlement(settlementId):
    auth()
    return success(get("settlements", settlementId), 200)


@bp.get("/dsd/route-settlements")
def list_settlements():
    auth()
    items, limit, offset, total = filter_sort_page(
        "settlements", {"route_day_id": request.args.get("route_day_id")}
    )
    return list_response(items, limit, offset, total)


@bp.post("/dsd/route-settlements/<settlementId>/balance")
def balance_settlement(settlementId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    rec = get("settlements", settlementId)
    if rec["status"] not in ("OPEN", "BALANCED"):
        raise err(ERR_INVALID_STATE, "Settlement cannot be balanced from %s" % rec["status"])
    data = body()
    cash = req_int(data, "cash_collected_cents")
    rec["cash_collected_cents"] = cash
    svc.recompute_settlement(rec)
    if abs(rec["variance_cents"]) <= svc.VARIANCE_TOLERANCE_CENTS:
        rec["status"] = "BALANCED"
    else:
        rec["status"] = "OPEN"
    touch(rec)
    return success(rec, 200)


@bp.post("/dsd/route-settlements/<settlementId>/post")
def post_settlement(settlementId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    rec = get("settlements", settlementId)
    if rec["status"] != "BALANCED":
        raise err(ERR_INVALID_STATE, "Settlement is not BALANCED")
    day = get("route_days", rec["route_day_id"])
    for order in store.db["orders"].values():
        if order["route_day_id"] == day["id"] and order["status"] == "SUBMITTED":
            raise err(ERR_UNRESOLVED_ORDERS, "Route day has SUBMITTED orders")
    rec["status"] = "POSTED"
    rec["posted_at"] = clock_now_iso()
    touch(rec)
    for lot in svc.day_lots(day["id"]):
        if lot["status"] == "OPEN":
            lot["returned_cases"] = svc.lot_remaining(lot)
            lot["remaining_cases"] = svc.lot_remaining(lot)
            lot["status"] = "CLOSED"
            touch(lot)
    svc.recompute_day_totals(day, bump=False)
    day["status"] = "SETTLED"
    touch(day)
    return success(rec, 200)


@bp.post("/dsd/route-settlements/<settlementId>/dispute")
def dispute_settlement(settlementId):
    uid, role = auth()
    require_role(role, "RouteSalesRep")
    rec = get("settlements", settlementId)
    day = get("route_days", rec["route_day_id"])
    route = get("routes", day["route_id"])
    if route["rsr_id"] != uid:
        raise err(ERR_REP_NOT_ASSIGNED, "Acting rep is not assigned to this route")
    if rec["status"] not in ("OPEN", "BALANCED"):
        raise err(ERR_INVALID_STATE, "Settlement cannot be disputed from %s" % rec["status"])
    rec["status"] = "DISPUTED"
    touch(rec)
    return success(rec, 200)


@bp.post("/dsd/route-settlements/<settlementId>/resolve")
def resolve_settlement(settlementId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    rec = get("settlements", settlementId)
    if rec["status"] != "DISPUTED":
        raise err(ERR_INVALID_STATE, "Settlement is not DISPUTED")
    rec["status"] = "OPEN"
    touch(rec)
    return success(rec, 200)


# ---------------------------------------------------------------------------
# service level snapshots
# ---------------------------------------------------------------------------

def _rate4(num, den):
    dec = (Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(dec)


@bp.post("/dsd/routes/<routeId>/service-level-snapshots")
def create_snapshot(routeId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    route = get("routes", routeId)
    data = body()
    period_start = req_date(data, "period_start")
    period_end = req_date(data, "period_end")
    if date.fromisoformat(period_end) <= date.fromisoformat(period_start):
        raise err(ERR_VALIDATION, "period_end must be after period_start")
    in_window_days = [
        d
        for d in store.db["route_days"].values()
        if d["route_id"] == routeId and period_start <= d["service_date"] < period_end
    ]
    day_ids = {d["id"] for d in in_window_days}
    delivered = [
        o
        for o in store.db["orders"].values()
        if o["route_day_id"] in day_ids and o["status"] == "DELIVERED"
    ]
    if not delivered:
        raise err(ERR_NO_DELIVERED_ORDERS, "Window contains no DELIVERED orders")
    order_ids = {o["id"] for o in delivered}
    lines = [l for l in store.db["order_lines"].values() if l["order_id"] in order_ids]
    sum_delivered = sum(l["qty_delivered_cases"] for l in lines)
    sum_ordered = sum(l["qty_ordered_cases"] for l in lines)
    fill_rate = _rate4(sum_delivered, sum_ordered)
    oos_rate = float(
        (Decimal(1) - Decimal(str(fill_rate))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    )
    if oos_rate < 0.02:
        grade = "GOLD"
    elif oos_rate < 0.05:
        grade = "SILVER"
    else:
        grade = "BRONZE"
    stale_cents = sum(
        c["credit_cents"]
        for c in store.db["stale_credits"].values()
        if c["route_day_id"] in day_ids and c["status"] == "APPROVED"
    )
    gross_cents = sum(o["gross_total_cents"] for o in delivered)
    stale_ratio = _rate4(stale_cents, gross_cents) if gross_cents > 0 else 0.0
    flag = "PERFORMANCE_WATCH" if stale_ratio > 0.08 else "CLEAR"
    rec = new_record()
    rec.update(
        route_id=routeId,
        period_start=period_start,
        period_end=period_end,
        orders_count=len(delivered),
        fill_rate=fill_rate,
        oos_rate=oos_rate,
        service_grade=grade,
        stale_ratio=stale_ratio,
        performance_flag_result=flag,
    )
    store.db["snapshots"][rec["id"]] = rec
    route["performance_flag"] = flag
    touch(route)
    return success(rec, 201)


@bp.get("/dsd/service-level-snapshots/<snapshotId>")
def get_snapshot(snapshotId):
    auth()
    return success(get("snapshots", snapshotId), 200)


@bp.get("/dsd/service-level-snapshots")
def list_snapshots():
    auth()
    items, limit, offset, total = filter_sort_page(
        "snapshots", {"route_id": request.args.get("route_id")}
    )
    return list_response(items, limit, offset, total)
