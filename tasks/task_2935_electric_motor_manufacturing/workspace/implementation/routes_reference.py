"""PRD 3.1 — plant reference data and the logical clock."""

from decimal import Decimal

from flask import Blueprint

import store
from auth import authorize
from envelope import created, ok, paginate, single
from errors import fail
from helpers import bool_filter, eq_filter, int_filter, load, rows
from store import base_row, db
from validate import (opt_enum, opt_int, opt_num, parse_body, req_date, req_enum,
                      req_instant, req_int, req_num, req_str)

bp = Blueprint("reference", __name__)

JURISDICTIONS = ("EU", "US", "CN")
EFFICIENCY_CLASSES = ("IE2", "IE3", "IE4", "IE5")
POLE_COUNTS = (2, 4, 6, 8)
EQUIPMENT_STATUSES = ("AVAILABLE", "MAINTENANCE")
TIERS = ("PLATINUM", "GOLD", "SILVER")


def req_poles(body, key="poles"):
    value = req_int(body, key)
    if value not in POLE_COUNTS:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of 2, 4, 6, 8." % key)
    return value


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize("PlantAdmin")
    body = parse_body()
    instant = req_instant(body, "current_utc")
    db.clock = instant
    return ok({})


# ---------------------------------------------------------------------------
# Regulatory standards — immutable reference data (PRD 2.4)
# ---------------------------------------------------------------------------

@bp.post("/regulatory-standards")
def create_standard():
    authorize("PlantAdmin")
    body = parse_body()
    standard_code = req_str(body, "standard_code", 1, 40)
    jurisdiction = req_enum(body, "jurisdiction", JURISDICTIONS)
    efficiency_class = req_enum(body, "efficiency_class", EFFICIENCY_CLASSES)
    poles = req_poles(body)
    kw_min = req_num(body, "rated_output_kw_min", places=1)
    if kw_min <= 0:
        fail("ERR_INVALID_REQUEST", "Field 'rated_output_kw_min' must be greater than zero.")
    kw_max = req_num(body, "rated_output_kw_max", places=1)
    if kw_max < kw_min:
        fail("ERR_INVALID_REQUEST",
             "Field 'rated_output_kw_max' must be at least 'rated_output_kw_min'.")
    minimum = req_num(body, "minimum_efficiency_pct", 50.00, 99.99, places=2)
    effective_from = req_date(body, "effective_from")
    tolerance = opt_num(body, "tolerance_pct", places=2, default=Decimal("0.00"))

    row = base_row(mutable=False)
    row.update({
        "standard_code": standard_code,
        "jurisdiction": jurisdiction,
        "efficiency_class": efficiency_class,
        "poles": poles,
        "rated_output_kw_min": kw_min,
        "rated_output_kw_max": kw_max,
        "minimum_efficiency_pct": minimum,
        "tolerance_pct": tolerance,
        "effective_from": effective_from,
    })
    db.standards[row["id"]] = row
    return created({k: v for k, v in row.items() if not k.startswith("_")})


STANDARD_READERS = ("QualityCertifier", "ComplianceOfficer", "DesignEngineer",
                    "DesignReviewer", "PlantAdmin")


@bp.get("/regulatory-standards/<row_id>")
def read_standard(row_id):
    authorize(*STANDARD_READERS)
    return single(load("standards", row_id))


@bp.get("/regulatory-standards")
def list_standards():
    authorize(*STANDARD_READERS)
    collection = rows("standards")
    collection = eq_filter(collection, "jurisdiction")
    collection = eq_filter(collection, "efficiency_class")
    collection = int_filter(collection, "poles")
    # PRD 2.3 — the documented exception: effective_from descending, ties broken
    # by created_at ascending.
    collection = sorted(collection, key=lambda r: (r["created_at"], r["_seq"]))
    collection = sorted(collection, key=lambda r: r["effective_from"], reverse=True)
    return paginate(collection)


# ---------------------------------------------------------------------------
# Distributors
# ---------------------------------------------------------------------------

@bp.post("/distributors")
def create_distributor():
    authorize("PlantAdmin")
    body = parse_body()
    name = req_str(body, "name", 1, 80)
    tier = req_enum(body, "tier", TIERS)
    jurisdiction = req_enum(body, "jurisdiction", JURISDICTIONS)
    enrolled = body.get("stocking_program_enrolled")
    if enrolled is None:
        enrolled = False
    elif not isinstance(enrolled, bool):
        fail("ERR_INVALID_REQUEST", "Field 'stocking_program_enrolled' must be a boolean.")
    committed = opt_int(body, "committed_annual_units", 0, 100000, default=0)
    buffer_units = opt_int(body, "stock_buffer_units", 0, default=0)

    row = base_row()
    row.update({
        "name": name,
        "tier": tier,
        "jurisdiction": jurisdiction,
        "stocking_program_enrolled": enrolled,
        "committed_annual_units": committed,
        "stock_buffer_units": buffer_units,
        "units_outstanding": 0,
        "stock_allowance_remaining_units": committed,
        "warranty_credit_balance_cents": 0,
        "open_presumed_defect_count": 0,
    })
    db.distributors[row["id"]] = row
    return created({k: v for k, v in row.items() if not k.startswith("_")})


DISTRIBUTOR_READERS = ("ProductionPlanner", "ComplianceOfficer", "PlantAdmin")


@bp.get("/distributors/<row_id>")
def read_distributor(row_id):
    authorize(*DISTRIBUTOR_READERS)
    return single(load("distributors", row_id))


@bp.get("/distributors")
def list_distributors():
    authorize(*DISTRIBUTOR_READERS)
    collection = rows("distributors")
    collection = eq_filter(collection, "tier")
    collection = eq_filter(collection, "jurisdiction")
    collection = bool_filter(collection, "stocking_program_enrolled")
    return paginate(collection)


# ---------------------------------------------------------------------------
# Curing ovens
# ---------------------------------------------------------------------------

@bp.post("/curing-ovens")
def create_oven():
    authorize("PlantAdmin")
    body = parse_body()
    oven_code = req_str(body, "oven_code", 1, 24)
    max_temp = req_num(body, "max_temp_c", 60.0, 300.0, places=1)
    cooldown = req_int(body, "cooldown_buffer_minutes", 0, 240)
    status = opt_enum(body, "status", EQUIPMENT_STATUSES, default="AVAILABLE")

    row = base_row()
    row.update({
        "oven_code": oven_code,
        "max_temp_c": max_temp,
        "cooldown_buffer_minutes": cooldown,
        "status": status,
        "booked_minutes": 0,
    })
    db.ovens[row["id"]] = row
    return created({k: v for k, v in row.items() if not k.startswith("_")})


OVEN_READERS = ("BuildTechnician", "ProductionPlanner", "PlantAdmin")


@bp.get("/curing-ovens/<row_id>")
def read_oven(row_id):
    authorize(*OVEN_READERS)
    return single(load("ovens", row_id))


@bp.get("/curing-ovens")
def list_ovens():
    authorize(*OVEN_READERS)
    collection = eq_filter(rows("ovens"), "status")
    return paginate(collection)


# ---------------------------------------------------------------------------
# Dynamometer test cells
# ---------------------------------------------------------------------------

@bp.post("/test-cells")
def create_cell():
    authorize("PlantAdmin")
    body = parse_body()
    cell_code = req_str(body, "cell_code", 1, 24)
    max_kw = req_num(body, "max_concurrent_kw", 1.0, 2000.0, places=1)
    status = opt_enum(body, "status", EQUIPMENT_STATUSES, default="AVAILABLE")

    row = base_row()
    row.update({
        "cell_code": cell_code,
        "max_concurrent_kw": max_kw,
        "status": status,
        "peak_reserved_kw": Decimal("0.0"),
    })
    db.test_cells[row["id"]] = row
    return created({k: v for k, v in row.items() if not k.startswith("_")})


CELL_READERS = ("TestEngineer", "ProductionPlanner", "PlantAdmin")


@bp.get("/test-cells/<row_id>")
def read_cell(row_id):
    authorize(*CELL_READERS)
    return single(load("test_cells", row_id))


@bp.get("/test-cells")
def list_cells():
    authorize(*CELL_READERS)
    collection = eq_filter(rows("test_cells"), "status")
    return paginate(collection)
