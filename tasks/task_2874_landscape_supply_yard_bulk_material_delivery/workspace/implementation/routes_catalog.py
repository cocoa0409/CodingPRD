"""Materials, price schedules, inventory lots and the yard logical clock."""
from flask import Blueprint

import calc
import serial
from core import (
    arg, arg_bool, auth, body, db, fail, iso, new_record, opt_bool, opt_num,
    present, render_list, req_bool, req_enum, req_id, req_int, req_instant,
    req_num, req_str, require, respond, touch, _bad,
)

bp = Blueprint("catalog", __name__)

FORMS = ("BULK", "BAGGED")
SEASONAL_CATEGORIES = ("MULCH", "SALT", "AGGREGATE", "SOIL")
MATERIAL_STATUSES = ("ACTIVE", "SUSPENDED", "DISCONTINUED")
LOT_STATUSES = ("AVAILABLE", "QUARANTINED", "DEPLETED")
LOT_BASES = ("INTAKE", "SETTLEMENT")
PRICE_STATUSES = ("SCHEDULED", "EFFECTIVE", "SUPERSEDED")


# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------
@bp.post("/materials")
def create_material():
    auth("YardAdmin")
    data = body()
    sku = req_str(data, "sku", min_len=1, max_len=32)
    name = req_str(data, "name")
    if not present(data, "offered_forms"):
        _bad("offered_forms", "is required")
    forms = data["offered_forms"]
    if not isinstance(forms, list) or not forms:
        _bad("offered_forms", "must be a non-empty list")
    for entry in forms:
        if entry not in FORMS:
            _bad("offered_forms", "must contain only BULK or BAGGED")
    seasonal_category = req_enum(data, "seasonal_category", SEASONAL_CATEGORIES)
    density = req_num(data, "density_lb_per_cubic_yard", minimum=0, exclusive_min=True)
    shrinkage = req_num(data, "shrinkage_factor", minimum=0, maximum=0.5)
    moisture = opt_num(data, "moisture_pct", default=15.0, minimum=0, maximum=60)
    unit_bag = opt_num(data, "unit_bag_cubic_yards", default=0.037, minimum=0,
                       exclusive_min=True)
    prebuy_eligible = opt_bool(data, "prebuy_eligible", default=False)

    for existing in db.materials.values():
        if existing["sku"] == sku:
            fail("ERR_DUPLICATE_SKU", "SKU '%s' already exists." % sku)

    record = new_record(
        sku=sku,
        name=name,
        offered_forms=list(forms),
        seasonal_category=seasonal_category,
        density_lb_per_cubic_yard=density,
        shrinkage_factor=shrinkage,
        moisture_pct=moisture,
        unit_bag_cubic_yards=unit_bag,
        prebuy_eligible=prebuy_eligible,
        status="ACTIVE",
    )
    db.insert("materials", record)
    return respond(serial.material(record), 201)


@bp.get("/materials")
def list_materials():
    auth(*("YardAdmin", "CreditManager", "DispatchPlanner", "YardLoader",
           "ClaimsAdjuster", "Contractor"))
    status = arg("status")
    category = arg("seasonal_category")
    prebuy = arg_bool("prebuy_eligible")
    rows = []
    for record in db.materials.values():
        if status is not None and record["status"] != status:
            continue
        if category is not None and record["seasonal_category"] != category:
            continue
        if prebuy is not None and record["prebuy_eligible"] != prebuy:
            continue
        rows.append(record)
    return render_list(rows, serial.material)


@bp.get("/materials/<material_id>")
def read_material(material_id):
    auth(*("YardAdmin", "CreditManager", "DispatchPlanner", "YardLoader",
           "ClaimsAdjuster", "Contractor"))
    record = require(db.get("materials", material_id), "materials")
    return respond(serial.material(record))


@bp.patch("/materials/<material_id>")
def patch_material(material_id):
    auth("YardAdmin")
    data = body()
    status = None
    moisture = None
    if present(data, "status"):
        status = req_enum(data, "status", MATERIAL_STATUSES)
    if present(data, "moisture_pct"):
        moisture = req_num(data, "moisture_pct", minimum=0, maximum=60)
    record = require(db.get("materials", material_id), "materials")
    if status is not None:
        record["status"] = status
    if moisture is not None:
        record["moisture_pct"] = moisture
    touch(record)
    return respond(serial.material(record))


# --------------------------------------------------------------------------
# Price schedules
# --------------------------------------------------------------------------
def _effective_row(material_id):
    for row in db.price_schedules.values():
        if row["material_id"] == material_id and row["status"] == "EFFECTIVE":
            return row
    return None


@bp.post("/price-schedules")
def create_price_schedule():
    auth("YardAdmin")
    data = body()
    material_id = req_id(data, "material_id")
    effective_from = req_instant(data, "effective_from")
    bulk_price = req_int(data, "bulk_price_per_cubic_yard_cents", minimum=0,
                         exclusive_min=True)
    bagged_price = req_int(data, "bagged_price_per_bag_cents", minimum=0,
                           exclusive_min=True)
    surcharge = opt_num(data, "seasonal_surcharge_pct", default=0.0, minimum=0,
                        maximum=50)
    expected_version = req_int(data, "expected_material_version")

    material = require(db.get("materials", material_id), "materials")
    if expected_version != material["version"]:
        fail("ERR_STALE_MATERIAL_VERSION",
             "Material version is %d." % material["version"])

    current = _effective_row(material_id)
    if current is not None and effective_from <= current["effective_from"]:
        fail("ERR_PRICE_SCHEDULE_BACKDATED",
             "effective_from must be strictly later than the current effective row.")

    becomes_effective = effective_from <= db.clock
    record = new_record(
        material_id=material_id,
        effective_from=effective_from,
        bulk_price_per_cubic_yard_cents=bulk_price,
        bagged_price_per_bag_cents=bagged_price,
        seasonal_surcharge_pct=surcharge,
        status="EFFECTIVE" if becomes_effective else "SCHEDULED",
    )
    db.insert("price_schedules", record)
    if becomes_effective and current is not None:
        current["status"] = "SUPERSEDED"
        touch(current)
    touch(material)
    return respond(serial.price_schedule(record), 201)


@bp.get("/price-schedules")
def list_price_schedules():
    auth("YardAdmin", "CreditManager", "Contractor")
    material_id = arg("material_id")
    status = arg("status")
    rows = []
    for record in db.price_schedules.values():
        if material_id is not None and record["material_id"] != material_id:
            continue
        if status is not None and record["status"] != status:
            continue
        rows.append(record)
    return render_list(rows, serial.price_schedule)


@bp.get("/price-schedules/<price_schedule_id>")
def read_price_schedule(price_schedule_id):
    auth("YardAdmin", "CreditManager", "Contractor")
    record = require(db.get("price_schedules", price_schedule_id), "price_schedules")
    return respond(serial.price_schedule(record))


# --------------------------------------------------------------------------
# Inventory lots
# --------------------------------------------------------------------------
@bp.post("/inventory-lots")
def create_inventory_lot():
    auth("YardAdmin")
    data = body()
    material_id = req_id(data, "material_id")
    gross = req_num(data, "gross_cubic_yards", minimum=0, exclusive_min=True)
    moisture = req_num(data, "moisture_pct_at_intake", minimum=0, maximum=60)
    material = require(db.get("materials", material_id), "materials")

    record = new_record(
        material_id=material_id,
        gross_cubic_yards=gross,
        moisture_pct_at_intake=moisture,
        current_moisture_pct=moisture,
        basis="INTAKE",
        withdrawn_gross_cubic_yards=0.0,
        net_sellable_cubic_yards=0.0,
        reserved_cubic_yards=0.0,
        status="AVAILABLE",
    )
    record["net_sellable_cubic_yards"] = calc.lot_net_sellable(record, material)
    db.insert("inventory_lots", record)
    return respond(serial.inventory_lot(record), 201)


@bp.get("/inventory-lots")
def list_inventory_lots():
    auth("YardAdmin", "DispatchPlanner", "YardLoader", "CreditManager")
    material_id = arg("material_id")
    status = arg("status")
    basis = arg("basis")
    rows = []
    for record in db.inventory_lots.values():
        if material_id is not None and record["material_id"] != material_id:
            continue
        if status is not None and record["status"] != status:
            continue
        if basis is not None and record["basis"] != basis:
            continue
        rows.append(record)
    return render_list(rows, serial.inventory_lot)


@bp.get("/inventory-lots/<inventory_lot_id>")
def read_inventory_lot(inventory_lot_id):
    auth("YardAdmin", "DispatchPlanner", "YardLoader", "CreditManager")
    record = require(db.get("inventory_lots", inventory_lot_id), "inventory_lots")
    return respond(serial.inventory_lot(record))


@bp.post("/inventory-lots/<inventory_lot_id>/moisture-readings")
def file_moisture_reading(inventory_lot_id):
    auth("YardAdmin")
    data = body()
    moisture = req_num(data, "current_moisture_pct", minimum=0, maximum=60)
    quarantine = req_bool(data, "set_quarantine")
    lot = require(db.get("inventory_lots", inventory_lot_id), "inventory_lots")
    material = db.get("materials", lot["material_id"])

    lot["current_moisture_pct"] = moisture
    lot["basis"] = "SETTLEMENT"
    lot["net_sellable_cubic_yards"] = calc.lot_net_sellable(lot, material)
    lot["status"] = "QUARANTINED" if quarantine else "AVAILABLE"
    touch(lot)
    return respond(serial.inventory_lot(lot))


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth("YardAdmin")
    data = body()
    target = req_instant(data, "to_iso8601")
    if target <= db.clock:
        fail("ERR_CLOCK_MUST_ADVANCE", "The clock may only move forward.")
    db.clock = target

    promoted = []
    by_material = {}
    for row in db.rows("price_schedules"):
        if row["status"] == "SCHEDULED" and row["effective_from"] <= target:
            by_material.setdefault(row["material_id"], []).append(row)
    for material_id in sorted(by_material.keys()):
        due = sorted(by_material[material_id],
                     key=lambda r: (r["effective_from"], r["_seq"]))
        for row in due:
            current = _effective_row(material_id)
            row["status"] = "EFFECTIVE"
            touch(row)
            promoted.append(row)
            if current is not None and current["id"] != row["id"]:
                current["status"] = "SUPERSEDED"
                touch(current)

    expired = []
    today = calc.clock_date()
    for contract in db.rows("prebuy_contracts"):
        if contract["status"] in ("DRAFT", "ACTIVE") and (
                contract["season_end_date"] < today):
            contract["status"] = "EXPIRED"
            touch(contract)
            expired.append(contract)

    promoted.sort(key=lambda r: r["_seq"])
    return respond({
        "current_utc": iso(target),
        "promoted_price_schedule_ids": [r["id"] for r in promoted],
        "expired_prebuy_contract_ids": [r["id"] for r in expired],
    })
