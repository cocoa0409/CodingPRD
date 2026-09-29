"""Shop bays and off-season overhaul work orders."""

from datetime import timedelta

from flask import Blueprint

import calc
import derive
import fetch
import store
import validate
from auth import ALL_ROLES, require_roles
from envelope import list_response
from errors import (
    fail,
    invalid,
    ERR_BAY_CAPACITY_CONFLICT,
    ERR_COMPONENT_ATTRACTION_MISMATCH,
    ERR_INSPECTION_STATE_INVALID,
    ERR_STALE_SHOP_BAY_VERSION,
    ERR_WORK_ORDER_STATE_INVALID,
)
from reply import computed, made, saved

bp = Blueprint("overhaul", __name__)

PHASES = ("SCHEDULED", "TEARDOWN", "INSPECTION", "REBUILD", "RECOMMISSIONED")
SUCCESSOR = {
    "SCHEDULED": "TEARDOWN",
    "TEARDOWN": "INSPECTION",
    "INSPECTION": "REBUILD",
    "REBUILD": "RECOMMISSIONED",
}


# ---------------------------------------------------------------------------
# shop bays
# ---------------------------------------------------------------------------

@bp.post("/park-ops/shop-bays")
@require_roles("ParkOpsAdmin")
def open_shop_bay():
    data = validate.body()
    name = validate.str_field(data, "name")
    capacity = validate.int_field(data, "concurrent_slot_capacity", minimum=1)
    row = store.create("shop_bays", name=name,
                       concurrent_slot_capacity=capacity)
    return made(derive.ser_shop_bay, row)


@bp.get("/park-ops/shop-bays/<bay_id>")
@require_roles(*ALL_ROLES)
def read_shop_bay(bay_id):
    return computed(derive.ser_shop_bay(fetch.shop_bay(bay_id)))


@bp.get("/park-ops/shop-bays")
@require_roles(*ALL_ROLES)
def list_shop_bays():
    return list_response(store.rows("shop_bays"), derive.ser_shop_bay,
                         order=("created_at",))


# ---------------------------------------------------------------------------
# overhaul work orders
# ---------------------------------------------------------------------------

def _covers(order, day):
    start = store.date_of(order["window_start_date"])
    end = store.date_of(order["window_end_date"])
    return start is not None and end is not None and start <= day <= end


def _capacity_conflict(bay, window_start, window_end):
    """The buffered bay-occupancy test of PRD 3.9.

    The requested window is widened by one changeover day at each end; the
    existing bookings are compared unwidened.
    """
    existing = [o for o in store.rows("work_orders")
                if o["shop_bay_id"] == bay["id"]
                and o["status"] != "RECOMMISSIONED"]
    day = window_start - timedelta(days=1)
    last = window_end + timedelta(days=1)
    while day <= last:
        booked = len([o for o in existing if _covers(o, day)])
        if booked >= bay["concurrent_slot_capacity"]:
            return True
        day = day + timedelta(days=1)
    return False


@bp.post("/park-ops/overhaul-work-orders")
@require_roles("MaintenanceManager")
def schedule_work_order():
    data = validate.body()
    attraction = fetch.fk("attractions", data.get("attraction_id"))
    component = fetch.fk("components", data.get("component_id"))
    bay = fetch.fk("shop_bays", data.get("shop_bay_id"))
    validate.id_field(data, "attraction_id")
    validate.id_field(data, "component_id")
    validate.id_field(data, "shop_bay_id")
    expected = validate.int_field(data, "expected_shop_bay_version")
    window_start = validate.date_field(data, "window_start_date")
    window_end = validate.date_field(data, "window_end_date")
    parts_subtotal = validate.int_field(data, "parts_subtotal_cents",
                                        minimum=0)
    labor_hours = validate.int_field(data, "labor_hours", minimum=0)
    expedite = validate.bool_field(data, "expedite_requested", default=False)
    if window_end < window_start:
        invalid("window_end_date must be the same as or later than "
                "window_start_date.")
    if expected != bay["version"]:
        fail(ERR_STALE_SHOP_BAY_VERSION,
             "expected_shop_bay_version does not match the shop bay.")
    if component["attraction_id"] != attraction["id"]:
        fail(ERR_COMPONENT_ATTRACTION_MISMATCH,
             "The component is installed on a different attraction.")
    if _capacity_conflict(bay, window_start, window_end):
        fail(ERR_BAY_CAPACITY_CONFLICT,
             "The bay has no free slot across the buffered occupancy window.")
    estimate = calc.overhaul_estimate(parts_subtotal, labor_hours,
                                      window_start, window_end, expedite)
    row = store.create(
        "work_orders",
        attraction_id=attraction["id"],
        component_id=component["id"],
        shop_bay_id=bay["id"],
        window_start_date=window_start.isoformat(),
        window_end_date=window_end.isoformat(),
        parts_subtotal_cents=parts_subtotal,
        labor_hours=labor_hours,
        expedite_requested=expedite,
        status="SCHEDULED",
        recommissioned_at=None,
        **estimate,
    )
    return made(derive.ser_work_order, row)


@bp.get("/park-ops/overhaul-work-orders/<order_id>")
@require_roles(*ALL_ROLES)
def read_work_order(order_id):
    return computed(derive.ser_work_order(fetch.work_order(order_id)))


@bp.get("/park-ops/overhaul-work-orders")
@require_roles(*ALL_ROLES)
def list_work_orders():
    return list_response(
        store.rows("work_orders"),
        derive.ser_work_order,
        filters=(("attraction_id", "str"), ("component_id", "str"),
                 ("shop_bay_id", "str"), ("status", "str"),
                 ("off_season", "bool")),
        order=("window_start_date",),
    )


@bp.post("/park-ops/overhaul-work-orders/<order_id>/advance")
@require_roles("MaintenanceManager")
def advance_work_order(order_id):
    order = fetch.work_order(order_id)
    data = validate.body()
    target = validate.enum_field(data, "target_phase", PHASES)
    current = order["status"]
    if SUCCESSOR.get(current) != target:
        fail(ERR_WORK_ORDER_STATE_INVALID,
             "target_phase must name the immediate successor of the work "
             "order's current status.")
    attraction = store.db.attractions.get(order["attraction_id"])
    component = store.db.components.get(order["component_id"])
    if target == "TEARDOWN":
        inspection = derive.inspection_for_date(attraction, store.today_str())
        if inspection is not None and inspection["status"] == "PENDING_SIGN_OFF":
            fail(ERR_INSPECTION_STATE_INVALID,
                 "Teardown may not start while the attraction's inspection for "
                 "the current service date awaits sign-off.")
    order["status"] = target
    if target == "RECOMMISSIONED":
        stamp = store.now()
        order["recommissioned_at"] = store.iso(stamp)
        if component is not None:
            component["last_ndt_at"] = store.iso(stamp)
            component["last_ndt_cycles"] = attraction["cumulative_cycles"]
            component["condition_flag"] = "OK"
    return saved(derive.ser_work_order, order)
