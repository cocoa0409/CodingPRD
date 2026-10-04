"""Stores, employees, register shifts, cart coin ledger, and labor windows."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import svc
from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_dt,
    f_enum,
    f_int,
    f_str,
    forbid_unless,
    new_row,
    paginate,
    q_enum,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("stores", __name__)


def _manager_owns(store_id):
    """Tier-2 ownership for StoreManager: X-User-ID is the acting store id."""
    forbid_unless(g.user_id == store_id)


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
@bp.post("/v1/stores")
@endpoint("OperationsAdmin")
def create_store():
    payload = body()
    code = f_str(payload, "code")
    name = f_str(payload, "name")
    tier = f_enum(payload, "tier", calc.STORE_TIERS)
    weekly_labor_budget_cents = f_int(payload, "weekly_labor_budget_cents", minimum=0)
    store = new_row(
        "Store",
        code=code,
        name=name,
        tier=tier,
        weekly_labor_budget_cents=weekly_labor_budget_cents,
        coins_outstanding=0,
        coin_liability_cents=0,
        refund_liability_cents=0,
        refund_paid_cents=0,
        finds_sell_through_pct=Decimal("0.0"),
        status="ACTIVE",
    )
    db.stores[store["id"]] = store
    return respond_object(dump(store), 201)


@bp.get("/v1/stores/<store_id>")
@endpoint("OperationsAdmin", "StoreManager", "CategoryManager", "CustomerServiceAgent")
def read_store(store_id):
    store = svc.need_store(store_id)
    if g.role == "StoreManager":
        _manager_owns(store["id"])
    return respond_object(dump(store))


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
@bp.post("/v1/stores/<store_id>/employees")
@endpoint("StoreManager")
def create_employee(store_id):
    store = svc.need_store(store_id)
    _manager_owns(store["id"])
    payload = body()
    name = f_str(payload, "name")
    role = f_enum(payload, "role", calc.EMPLOYEE_ROLES)
    employee = new_row(
        "Employee",
        store_id=store["id"],
        name=name,
        role=role,
        status="ACTIVE",
    )
    db.employees[employee["id"]] = employee
    return respond_object(dump(employee), 201)


@bp.get("/v1/stores/<store_id>/employees")
@endpoint("StoreManager", "OperationsAdmin")
def list_employees(store_id):
    store = svc.need_store(store_id)
    if g.role == "StoreManager":
        _manager_owns(store["id"])
    role = q_enum("role", calc.EMPLOYEE_ROLES)
    rows = sort_created(
        [e for e in db.employees.values() if e["store_id"] == store["id"]]
    )
    if role is not None:
        rows = [r for r in rows if r["role"] == role]
    return paginate(rows)


@bp.get("/v1/employees/<employee_id>")
@endpoint("StoreManager", "OperationsAdmin")
def read_employee(employee_id):
    employee = svc.need_employee(employee_id)
    if g.role == "StoreManager":
        _manager_owns(employee["store_id"])
    return respond_object(dump(employee))


# ---------------------------------------------------------------------------
# Cart coin ledger
# ---------------------------------------------------------------------------
@bp.post("/v1/stores/<store_id>/cart-coin-events")
@endpoint("Cashier", "StoreManager")
def create_coin_event(store_id):
    store = svc.need_store(store_id)
    if g.role == "StoreManager":
        _manager_owns(store["id"])
    payload = body()
    event_type = f_enum(payload, "event_type", calc.COIN_EVENT_TYPES)
    coin_count = f_int(payload, "coin_count")
    # tier 8 -- structural: positive counts except for signed adjustments
    if event_type in ("INSERT", "RETURN", "CORRAL_COLLECT") and coin_count <= 0:
        raise ApiError("ERR_VALIDATION",
                       "coin_count must be positive for %s events." % event_type)
    # tier 9 -- fiscal: never drive the running balance negative
    svc.apply_coin_event(store, event_type, coin_count)
    event = new_row(
        "CartCoinEvent",
        audited=False,
        store_id=store["id"],
        event_type=event_type,
        coin_count=coin_count,
    )
    db.cart_coin_events[event["id"]] = event
    return respond_object(dump(event), 201)


@bp.get("/v1/stores/<store_id>/cart-coin-events")
@endpoint("StoreManager", "OperationsAdmin")
def list_coin_events(store_id):
    store = svc.need_store(store_id)
    if g.role == "StoreManager":
        _manager_owns(store["id"])
    event_type = q_enum("event_type", calc.COIN_EVENT_TYPES)
    rows = svc.coin_events_of_store(store["id"])
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    return paginate(rows)


@bp.get("/v1/stores/<store_id>/cart-reconciliation")
@endpoint("StoreManager", "OperationsAdmin")
def cart_reconciliation(store_id):
    store = svc.need_store(store_id)
    if g.role == "StoreManager":
        _manager_owns(store["id"])
    return respond_object(svc.coin_reconciliation(store))


# ---------------------------------------------------------------------------
# Register shifts and scan rate
# ---------------------------------------------------------------------------
@bp.post("/v1/stores/<store_id>/register-shifts")
@endpoint("StoreManager")
def create_shift(store_id):
    store = svc.need_store(store_id)
    _manager_owns(store["id"])
    payload = body()
    cashier_id = f_str(payload, "cashier_id")
    # tier 4 -- body FK existence
    employee = svc.need_employee(cashier_id)
    # tier 8 -- the named employee must be a cashier
    if employee["role"] != "CASHIER":
        raise ApiError("ERR_CASHIER_ROLE_REQUIRED")
    shift = new_row(
        "RegisterShift",
        store_id=store["id"],
        cashier_id=employee["id"],
        started_at=db.clock,
        closed_at=None,
        items_scanned=0,
        voids=0,
        provisional_scan_rate=Decimal("0.0"),
        final_scan_rate=None,
        compliance=None,
        status="OPEN",
    )
    db.register_shifts[shift["id"]] = shift
    return respond_object(dump(shift), 201)


@bp.get("/v1/stores/<store_id>/register-shifts")
@endpoint("StoreManager", "OperationsAdmin")
def list_store_shifts(store_id):
    store = svc.need_store(store_id)
    if g.role == "StoreManager":
        _manager_owns(store["id"])
    status = q_enum("status", calc.SHIFT_STATUSES)
    rows = sort_created(
        [s for s in db.register_shifts.values() if s["store_id"] == store["id"]]
    )
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows)


@bp.get("/v1/register-shifts/<shift_id>")
@endpoint("StoreManager", "Cashier", "OperationsAdmin")
def read_shift(shift_id):
    shift = svc.need_shift(shift_id)
    if g.role == "StoreManager":
        _manager_owns(shift["store_id"])
    elif g.role == "Cashier":
        forbid_unless(g.user_id == shift["cashier_id"])
    return respond_object(dump(shift))


@bp.get("/v1/employees/<employee_id>/register-shifts")
@endpoint("StoreManager", "OperationsAdmin")
def list_employee_shifts(employee_id):
    employee = svc.need_employee(employee_id)
    if g.role == "StoreManager":
        _manager_owns(employee["store_id"])
    rows = sort_created(
        [s for s in db.register_shifts.values() if s["cashier_id"] == employee["id"]]
    )
    return paginate(rows)


@bp.post("/v1/register-shifts/<shift_id>/scan")
@endpoint("Cashier")
def scan_shift(shift_id):
    shift = svc.need_shift(shift_id)
    forbid_unless(g.user_id == shift["cashier_id"])
    payload = body()
    items_count = f_int(payload, "items_count", minimum=0)
    voids_count = f_int(payload, "voids_count", required=False, default=0, minimum=0)
    if shift["status"] != "OPEN":
        raise ApiError("ERR_SHIFT_NOT_OPEN")
    shift["items_scanned"] += items_count
    shift["voids"] += voids_count
    shift["provisional_scan_rate"] = calc.provisional_rate(
        shift["items_scanned"], shift["started_at"], db.clock
    )
    touch(shift)
    return respond_object(dump(shift))


@bp.post("/v1/register-shifts/<shift_id>/close")
@endpoint("StoreManager")
def close_shift(shift_id):
    shift = svc.need_shift(shift_id)
    _manager_owns(shift["store_id"])
    if shift["status"] != "OPEN":
        raise ApiError("ERR_SHIFT_NOT_OPEN")
    shift["closed_at"] = db.clock
    final = calc.final_rate(
        shift["items_scanned"], shift["voids"], shift["started_at"], shift["closed_at"]
    )
    shift["final_scan_rate"] = final
    shift["compliance"] = calc.compliance_for(final)
    shift["status"] = "CLOSED"
    touch(shift)
    return respond_object(dump(shift))


# ---------------------------------------------------------------------------
# Labor windows
# ---------------------------------------------------------------------------
@bp.post("/v1/stores/<store_id>/labor-windows")
@endpoint("StoreManager")
def create_labor_window(store_id):
    store = svc.need_store(store_id)
    _manager_owns(store["id"])
    payload = body()
    aisle_zone = f_str(payload, "aisle_zone")
    role = f_enum(payload, "role", calc.EMPLOYEE_ROLES)
    starts_at = f_dt(payload, "starts_at")
    ends_at = f_dt(payload, "ends_at")
    if ends_at <= starts_at:
        raise ApiError("ERR_VALIDATION", "ends_at must be after starts_at.")
    cost_cents = calc.window_cost(role, starts_at, ends_at)
    # tier 7 -- temporal: half-open overlap per (store, aisle_zone)
    for w in db.labor_windows.values():
        if (
            w["store_id"] == store["id"]
            and w["aisle_zone"] == aisle_zone
            and w["status"] in ("PLANNED", "CONFIRMED")
            and starts_at < w["ends_at"]
            and w["starts_at"] < ends_at
        ):
            raise ApiError("ERR_WINDOW_OVERLAP")
    # tier 8 -- structural: weekly window count limit
    in_week = calc.windows_in_week(db.labor_windows.values(), store["id"], starts_at)
    if len(in_week) >= calc.LABOR_WEEKLY_WINDOW_LIMIT:
        raise ApiError("ERR_WINDOW_LIMIT_EXCEEDED")
    # tier 9 -- fiscal rule last
    spend = sum(w["cost_cents"] for w in in_week)
    if spend + cost_cents > store["weekly_labor_budget_cents"]:
        raise ApiError("ERR_LABOR_BUDGET_EXCEEDED")
    window = new_row(
        "LaborWindow",
        store_id=store["id"],
        aisle_zone=aisle_zone,
        role=role,
        starts_at=starts_at,
        ends_at=ends_at,
        cost_cents=cost_cents,
        status="PLANNED",
    )
    db.labor_windows[window["id"]] = window
    return respond_object(dump(window), 201)


@bp.get("/v1/stores/<store_id>/labor-windows")
@endpoint("StoreManager", "OperationsAdmin")
def list_labor_windows(store_id):
    store = svc.need_store(store_id)
    if g.role == "StoreManager":
        _manager_owns(store["id"])
    status = q_enum("status", calc.LABOR_WINDOW_STATUSES)
    rows = sort_created(
        [w for w in db.labor_windows.values() if w["store_id"] == store["id"]]
    )
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows)


@bp.get("/v1/labor-windows/<window_id>")
@endpoint("StoreManager", "OperationsAdmin")
def read_labor_window(window_id):
    window = svc.need_labor_window(window_id)
    if g.role == "StoreManager":
        _manager_owns(window["store_id"])
    return respond_object(dump(window))


@bp.post("/v1/labor-windows/<window_id>/confirm")
@endpoint("StoreManager")
def confirm_labor_window(window_id):
    window = svc.need_labor_window(window_id)
    _manager_owns(window["store_id"])
    if window["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")
    window["status"] = "CONFIRMED"
    touch(window)
    return respond_object(dump(window))


@bp.post("/v1/labor-windows/<window_id>/cancel")
@endpoint("StoreManager")
def cancel_labor_window(window_id):
    window = svc.need_labor_window(window_id)
    _manager_owns(window["store_id"])
    if window["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE")
    window["status"] = "CANCELLED"
    touch(window)
    return respond_object(dump(window))
