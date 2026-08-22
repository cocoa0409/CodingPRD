"""Advance warehouses and the between-show storage billing run (PRD §3.1, §3.4)."""
from flask import Blueprint

import db
import response
from middleware import ANY_ROLE, own_warehouse, require_roles
from services import calc
from validation import json_body, parse_dt, require_row

bp = Blueprint("warehouses", __name__)
store = db.store

METERED_STATUSES = ("AT_ADVANCE_WAREHOUSE", "RETURNED_TO_WAREHOUSE")


@bp.post("/warehouses")
def create_warehouse():
    require_roles("ShowOperations")
    body = json_body()
    name = body.string("name")
    city = body.string("city")
    capacity = body.integer("capacity_cwt")
    rate = body.integer("storage_rate_cents_per_cwt_per_month", required=False,
                        default=2200)
    free_days = body.integer("free_days", required=False, default=30)
    dock_capacity = body.integer("dock_capacity_cwt", required=False, default=300)
    status = body.enum("status", ("ACCEPTING", "CLOSED"), required=False,
                       default="ACCEPTING")

    warehouse = {
        "id": db.new_id(),
        "name": name,
        "city": city,
        "storage_rate_cents_per_cwt_per_month": rate,
        "free_days": free_days,
        "capacity_cwt": capacity,
        "dock_capacity_cwt": dock_capacity,
        "committed_cwt": 0,
        "status": status,
    }
    db.stamp_common(warehouse)
    store.warehouses[warehouse["id"]] = warehouse
    return response.created(warehouse)


@bp.get("/warehouses/<warehouse_id>")
def get_warehouse(warehouse_id):
    require_roles(ANY_ROLE)
    warehouse = require_row(store.warehouses, warehouse_id, "ERR_WAREHOUSE_NOT_FOUND",
                            "Warehouse")
    return response.ok(warehouse)


@bp.post("/warehouses/<warehouse_id>/storage-billing-runs")
def storage_billing_run(warehouse_id):
    require_roles("WarehouseAgent", "FinanceController")
    own_warehouse(warehouse_id)
    body = json_body()
    as_of_text = body.datetime_str("as_of")
    warehouse = require_row(store.warehouses, warehouse_id, "ERR_WAREHOUSE_NOT_FOUND",
                            "Warehouse")

    as_of = parse_dt(as_of_text)
    crates = [c for c in store.crates.values()
              if c.get("warehouse_id") == warehouse_id
              and c["status"] in METERED_STATUSES
              and c.get("stored_since") is not None]
    crates = db.sort_rows(crates)

    total = 0
    for crate in crates:
        charge = calc.storage_charge(
            crate["weight_lbs"],
            warehouse["storage_rate_cents_per_cwt_per_month"],
            parse_dt(crate["stored_since"]),
            as_of,
            warehouse["free_days"])
        crate["storage_charge_cents"] = charge
        db.touch(crate)
        total += charge

    return response.ok({
        "warehouse_id": warehouse_id,
        "as_of": as_of_text,
        "crate_count": len(crates),
        "total_storage_charge_cents": total,
    })
