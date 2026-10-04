"""Item lifecycle: denomination, price assignment, landed cost, break-even,
activation and the deletion cascade (PRD §3.1 - §3.4, §3.9)."""

from db import db
from errors import (
    ApiError,
    ERR_CONTAINER_NOT_RECEIVED,
    ERR_CONTAINER_VENDOR_MISMATCH,
    ERR_DUPLICATE_SKU,
    ERR_INVALID_REQUEST,
    ERR_ITEM_NOT_COST_CLEARED,
    ERR_ITEM_NOT_COST_PENDING,
    ERR_ITEM_NOT_DENOMINATED,
    ERR_ITEM_NOT_IN_DELETE_REVIEW,
    ERR_ITEM_NOT_PRICE_ASSIGNED,
    ERR_PRICE_POINT_MISMATCH,
    ERR_PRICE_POINT_NOT_ACTIVE,
)
from common import (
    apply_eq,
    as_enum,
    as_number,
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
    apply_item_state_cascade,
    dec,
    derive_item,
    item_has_active_pack,
    recompute_container_status,
    refresh_after_config_change,
    refresh_store,
    serialize_cost_row,
    serialize_item,
)

METHODS = ("FREIGHT_PASS_THROUGH", "VENDOR_PRICE_CHANGE")
DECISIONS = ("RETAIN", "DELETE")


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------

@route("/merchandise/items", ["POST"], ["MerchandiseBuyer"])
def create_item():
    data = body()
    require(data, [
        "sku", "description", "unit_retail_cents", "commodity_class",
        "sqft_per_unit", "shelf_package_capacity", "units_per_case",
        "base_landed_cost_cents", "fixed_store_handling_cents",
        "variable_store_cost_cents", "sourcing_vendor_id",
    ])
    # season_code is the one optional denomination field: the PRD calls it
    # optional and specifies '' for a year-round staple (PRD §3.1).
    data = dict(data)
    data.setdefault("season_code", "")
    # body FK resolution before any business rule
    get_row("vendor", data["sourcing_vendor_id"])

    unit_retail_cents = as_int_opt(data, "unit_retail_cents")
    sqft_per_unit = as_number(data, "sqft_per_unit")
    shelf_package_capacity = as_number(data, "shelf_package_capacity")
    units_per_case = as_int_opt(data, "units_per_case")
    base_landed_cost_cents = as_int_opt(data, "base_landed_cost_cents")
    fixed_store_handling_cents = as_int_opt(data, "fixed_store_handling_cents")
    variable_store_cost_cents = as_int_opt(data, "variable_store_cost_cents")

    if unit_retail_cents is None or unit_retail_cents <= 0:
        invalid("unit_retail_cents must be greater than zero.")
    if sqft_per_unit is None or sqft_per_unit <= 0:
        invalid("sqft_per_unit must be greater than zero.")
    if shelf_package_capacity is None or shelf_package_capacity <= 0:
        invalid("shelf_package_capacity must be greater than zero.")
    if units_per_case is None or units_per_case < 1:
        invalid("units_per_case must be at least one.")
    for name, value in (
        ("base_landed_cost_cents", base_landed_cost_cents),
        ("fixed_store_handling_cents", fixed_store_handling_cents),
        ("variable_store_cost_cents", variable_store_cost_cents),
    ):
        if value is None or value < 0:
            invalid("%s must not be negative." % name)

    if any(i["sku"] == data["sku"] for i in db.items.values()):
        raise ApiError(ERR_DUPLICATE_SKU, "sku is already held by another item.")

    row = new_row("item", {
        "sku": data["sku"],
        "description": data["description"],
        "unit_retail_cents": unit_retail_cents,
        "price_point_id": None,
        "commodity_class": data["commodity_class"],
        "season_code": data["season_code"],
        "sqft_per_unit": sqft_per_unit,
        "shelf_package_capacity": shelf_package_capacity,
        "units_per_case": units_per_case,
        "base_landed_cost_cents": base_landed_cost_cents,
        "fixed_store_handling_cents": fixed_store_handling_cents,
        "variable_store_cost_cents": variable_store_cost_cents,
        "sourcing_vendor_id": data["sourcing_vendor_id"],
        "on_hand_units": 0,
        "broken_case_allowance": False,
        "is_shelf_overflow": False,
        "landed_cost_cents": 0,
        "break_even_units": 0,
        "net_contribution_cents_per_unit": unit_retail_cents - variable_store_cost_cents,
        "break_even_regime": "PRICE_PENDING",
        "status": "DENOMINATED",
    })
    insert("item", row)
    # Creation is not a modification: settle the derived fields while the row
    # still reports its initial version, and do not judge the unbound item.
    derive_item(row, mint=False, partial_create=True)
    refresh_after_config_change()
    return ok_object(serialize_item(row), 201)


@route("/merchandise/items", ["GET"],
       ["MerchandiseBuyer", "MerchandiseAnalyst", "StoreOperationsManager", "LegalCostEngineer"])
def list_items():
    rows = db.creation_order(db.items)
    rows = apply_eq(rows, "status", query("status"))
    rows = apply_eq(rows, "price_point_id", query("price_point_id"))
    rows = apply_eq(rows, "sourcing_vendor_id", query("sourcing_vendor_id"))
    rows = apply_eq(rows, "commodity_class", query("commodity_class"))
    rows = apply_eq(rows, "season_code", query("season_code"))
    return paginate([serialize_item(r) for r in rows])


@route("/merchandise/items/<item_id>", ["GET"],
       ["MerchandiseBuyer", "MerchandiseAnalyst", "StoreOperationsManager", "LegalCostEngineer"])
def read_item(item_id):
    return get_ok("item", item_id)


@route("/merchandise/items/<item_id>/price-assignments", ["POST"], ["MerchandiseBuyer"])
def assign_price_point(item_id):
    item = get_row("item", item_id)
    data = body()
    require(data, ["price_point_id"])
    price_point = get_row("price_point", data["price_point_id"])

    if item["status"] != "DENOMINATED":
        raise ApiError(ERR_ITEM_NOT_DENOMINATED)
    if item["unit_retail_cents"] != price_point["shelf_price_cents"]:
        raise ApiError(ERR_PRICE_POINT_MISMATCH)
    if price_point["status"] != "ACTIVE":
        raise ApiError(ERR_PRICE_POINT_NOT_ACTIVE)

    item["price_point_id"] = price_point["id"]
    item["status"] = "PRICE_ASSIGNED"
    touch(item)
    derive_item(item)
    refresh_after_config_change()
    return ok_object(serialize_item(item))


@route("/merchandise/items/<item_id>/price-assignment-release", ["POST"], ["MerchandiseBuyer"])
def release_price_assignment(item_id):
    item = get_row("item", item_id)
    if item["status"] != "PRICE_ASSIGNED":
        raise ApiError(ERR_ITEM_NOT_PRICE_ASSIGNED)
    item["price_point_id"] = None
    item["status"] = "DENOMINATED"
    touch(item)
    derive_item(item)
    refresh_after_config_change()
    return ok_object(serialize_item(item))


@route("/merchandise/items/<item_id>/landed-costs", ["POST"], ["MerchandiseBuyer"])
def apply_landed_cost(item_id):
    item = get_row("item", item_id)
    data = body()
    require(data, ["method"])
    method = data["method"]
    container_id = data.get("container_id")

    # Body FK resolution (priority 4) — a FREIGHT_PASS_THROUGH draws solely on
    # a container; a VENDOR_PRICE_CHANGE carries none (PRD §3.2).
    container = None
    if method == "FREIGHT_PASS_THROUGH" and container_id:
        container = get_row("container", container_id)

    # Acting-resource state (priority 5). PRD §3.2 makes the revision loop
    # cyclical across BOTH cost-carrying states: "each additional landed-cost
    # write on an already-`COST_PENDING` item re-runs the identical test and can
    # push it to `DELETE_REVIEW` on the same terms", and a later round "walks
    # the item back out of the deletion review" when the vendor revises down.
    # So a DELETE_REVIEW item also accepts a landed-cost application; the
    # re-derived contribution decides where it lands.
    if item["status"] not in ("PRICE_ASSIGNED", "COST_PENDING", "DELETE_REVIEW"):
        raise ApiError(ERR_ITEM_NOT_PRICE_ASSIGNED)

    # Request shape (priority 7).
    if method not in METHODS:
        invalid("'method' must be one of %s." % "/".join(METHODS))
    if method == "FREIGHT_PASS_THROUGH":
        if not container_id:
            invalid("A FREIGHT_PASS_THROUGH row must reference a container_id.")
        container = get_row("container", container_id)

    # Container safety gates (priorities 15 and 16).
    if method == "FREIGHT_PASS_THROUGH":
        if container["status"] != "RECEIVED":
            raise ApiError(ERR_CONTAINER_NOT_RECEIVED)
        if container["vendor_id"] != item["sourcing_vendor_id"]:
            raise ApiError(ERR_CONTAINER_VENDOR_MISMATCH)

    if method == "FREIGHT_PASS_THROUGH":
        # The freight rate is a container-level number the server derives; the
        # item cannot supply it (PRD §3.2).
        applied_amount_cents = pass_through_amount(item, container)
    else:
        applied_amount_cents = as_int_opt(data, "applied_amount_cents")
        if applied_amount_cents is None or applied_amount_cents < 0:
            invalid("applied_amount_cents must not be negative.")
        applied_amount_cents = int(applied_amount_cents)

    row = new_row("landed_cost", {
        "item_id": item["id"],
        "container_id": None if container is None else container["id"],
        "method": method,
        "applied_amount_cents": applied_amount_cents,
        "effective_sequence": db.mint_sequence(),
    })
    insert("landed_cost", row)

    pre_status = item["status"]
    derive_item(item)
    raised = apply_item_state_cascade(item, item["net_contribution_cents_per_unit"], pre_status)
    refresh_after_config_change()
    if raised is not None:
        raise ApiError(raised)
    return ok_object(serialize_cost_row(row), 201)


@route("/merchandise/items/<item_id>/landed-costs", ["GET"],
       ["MerchandiseBuyer", "MerchandiseAnalyst", "LegalCostEngineer"])
def item_landed_costs(item_id):
    get_row("item", item_id)
    rows = [r for r in db.landed_costs.values() if r["item_id"] == item_id]
    rows.sort(key=lambda r: r["effective_sequence"], reverse=True)
    rows = apply_eq(rows, "method", query("method"))
    rows = apply_eq(rows, "container_id", query("container_id"))
    return paginate([serialize_cost_row(r) for r in rows])


@route("/merchandise/landed-cost-history", ["GET"],
       ["MerchandiseBuyer", "MerchandiseAnalyst", "LegalCostEngineer"])
def all_landed_costs():
    rows = db.creation_order(db.landed_costs)
    rows = apply_eq(rows, "item_id", query("item_id"))
    rows = apply_eq(rows, "container_id", query("container_id"))
    rows = apply_eq(rows, "method", query("method"))
    return paginate([serialize_cost_row(r) for r in rows])


@route("/merchandise/items/<item_id>/break-even", ["GET"],
       ["MerchandiseBuyer", "MerchandiseAnalyst", "LegalCostEngineer"])
def break_even(item_id):
    item = get_row("item", item_id)
    derive_item(item)
    return ok_object({
        "item_id": item["id"],
        "break_even_units": item["break_even_units"],
        "unit_retail_cents": item["unit_retail_cents"],
        "landed_cost_cents": item["landed_cost_cents"],
        "variable_store_cost_cents": item["variable_store_cost_cents"],
        "net_contribution_cents_per_unit": item["net_contribution_cents_per_unit"],
        "regime": item["break_even_regime"],
    })


@route("/merchandise/items/<item_id>/activations", ["POST"], ["MerchandiseBuyer"])
def activate_item(item_id):
    item = get_row("item", item_id)
    if item["status"] != "COST_PENDING":
        raise ApiError(ERR_ITEM_NOT_COST_PENDING)
    derive_item(item)
    if item["net_contribution_cents_per_unit"] < 0 and not item_has_active_pack(item):
        raise ApiError(ERR_ITEM_NOT_COST_CLEARED)
    item["status"] = "ACTIVE"
    touch(item)
    derive_item(item)
    refresh_after_config_change()
    return ok_object(serialize_item(item))


# ---------------------------------------------------------------------------
# ItemDeletion (the three-hop cascade, PRD §3.9)
# ---------------------------------------------------------------------------

@route("/merchandise/item-deletions/<item_id>/decision", ["POST"], ["MerchandiseBuyer"])
def item_deletion_decision(item_id):
    item = get_row("item", item_id)
    data = body()
    require(data, ["decision"])
    decision = as_enum(data, "decision", DECISIONS)

    if item["status"] != "DELETE_REVIEW":
        raise ApiError(ERR_ITEM_NOT_IN_DELETE_REVIEW)

    if decision == "RETAIN":
        item["status"] = "ACTIVE"
        touch(item)
        derive_item(item)
        refresh_after_config_change()
        return ok_object(serialize_item(item))

    # DELETE — hop 1: reverse the item's ALLOCATED / SHORTED lines.
    item["status"] = "DELETED"
    item["price_point_id"] = None
    affected = [line for line in db.allocation_lines.values()
                if line["item_id"] == item["id"] and line["status"] in ("ALLOCATED", "SHORTED")]
    stores = set()
    containers = set()
    for line in affected:
        line["status"] = "REVERSED"
        line["released_units"] = 0
        line["remaining_units"] = 0
        line["__reversed_at"] = db.mint_sequence()
        stores.add(line["store_id"])
        containers.add(line["container_id"])

    # The container-freight-absorption invariant (PRD §3.9): the pass-through
    # absorbed on the container is fully given back by the deletion, so the
    # terminated item's current cost row reverts to its base FOB landed cost.
    # A deleted item is already out of the drawing states, so the waterfall
    # leaves it alone; the reversal above is what zeroes the invariant sum.
    if item["landed_cost_cents"] != item["base_landed_cost_cents"]:
        append_cost_row(item["id"], None, "VENDOR_PRICE_CHANGE", int(item["base_landed_cost_cents"]))
    refresh_after_config_change()

    # hop 2 + hop 3
    for store_id in stores:
        store = db.stores.get(store_id)
        if store is not None:
            refresh_store(store)
    for container_id in containers:
        # PRD §3.9 hop 3 retracts containers: a container whose remaining ALLOCATED
        # line count has fallen to zero and which is currently ALLOCATED is moved
        # back to RECEIVED. The reversal above already made every line on it
        # terminal, so the container is retracted here rather than left behind.
        container = db.containers.get(container_id)
        if container is not None and container["status"] == "ALLOCATED":
            container["status"] = "RECEIVED"
            touch(container)
        else:
            recompute_container_status(container_id)

    touch(item)
    return ok_object(serialize_item(item))


def pass_through_amount(item, container):
    """freight_pass_through_apportionment — floored ONCE for the whole container.

    container_total_units sums allocated_units over every line whose status is
    not REVERSED; the quotient is floored exactly once to whole cents and that
    single rate is charged to every item on the container. The individually
    floored per-item share is explicitly NOT the sanctioned behaviour
    (PRD §3.2), and the residual cents are dropped, never redistributed.
    """
    total_units = sum(
        int(line["allocated_units"]) for line in db.allocation_lines.values()
        if line["container_id"] == container["id"] and line["status"] != "REVERSED"
    )
    if total_units <= 0:
        freight_per_unit_cents = 0
    else:
        freight_per_unit_cents = int(
            (dec(container["total_freight_cents"]) / dec(total_units)).to_integral_value(rounding="ROUND_FLOOR")
        )
    return int(item["base_landed_cost_cents"]) + freight_per_unit_cents


def append_cost_row(item_id, container_id, method, amount):
    row = new_row("landed_cost", {
        "item_id": item_id,
        "container_id": container_id,
        "method": method,
        "applied_amount_cents": amount,
        "effective_sequence": db.mint_sequence(),
    })
    insert("landed_cost", row)
    return row


def invalid(message):
    raise ApiError(ERR_INVALID_REQUEST, message)