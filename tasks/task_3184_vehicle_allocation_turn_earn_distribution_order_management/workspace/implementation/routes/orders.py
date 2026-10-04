"""Vehicle orders: entry, cancel, schedule, build, retrofit (PRD §3.6, §3.7)."""
from flask import Blueprint, request

import errors as err
from db import get_store, now_iso
from middleware import auth_context, require_dealer_owns
from response import success_list, success_object
from services.core import (active_restriction_for, commodity_cap_admits,
                           da_remaining_total, da_retail_pool, da_stock_pool,
                           get_da, recompute_dml)
from util import (bump, current_iso_week, current_week_monday, new_entity,
                  now_dt, opt_int, opt_str, parse_dt, req_enum, req_int,
                  req_str, req_week, week_monday)

bp = Blueprint("orders", __name__)

READ = ["RegionalAllocator", "Dealer", "ProductionScheduler", "LogisticsCoordinator"]
SCHED = ["ProductionScheduler"]


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _get_order_or_404(order_id):
    order = get_store("vehicle_orders").get(order_id)
    if order is None:
        raise err.not_found("order not found")
    return order


def _order_view(order: dict) -> dict:
    return {k: v for k, v in order.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Order entry (PRD §3.6) — immediate accept-or-reject.
# ---------------------------------------------------------------------------

@bp.post("/wholesale/orders")
def create_order():
    _role, user_id = auth_context(["Dealer"])
    body = _body()
    dealer_id = req_str(body, "dealer_id")
    model_line_id = req_str(body, "model_line_id")
    run_id = req_str(body, "run_id")
    order_kind = req_enum(body, "order_kind", ("RETAIL", "STOCK"))
    configuration = body.get("configuration")
    if not isinstance(configuration, dict):
        raise err.validation("configuration must be an object")
    trim = configuration.get("trim")
    if not isinstance(trim, str) or not trim:
        raise err.validation("configuration.trim must be a non-empty string")
    codes = configuration.get("commodity_codes", [])
    if not isinstance(codes, list) or any(not isinstance(c, str) for c in codes):
        raise err.validation("configuration.commodity_codes must be a string array")
    customer_ref = body.get("customer_ref")
    expected_version = req_int(body, "expected_dealer_allocation_version", 1)

    # Priority 3: entity-backed identity (Dealer owns the order's dealer_id).
    require_dealer_owns(user_id, dealer_id)

    # Priority 4: body FK existence in declared field order.
    dealer = get_store("dealers").get(dealer_id)
    if dealer is None:
        raise err.not_found("dealer not found")
    if model_line_id not in get_store("model_lines"):
        raise err.not_found("model line not found")
    run = get_store("allocation_runs").get(run_id)
    if run is None:
        raise err.not_found("run not found")
    da = get_da(run_id, dealer_id)
    if da is None:
        raise err.not_found("dealer allocation not found")

    # Priority 6: parent lifecycle gates.
    if run["status"] != "PUBLISHED":
        raise err.parent_not_active("run is not PUBLISHED")
    if dealer["status"] != "ACTIVE":
        raise err.parent_not_active("dealer is not ACTIVE")

    # OCC (§2.6): expected DealerAllocation version.
    if expected_version != da["version"]:
        raise err.stale_allocation_version()

    # Priority 7: configuration constraints.
    if order_kind == "RETAIL" and not customer_ref:
        raise err.invalid_configuration("RETAIL order requires customer_ref")
    if order_kind == "STOCK" and customer_ref is not None:
        raise err.invalid_configuration("STOCK order must not carry customer_ref")
    commodities = get_store("commodities")
    code_to_commodity = {c["code"]: c for c in commodities.values()}
    for code in codes:
        if code not in code_to_commodity:
            raise err.invalid_configuration(f"unknown commodity code: {code}")

    # Priority 8: commodity cap (pre-accept evaluation).
    for code in codes:
        commodity = code_to_commodity[code]
        restriction = active_restriction_for(commodity["id"], model_line_id)
        if restriction is not None:
            if not commodity_cap_admits(dealer_id, model_line_id, run_id,
                                        restriction, code):
                raise err.commodity_cap_exceeded()

    # Priority 9: allocation pool availability.
    retail_pool = da_retail_pool(da)
    stock_pool = da_stock_pool(da)
    if order_kind == "RETAIL":
        if retail_pool < 1:
            spillover_ok = (0 < run["retail_priority_pct"] < 100) and stock_pool >= 1
            if not spillover_ok:
                raise err.allocation_exhausted("retail pool exhausted")
    else:
        if stock_pool < 1:
            raise err.allocation_exhausted("stock pool exhausted")

    # Accept: SUBMITTED -> ACCEPTED immediately (create-path, §3.6).
    order = new_entity({
        "dealer_id": dealer_id,
        "model_line_id": model_line_id,
        "run_id": run_id,
        "order_kind": order_kind,
        "customer_ref": customer_ref if order_kind == "RETAIL" else None,
        "configuration": {"trim": trim, "commodity_codes": list(codes)},
        "state": "ACCEPTED",
        "build_state": "NOT_APPLICABLE",
        "retrofit_of_order_id": None,
        "consumed_units": 1,
        "scheduled_week": None,
        "scheduled_at": None,
        "built_at": None,
        "delivered_at": None,
        "cancel_reason": None,
    })
    get_store("vehicle_orders")[order["id"]] = order
    da["consumed_units"] += 1
    if order_kind == "RETAIL":
        da["retail_consumed_units"] += 1
    bump(da)
    recompute_dml(dealer_id, model_line_id)
    return success_object(_order_view(order), 201)


# ---------------------------------------------------------------------------
# Reads (PRD §3.6, §3.13 — customer visibility)
# ---------------------------------------------------------------------------

@bp.get("/wholesale/orders")
def list_orders():
    _role, user_id = auth_context(READ)
    rows = list(get_store("vehicle_orders").values())
    if _role == "Dealer":
        rows = [o for o in rows if o["dealer_id"] == user_id]
    for key in ("dealer_id", "run_id", "model_line_id", "state",
                "order_kind", "retrofit_of_order_id"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list([_order_view(o) for o in rows])


@bp.get("/wholesale/orders/<oid>")
def get_order(oid):
    _role, user_id = auth_context(READ)
    order = _get_order_or_404(oid)
    if _role == "Dealer" and order["dealer_id"] != user_id:
        raise err.forbidden()
    return success_object(_order_view(order))


# ---------------------------------------------------------------------------
# Cancel (PRD §3.6)
# ---------------------------------------------------------------------------

@bp.post("/wholesale/orders/<oid>/cancel")
def cancel_order(oid):
    _role, user_id = auth_context(["Dealer"])
    order = _get_order_or_404(oid)
    require_dealer_owns(user_id, order["dealer_id"])
    if order["state"] not in ("DRAFT", "SUBMITTED", "ACCEPTED"):
        raise err.invalid_state("order cannot be cancelled from this state")
    released = False
    if order["state"] == "ACCEPTED":
        order["consumed_units"] = 0
        da = get_da(order["run_id"], order["dealer_id"])
        if da is not None:
            da["consumed_units"] -= 1
            if order["order_kind"] == "RETAIL":
                da["retail_consumed_units"] -= 1
            bump(da)
        released = True
    body = _body()
    order["cancel_reason"] = body.get("cancel_reason")
    order["state"] = "CANCELLED"
    bump(order)
    if released:
        recompute_dml(order["dealer_id"], order["model_line_id"])
    return success_object(_order_view(order))


# ---------------------------------------------------------------------------
# Schedule / build / retrofit (PRD §3.7)
# ---------------------------------------------------------------------------

@bp.post("/wholesale/orders/<oid>/schedule")
def schedule_order(oid):
    auth_context(SCHED)
    order = _get_order_or_404(oid)
    if order["state"] != "ACCEPTED":
        raise err.invalid_state("order is not ACCEPTED")
    build_week = req_week(_body(), "build_week")
    if week_monday(build_week) < current_week_monday():
        raise err.window_closed("build_week earlier than current week")
    order["state"] = "SCHEDULED"
    order["scheduled_week"] = build_week
    order["scheduled_at"] = now_iso()
    bump(order)
    recompute_dml(order["dealer_id"], order["model_line_id"])
    return success_object(_order_view(order))


@bp.post("/wholesale/orders/<oid>/build")
def build_order(oid):
    auth_context(SCHED)
    order = _get_order_or_404(oid)
    if order["state"] != "SCHEDULED":
        raise err.invalid_state("order is not SCHEDULED")
    if week_monday(order["scheduled_week"]) < current_week_monday():
        raise err.window_closed("build before scheduled week")
    body = _body()
    build_mode = body.get("build_mode")
    if build_mode is not None and build_mode not in ("WITHOUT_FEATURE",):
        raise err.validation("build_mode must be WITHOUT_FEATURE")
    if build_mode == "WITHOUT_FEATURE":
        codes = (order["configuration"] or {}).get("commodity_codes", [])
        commodities = {c["code"]: c for c in get_store("commodities").values()}
        for code in codes:
            commodity = commodities.get(code)
            if commodity is None:
                continue
            restriction = active_restriction_for(commodity["id"], order["model_line_id"])
            if restriction is not None:
                if not restriction["allow_partial_build"]:
                    raise err.partial_build_not_allowed()
                # Surge mode: drop the feature, mark pending retrofit (§3.7).
                order["configuration"]["commodity_codes"] = [
                    c for c in codes if c != code
                ]
                order["_omitted_commodity_code"] = code
                order["build_state"] = "PENDING_RETROFIT"
                break
    order["state"] = "BUILT"
    order["built_at"] = now_iso()
    bump(order)
    recompute_dml(order["dealer_id"], order["model_line_id"])
    return success_object(_order_view(order))


@bp.post("/wholesale/orders/<oid>/retrofit")
def retrofit_order(oid):
    auth_context(SCHED)
    order = _get_order_or_404(oid)
    if order["state"] not in ("BUILT", "DELIVERED") or order["build_state"] != "PENDING_RETROFIT":
        raise err.invalid_state("order is not pending retrofit")
    # The omitting restriction must no longer be ACTIVE (§3.7).
    blocked = False
    omitted_code = order.get("_omitted_commodity_code")
    commodities = get_store("commodities").values()
    if omitted_code is not None:
        for commodity in commodities:
            if commodity["code"] == omitted_code:
                if active_restriction_for(commodity["id"], order["model_line_id"]) is not None:
                    blocked = True
                break
    else:
        # Fall back: any constrained commodity with an ACTIVE restriction on
        # the line gates the retrofit.
        for commodity in commodities:
            if active_restriction_for(commodity["id"], order["model_line_id"]) is not None:
                blocked = True
                break
    if blocked:
        raise err.retrofit_blocked()
    order["build_state"] = "RETROFITTED"
    bump(order)
    # Child retrofit work order: ACCEPTED, consumes no pool (§3.7).
    child = new_entity({
        "dealer_id": order["dealer_id"],
        "model_line_id": order["model_line_id"],
        "run_id": order["run_id"],
        "order_kind": order["order_kind"],
        "customer_ref": order.get("customer_ref"),
        "configuration": dict(order["configuration"]),
        "state": "ACCEPTED",
        "build_state": "NOT_APPLICABLE",
        "retrofit_of_order_id": order["id"],
        "consumed_units": 0,
        "scheduled_week": None,
        "scheduled_at": None,
        "built_at": None,
        "delivered_at": None,
        "cancel_reason": None,
    })
    get_store("vehicle_orders")[child["id"]] = child
    return success_object(_order_view(order))
