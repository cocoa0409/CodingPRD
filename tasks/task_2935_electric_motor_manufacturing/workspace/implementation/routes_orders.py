"""PRD 3.4 and 3.5 — the commercial order book, cancellation cascade, work
orders, build costing and shipping."""

from flask import Blueprint

from auth import authorize, own_distributor_id
from calc import order_lead_time, unit_standard_cost_cents, work_order_cost
from envelope import created, ok, paginate, single
from errors import fail
from helpers import bool_filter, eq_filter, load, rows
from ledgers import recompute_allowance, recompute_oven
from routes_reference import JURISDICTIONS
from store import base_row, by_created_at, db, now, touch
from validate import (as_date, opt_object, parse_body, req_date, req_enum,
                      req_int, req_str)

bp = Blueprint("orders", __name__)

ORDER_TYPES = ("STOCK_REPLENISH", "MADE_TO_ORDER", "ENGINEERED_SPECIAL")
ORDER_READERS = ("ProductionPlanner", "Distributor", "ComplianceOfficer", "PlantAdmin")
WORK_ORDER_READERS = ("ProductionPlanner", "BuildTechnician", "TestEngineer",
                      "QualityCertifier", "ComplianceOfficer", "PlantAdmin")


# ---------------------------------------------------------------------------
# Customer orders
# ---------------------------------------------------------------------------

@bp.post("/customer-orders")
def create_order():
    user_id, role = authorize("ProductionPlanner", "Distributor")
    body = parse_body()
    # PRD 2.11 — ownership precedes payload shape: a Distributor supplying a
    # foreign distributor_id is refused before the payload is examined.
    raw_distributor = body.get("distributor_id")
    own_distributor_id(user_id, role, raw_distributor if isinstance(raw_distributor, str) else None)

    distributor_id = req_str(body, "distributor_id")
    design_id = req_str(body, "design_id")
    order_type = req_enum(body, "order_type", ORDER_TYPES)
    quantity = req_int(body, "quantity", 1, 5000)
    requested_ship_date = req_date(body, "requested_ship_date")
    jurisdiction = req_enum(body, "jurisdiction", JURISDICTIONS)
    special = opt_object(body, "special_requirements", {})
    for key, value in special.items():
        if not isinstance(value, bool):
            fail("ERR_INVALID_REQUEST",
                 "Field 'special_requirements.%s' must be a boolean." % key)

    load("designs", design_id)
    distributor = load("distributors", distributor_id)
    own_distributor_id(user_id, role, distributor_id)

    row = base_row()
    row.update({
        "distributor_id": distributor_id,
        "design_id": design_id,
        "order_type": order_type,
        "quantity": quantity,
        "requested_ship_date": requested_ship_date,
        "jurisdiction": jurisdiction,
        "special_requirements": special,
        "status": "DRAFT",
        "confirmed_at": None,
        "cancellation_reason": None,
    })
    days, ship_date = order_lead_time(row, distributor, now())
    row["promised_lead_time_days"] = days
    row["promised_ship_date"] = ship_date
    db.orders[row["id"]] = row
    return created({k: v for k, v in row.items() if not k.startswith("_")})


@bp.get("/customer-orders/<row_id>")
def read_order(row_id):
    user_id, role = authorize(*ORDER_READERS)
    order = load("orders", row_id)
    own_distributor_id(user_id, role, order["distributor_id"])
    return single(order)


@bp.get("/customer-orders")
def list_orders():
    user_id, role = authorize(*ORDER_READERS)
    collection = rows("orders")
    if role == "Distributor":
        from flask import request
        requested = request.args.get("distributor_id")
        if requested is not None and requested != user_id:
            fail("ERR_NOT_OWNER", "A distributor may only list its own orders.")
        collection = [o for o in collection if o["distributor_id"] == user_id]
    collection = eq_filter(collection, "distributor_id")
    collection = eq_filter(collection, "design_id")
    collection = eq_filter(collection, "status")
    collection = eq_filter(collection, "order_type")
    return paginate(collection)


@bp.post("/customer-orders/<row_id>/confirm")
def confirm_order(row_id):
    authorize("ProductionPlanner")
    order = load("orders", row_id)
    parse_body()
    if order["status"] != "DRAFT":
        fail("ERR_INVALID_ORDER_STATE", "Only a DRAFT order may be confirmed.")

    design = db.designs.get(order["design_id"])
    if design is None or design["status"] != "RELEASED":
        fail("ERR_DESIGN_NOT_RELEASED",
             "The design named by this order must be RELEASED at confirmation.")

    distributor = db.distributors[order["distributor_id"]]
    if (order["order_type"] == "STOCK_REPLENISH"
            and not distributor["stocking_program_enrolled"]):
        fail("ERR_STOCKING_PROGRAM_NOT_ENROLLED",
             "A STOCK_REPLENISH order requires an enrolled stocking program.")

    days, ship_date = order_lead_time(order, distributor, now())
    if as_date(ship_date) > as_date(order["requested_ship_date"]):
        fail("ERR_SHIP_DATE_UNACHIEVABLE",
             "The promised ship date %s falls after the requested date %s."
             % (ship_date, order["requested_ship_date"]))

    if order["quantity"] > distributor["stock_allowance_remaining_units"]:
        fail("ERR_STOCK_ALLOWANCE_EXCEEDED",
             "The order quantity exceeds the distributor's remaining allowance.")

    order["promised_lead_time_days"] = days
    order["promised_ship_date"] = ship_date
    order["confirmed_at"] = now()
    order["status"] = "CONFIRMED"
    touch(order)
    recompute_allowance(distributor)
    return single(order)


@bp.post("/customer-orders/<row_id>/cancel")
def cancel_order(row_id):
    authorize("ProductionPlanner")
    order = load("orders", row_id)
    body = parse_body()
    reason = req_str(body, "cancellation_reason", 1)
    if order["status"] not in ("DRAFT", "CONFIRMED", "IN_PRODUCTION"):
        fail("ERR_INVALID_ORDER_STATE",
             "A FULFILLED or CANCELLED order can no longer be cancelled.")

    previous = order["status"]
    order["status"] = "CANCELLED"
    order["cancellation_reason"] = reason
    touch(order)

    if previous in ("CONFIRMED", "IN_PRODUCTION"):
        recompute_allowance(db.distributors[order["distributor_id"]])

    if previous == "IN_PRODUCTION":
        _cancellation_cascade(order)

    return single(order)


def _cancellation_cascade(order):
    """PRD 3.4 — three hops: work orders, then their subassemblies in the fixed
    collection order stator/rotor/assembly, then the ovens those stators held."""
    work_orders = [w for w in by_created_at(list(db.work_orders.values()))
                   if w["order_id"] == order["id"]
                   and w["build_status"] not in ("SHIPPED", "CANCELLED")]
    for work_order in work_orders:
        work_order["build_status"] = "CANCELLED"
        touch(work_order)

    ids = set(w["id"] for w in work_orders)
    scrapped_stators = []
    for build in by_created_at(list(db.stator_builds.values())):
        if build["work_order_id"] in ids and build["status"] not in ("REJECTED", "SCRAPPED"):
            build["status"] = "SCRAPPED"
            touch(build)
            scrapped_stators.append(build)
    for build in by_created_at(list(db.rotor_builds.values())):
        if build["work_order_id"] in ids and build["status"] not in ("REJECTED", "SCRAPPED"):
            build["status"] = "SCRAPPED"
            touch(build)
    for record in by_created_at(list(db.assembly_records.values())):
        if record["work_order_id"] in ids and record["status"] == "BUILT":
            record["status"] = "SCRAPPED"
            touch(record)

    oven_ids = set(b["oven_id"] for b in scrapped_stators if b.get("oven_id"))
    for oven in by_created_at(list(db.ovens.values())):
        if oven["id"] in oven_ids:
            recompute_oven(oven)


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------

@bp.post("/work-orders")
def create_work_order():
    authorize("ProductionPlanner")
    body = parse_body()
    order_id = req_str(body, "order_id")
    design_id = req_str(body, "design_id")
    unit_count = req_int(body, "unit_count", 1, 5000)
    expected_design_version = req_int(body, "expected_design_version")

    design = load("designs", design_id)
    order = load("orders", order_id)

    if order["status"] not in ("CONFIRMED", "IN_PRODUCTION"):
        fail("ERR_INVALID_ORDER_STATE",
             "A work order may only be opened against a CONFIRMED or IN_PRODUCTION order.")

    if design["id"] != order["design_id"] or design["status"] != "RELEASED":
        fail("ERR_DESIGN_NOT_RELEASED",
             "The work order must pin the customer order's own RELEASED design.")

    if expected_design_version != design["version"]:
        fail("ERR_STALE_DESIGN_VERSION",
             "expected_design_version %s does not match the design's current version %s."
             % (expected_design_version, design["version"]))

    row = base_row()
    row.update({
        "order_id": order_id,
        "design_id": design_id,
        "unit_count": unit_count,
        "build_status": "RELEASED",
        "certification_status": "PENDING",
        "design_pin_stale": False,
        "rework_reject_count": 0,
        "pinned_design_revision_index": design["revision_index"],
        "shipped_at": None,
    })
    row["per_unit_direct_cost_cents"] = work_order_cost(row, design)
    db.work_orders[row["id"]] = row

    touch(design)
    if order["status"] == "CONFIRMED":
        order["status"] = "IN_PRODUCTION"
        touch(order)

    return created({k: v for k, v in row.items() if not k.startswith("_")})


@bp.get("/work-orders/<row_id>")
def read_work_order(row_id):
    authorize(*WORK_ORDER_READERS)
    return single(load("work_orders", row_id))


@bp.get("/work-orders")
def list_work_orders():
    authorize(*WORK_ORDER_READERS)
    collection = rows("work_orders")
    collection = eq_filter(collection, "order_id")
    collection = eq_filter(collection, "design_id")
    collection = eq_filter(collection, "build_status")
    collection = eq_filter(collection, "certification_status")
    collection = bool_filter(collection, "design_pin_stale")
    return paginate(collection)


@bp.get("/work-orders/<row_id>/cost-summary")
def cost_summary(row_id):
    authorize("ProductionPlanner", "ComplianceOfficer", "QualityCertifier", "PlantAdmin")
    work_order = load("work_orders", row_id)
    return ok({
        "work_order_id": work_order["id"],
        "unit_count": work_order["unit_count"],
        "per_unit_direct_cost_cents": work_order["per_unit_direct_cost_cents"],
        "direct_cost_cents": work_order["direct_cost_cents"],
        "overhead_band": work_order["overhead_band"],
        "overhead_cents": work_order["overhead_cents"],
        "standard_cost_cents": work_order["standard_cost_cents"],
        "actual_cost_cents": work_order["actual_cost_cents"],
        "cost_variance_cents": work_order["cost_variance_cents"],
        "rework_reject_count": work_order["rework_reject_count"],
        "unit_standard_cost_cents": unit_standard_cost_cents(work_order),
    })


@bp.post("/work-orders/<row_id>/ship")
def ship_work_order(row_id):
    authorize("ProductionPlanner")
    work_order = load("work_orders", row_id)
    parse_body()
    if work_order["build_status"] != "TESTED":
        fail("ERR_INVALID_WORK_ORDER_STATE", "Only a TESTED work order may be shipped.")
    if work_order["certification_status"] != "CERTIFIED":
        fail("ERR_NAMEPLATE_NOT_CERTIFIED",
             "A motor may not leave the plant without a live nameplate certification.")

    work_order["shipped_at"] = now()
    work_order["build_status"] = "SHIPPED"
    touch(work_order)

    order = db.orders.get(work_order["order_id"])
    if order is not None and order["status"] == "IN_PRODUCTION":
        order["status"] = "FULFILLED"
        touch(order)
        recompute_allowance(db.distributors[order["distributor_id"]])

    return single(work_order)
