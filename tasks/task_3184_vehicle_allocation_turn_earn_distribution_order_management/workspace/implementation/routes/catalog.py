"""Catalog + test-driving routes: clock, seed, regions, dealers, model lines."""
from flask import Blueprint, request

import errors as err
from db import get_store, set_clock
from middleware import auth_context
from response import success_list, success_object
from services.core import FILING_WINDOW_DAYS  # noqa: F401 (kept for parity)
from services.core import get_dml, recompute_dml
from util import (REGION_CODE_RE, new_entity, req_field, req_int, req_str,
                  req_ts, req_week, sweep_all_restrictions, sweep_all_trades,
                  week_monday, fmt_dt)

bp = Blueprint("catalog", __name__)

ALL_READ = ["RegionalAllocator", "Dealer", "ProductionScheduler",
            "LogisticsCoordinator", "CommodityManager"]
ALLOC_ONLY = ["RegionalAllocator"]


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


# ---------------------------------------------------------------------------
# Test-driving hooks (PRD §3.14, §2.9)
# ---------------------------------------------------------------------------

@bp.post("/wholesale/_clock/set_current_utc")
def clock_set():
    auth_context(ALLOC_ONLY)
    to_iso = req_ts(_body(), "to_iso8601")
    set_clock(to_iso)
    sweep_all_restrictions()
    sweep_all_trades()
    return success_object({"current_utc": to_iso}, 200)


@bp.post("/wholesale/_seed/order-at-week")
def seed_order_at_week():
    auth_context(ALLOC_ONLY)
    body = _body()
    dealer_id = req_str(body, "dealer_id")
    model_line_id = req_str(body, "model_line_id")
    run_id = req_str(body, "run_id")
    order_kind = body.get("order_kind", "STOCK")
    if order_kind not in ("RETAIL", "STOCK"):
        raise err.validation("order_kind must be RETAIL or STOCK")
    scheduled_week = req_week(body, "scheduled_week")
    customer_ref = body.get("customer_ref")

    dealers = get_store("dealers")
    lines = get_store("model_lines")
    runs = get_store("allocation_runs")
    if dealer_id not in dealers:
        raise err.not_found("dealer not found")
    if model_line_id not in lines:
        raise err.not_found("model line not found")
    if run_id not in runs:
        raise err.not_found("run not found")
    if order_kind == "RETAIL" and not customer_ref:
        customer_ref = "SEED"
    run = runs[run_id]

    monday = week_monday(scheduled_week)
    order = new_entity({
        "dealer_id": dealer_id,
        "model_line_id": model_line_id,
        "run_id": run_id,
        "order_kind": order_kind,
        "customer_ref": customer_ref if order_kind == "RETAIL" else None,
        "configuration": {"trim": "SEED", "commodity_codes": []},
        "state": "BUILT",
        "build_state": "NOT_APPLICABLE",
        "retrofit_of_order_id": None,
        "consumed_units": 1,
        "scheduled_week": scheduled_week,
        "scheduled_at": fmt_dt(monday),
        "built_at": fmt_dt(monday),
        "delivered_at": None,
        "cancel_reason": None,
    })
    get_store("vehicle_orders")[order["id"]] = order
    # Consume 1 pool unit exactly as a normal accept would (§3.14).
    from services.core import get_da
    da = get_da(run_id, dealer_id)
    if da is not None:
        da["consumed_units"] += 1
        if order_kind == "RETAIL":
            da["retail_consumed_units"] += 1
        from util import bump
        bump(da)
    recompute_dml(dealer_id, model_line_id)
    return success_object(order, 201)


# ---------------------------------------------------------------------------
# Regions (PRD §3.1)
# ---------------------------------------------------------------------------

@bp.post("/wholesale/regions")
def create_region():
    auth_context(ALLOC_ONLY)
    body = _body()
    code = req_str(body, "code")
    if not REGION_CODE_RE.match(code):
        raise err.validation("code must be 2-20 uppercase alnum + dash")
    name = req_str(body, "name")
    for r in get_store("regions").values():
        if r["code"] == code:
            raise err.duplicate("region code already exists")
    region = new_entity({"code": code, "name": name, "status": "ACTIVE"})
    get_store("regions")[region["id"]] = region
    return success_object(region, 201)


@bp.get("/wholesale/regions")
def list_regions():
    auth_context(ALL_READ)
    rows = list(get_store("regions").values())
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.get("/wholesale/regions/<rid>")
def get_region(rid):
    auth_context(ALL_READ)
    region = get_store("regions").get(rid)
    if region is None:
        raise err.not_found("region not found")
    return success_object(region)


# ---------------------------------------------------------------------------
# Dealers (PRD §3.1)
# ---------------------------------------------------------------------------

def dealer_view(dealer: dict) -> dict:
    view = dict(dealer)
    view["carryover_credit_units"] = round(sum(
        dml["earned_credit_units"]
        for dml in get_store("dealer_model_lines").values()
        if dml["dealer_id"] == dealer["id"]
    ), 2)
    return view


@bp.post("/wholesale/dealers")
def create_dealer():
    auth_context(ALLOC_ONLY)
    body = _body()
    region_id = req_str(body, "region_id")
    dealer_code = req_str(body, "dealer_code")
    name = req_str(body, "name")
    opened_on = req_ts(body, "opened_on")
    if region_id not in get_store("regions"):
        raise err.not_found("region not found")
    for d in get_store("dealers").values():
        if d["dealer_code"] == dealer_code:
            raise err.duplicate("dealer code already exists")
    dealer = new_entity({
        "region_id": region_id,
        "dealer_code": dealer_code,
        "name": name,
        "opened_on": opened_on,
        "status": "ACTIVE",
    })
    get_store("dealers")[dealer["id"]] = dealer
    return success_object(dealer_view(dealer), 201)


@bp.get("/wholesale/dealers")
def list_dealers():
    auth_context(ALL_READ)
    rows = list(get_store("dealers").values())
    if request.args.get("region_id"):
        rows = [r for r in rows if r["region_id"] == request.args["region_id"]]
    if request.args.get("status"):
        rows = [r for r in rows if r["status"] == request.args["status"]]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list([dealer_view(d) for d in rows])


@bp.get("/wholesale/dealers/<did>")
def get_dealer(did):
    auth_context(ALL_READ)
    dealer = get_store("dealers").get(did)
    if dealer is None:
        raise err.not_found("dealer not found")
    return success_object(dealer_view(dealer))


@bp.get("/wholesale/dealers/<did>/model-lines")
def list_dealer_model_lines_for_dealer(did):
    auth_context(["RegionalAllocator", "Dealer", "ProductionScheduler"])
    dealer = get_store("dealers").get(did)
    if dealer is None:
        raise err.not_found("dealer not found")
    rows = [d for d in get_store("dealer_model_lines").values()
            if d["dealer_id"] == did]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


# ---------------------------------------------------------------------------
# Model lines (PRD §3.1)
# ---------------------------------------------------------------------------

@bp.post("/wholesale/model-lines")
def create_model_line():
    auth_context(ALLOC_ONLY)
    body = _body()
    model_code = req_str(body, "model_code")
    name = req_str(body, "name")
    for m in get_store("model_lines").values():
        if m["model_code"] == model_code:
            raise err.duplicate("model code already exists")
    line = new_entity({"model_code": model_code, "name": name, "status": "ACTIVE"})
    get_store("model_lines")[line["id"]] = line
    return success_object(line, 201)


@bp.get("/wholesale/model-lines")
def list_model_lines():
    auth_context(ALL_READ)
    rows = list(get_store("model_lines").values())
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.get("/wholesale/model-lines/<mid>")
def get_model_line(mid):
    auth_context(ALL_READ)
    line = get_store("model_lines").get(mid)
    if line is None:
        raise err.not_found("model line not found")
    return success_object(line)
