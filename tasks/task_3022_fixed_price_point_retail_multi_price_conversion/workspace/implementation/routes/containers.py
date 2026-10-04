"""Container movement, allocation lines, release and short (PRD §3.6 - §3.7)."""

from db import db
from errors import (
    ApiError,
    ERR_ALLOCATION_LINE_NOT_ALLOCATED,
    ERR_CONTAINER_NOT_AT_PORT,
    ERR_CONTAINER_NOT_BOOKED,
    ERR_CONTAINER_NOT_IN_TRANSIT,
    ERR_CONTAINER_NOT_ON_CUSTOMS_HOLD,
    ERR_CONTAINER_NOT_RECEIVED,
    ERR_CUSTOMS_NOT_CLEARED,
    ERR_DUPLICATE_SKU,
    ERR_INVALID_REQUEST,
    ERR_RELEASE_EXCEEDS_ALLOCATION,
)
from common import (
    apply_eq,
    as_int_opt,
    body,
    get_ok,
    get_row,
    insert,
    new_row,
    paginate,
    query,
    require,
    route,
    touch,
)
from response import ok_object
from derivations import (
    recompute_container_status,
    refresh_after_config_change,
    refresh_store,
    run_waterfall,
    serialize_container,
    serialize_cost_row,
    serialize_line,
)


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------

@route("/merchandise/containers", ["POST"], ["ImportCoordinator"])
def create_container():
    data = body()
    require(data, ["vendor_id", "container_number", "port_code", "dc_code", "total_freight_cents"])
    get_row("vendor", data["vendor_id"])
    total_freight_cents = as_int_opt(data, "total_freight_cents")
    if total_freight_cents is None or total_freight_cents < 0:
        invalid("total_freight_cents must not be negative.")
    if any(c["container_number"] == data["container_number"] for c in db.containers.values()):
        raise ApiError(ERR_DUPLICATE_SKU, "container_number is already held by another container.")

    row = new_row("container", {
        "vendor_id": data["vendor_id"],
        "container_number": data["container_number"],
        "port_code": data["port_code"],
        "dc_code": data["dc_code"],
        "total_freight_cents": total_freight_cents,
        "customs_cleared": False,
        "status": "BOOKED",
    })
    insert("container", row)
    refresh_after_config_change()
    return ok_object(serialize_container(row), 201)


@route("/merchandise/containers", ["GET"],
       ["ImportCoordinator", "MerchandiseAnalyst", "DistributionCenterOperator"])
def list_containers():
    rows = db.creation_order(db.containers)
    rows = apply_eq(rows, "status", query("status"))
    rows = apply_eq(rows, "vendor_id", query("vendor_id"))
    return paginate([serialize_container(r) for r in rows])


@route("/merchandise/containers/<container_id>", ["GET"],
       ["ImportCoordinator", "MerchandiseAnalyst", "DistributionCenterOperator"])
def read_container(container_id):
    return get_ok("container", container_id)


@route("/merchandise/containers/<container_id>/depart", ["POST"], ["ImportCoordinator"])
def depart_container(container_id):
    container = get_row("container", container_id)
    if container["status"] != "BOOKED":
        raise ApiError(ERR_CONTAINER_NOT_BOOKED)
    container["status"] = "IN_TRANSIT"
    touch(container)
    return ok_object(serialize_container(container))


@route("/merchandise/containers/<container_id>/arrive", ["POST"], ["ImportCoordinator"])
def arrive_container(container_id):
    container = get_row("container", container_id)
    if container["status"] != "IN_TRANSIT":
        raise ApiError(ERR_CONTAINER_NOT_IN_TRANSIT)
    container["status"] = "AT_PORT"
    container["customs_cleared"] = True
    touch(container)
    return ok_object(serialize_container(container))


@route("/merchandise/containers/<container_id>/customs-hold", ["POST"], ["ImportCoordinator"])
def hold_container(container_id):
    container = get_row("container", container_id)
    if container["status"] != "AT_PORT":
        raise ApiError(ERR_CONTAINER_NOT_AT_PORT)
    container["status"] = "CUSTOMS_HOLD"
    container["customs_cleared"] = False
    touch(container)
    return ok_object(serialize_container(container))


@route("/merchandise/containers/<container_id>/customs-release", ["POST"], ["ImportCoordinator"])
def release_container(container_id):
    container = get_row("container", container_id)
    if container["status"] != "CUSTOMS_HOLD":
        raise ApiError(ERR_CONTAINER_NOT_ON_CUSTOMS_HOLD)
    container["status"] = "AT_PORT"
    container["customs_cleared"] = True
    touch(container)
    return ok_object(serialize_container(container))


@route("/merchandise/containers/<container_id>/receive", ["POST"], ["ImportCoordinator"])
def receive_container(container_id):
    container = get_row("container", container_id)
    if container["status"] != "AT_PORT":
        raise ApiError(ERR_CONTAINER_NOT_AT_PORT)
    if not container["customs_cleared"]:
        raise ApiError(ERR_CUSTOMS_NOT_CLEARED)
    container["status"] = "RECEIVED"
    touch(container)
    return ok_object(serialize_container(container))


@route("/merchandise/containers/<container_id>/landed-cost-history", ["GET"],
       ["MerchandiseBuyer", "MerchandiseAnalyst", "LegalCostEngineer"])
def container_landed_costs(container_id):
    get_row("container", container_id)
    rows = [r for r in db.landed_costs.values() if r["container_id"] == container_id]
    rows.sort(key=lambda r: r["effective_sequence"], reverse=True)
    rows = apply_eq(rows, "item_id", query("item_id"))
    return paginate([serialize_cost_row(r) for r in rows])


@route("/merchandise/containers/<container_id>/allocation-lines", ["GET"],
       ["DistributionCenterOperator", "ImportCoordinator", "StoreOperationsManager", "MerchandiseAnalyst"])
def container_allocation_lines(container_id):
    get_row("container", container_id)
    rows = [r for r in db.creation_order(db.allocation_lines) if r["container_id"] == container_id]
    rows = apply_eq(rows, "status", query("status"))
    return paginate([serialize_line(r) for r in rows])


# ---------------------------------------------------------------------------
# AllocationLine
# ---------------------------------------------------------------------------

@route("/merchandise/allocation-lines", ["POST"], ["DistributionCenterOperator"])
def create_allocation_line():
    data = body()
    require(data, ["container_id", "store_id", "item_id", "sequence", "requested_units"])
    # body FK resolution in the order the input list declares them
    container = get_row("container", data["container_id"])
    get_row("store", data["store_id"])
    get_row("item", data["item_id"])

    sequence = as_int_opt(data, "sequence")
    requested_units = as_int_opt(data, "requested_units")
    if sequence is None or sequence < 1:
        invalid("sequence must be at least one.")
    if requested_units is None or requested_units < 0:
        invalid("requested_units must not be negative.")
    for line in db.allocation_lines.values():
        if line["container_id"] == container["id"] and line["sequence"] == sequence:
            invalid("sequence must be unique within its container.")

    row = new_row("allocation_line", {
        "container_id": container["id"],
        "store_id": data["store_id"],
        "item_id": data["item_id"],
        "sequence": sequence,
        "requested_units": requested_units,
        "allocated_units": 0,
        "overflow_units": requested_units,
        "released_units": 0,
        "remaining_units": 0,
        "status": "ALLOCATED",
    })
    insert("allocation_line", row)
    run_waterfall()
    # A fresh ALLOCATED line against an already-ALLOCATED container reopens it
    # for release (PRD §3.6). The line's own container status is settled here,
    # after the sweep, so nothing downstream undoes the revert edge.
    if row["status"] == "ALLOCATED" and container["status"] == "ALLOCATED":
        container["status"] = "RECEIVED"
        touch(container)
    refresh_after_config_change()
    return ok_object(serialize_line(row), 201)


@route("/merchandise/allocation-lines", ["GET"],
       ["DistributionCenterOperator", "ImportCoordinator", "StoreOperationsManager", "MerchandiseAnalyst"])
def list_allocation_lines():
    rows = db.creation_order(db.allocation_lines)
    rows = apply_eq(rows, "container_id", query("container_id"))
    rows = apply_eq(rows, "store_id", query("store_id"))
    rows = apply_eq(rows, "item_id", query("item_id"))
    rows = apply_eq(rows, "status", query("status"))
    return paginate([serialize_line(r) for r in rows])


@route("/merchandise/allocation-lines/<line_id>", ["GET"],
       ["DistributionCenterOperator", "ImportCoordinator", "StoreOperationsManager", "MerchandiseAnalyst"])
def read_allocation_line(line_id):
    return get_ok("allocation_line", line_id)


@route("/merchandise/allocation-lines/<line_id>/release", ["POST"], ["DistributionCenterOperator"])
def release_allocation_line(line_id):
    line = get_row("allocation_line", line_id)
    data = body()
    require(data, ["release_units"])
    release_units = as_int_opt(data, "release_units")

    if line["status"] != "ALLOCATED":
        raise ApiError(ERR_ALLOCATION_LINE_NOT_ALLOCATED)
    if release_units is None or release_units < 1:
        invalid("release_units must be at least one.")
    if release_units > line["remaining_units"]:
        raise ApiError(ERR_RELEASE_EXCEEDS_ALLOCATION)
    container = get_row("container", line["container_id"])
    if container["status"] != "RECEIVED":
        raise ApiError(ERR_CONTAINER_NOT_RECEIVED)

    line["released_units"] = line["released_units"] + release_units
    line["remaining_units"] = line["allocated_units"] - line["released_units"]
    item = get_row("item", line["item_id"])
    item["on_hand_units"] = item["on_hand_units"] + release_units
    touch(line)
    if line["remaining_units"] == 0:
        line["status"] = "RELEASED"
    recompute_container_status(line["container_id"])
    refresh_after_config_change()
    return ok_object(serialize_line(line))


@route("/merchandise/allocation-lines/<line_id>/short", ["POST"], ["DistributionCenterOperator"])
def short_allocation_line(line_id):
    line = get_row("allocation_line", line_id)
    if line["status"] != "ALLOCATED":
        raise ApiError(ERR_ALLOCATION_LINE_NOT_ALLOCATED)
    line["status"] = "SHORTED"
    line["remaining_units"] = 0
    touch(line)
    store = db.stores.get(line["store_id"])
    if store is not None:
        refresh_store(store)
    recompute_container_status(line["container_id"])
    refresh_after_config_change()
    return ok_object(serialize_line(line))


def invalid(message):
    raise ApiError(ERR_INVALID_REQUEST, message)