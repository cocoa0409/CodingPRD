"""Logical clock, PricePoint, Vendor and ExclusivePackProgram endpoints."""

from decimal import Decimal

from db import db, parse_dt, iso
from errors import (
    ApiError,
    ERR_DUPLICATE_SKU,
    ERR_INVALID_REQUEST,
    ERR_PACK_COST_TARGET_MISSED,
    ERR_PRICE_POINT_NOT_ACTIVE,
)
from common import (
    apply_eq,
    as_bool,
    as_enum,
    as_int_opt,
    as_number,
    body,
    get_ok,
    get_row,
    insert,
    new_row,
    paginate,
    query,
    require,
    route,
    serialize,
    touch,
)
from response import ok_object
from derivations import (
    TARGET_MARGIN_BUFFER_PCT,
    clock_sweep,
    dec,
    floor_at_cent,
    refresh_after_config_change,
    refresh_price_point,
    serialize_pack,
    serialize_price_point,
    serialize_vendor,
)

PACK_STATUSES = ("DRAFT", "PENDING_ACTIVATION", "ACTIVE", "TERMINATED")
# PRD §3.5 pins the chain DRAFT → PENDING_ACTIVATION → ACTIVE → TERMINATED and
# says the endpoint "Advance[s] an exclusive pack program's status"; a PATCH may
# therefore land the program on any later rung of that chain in one call (the
# intermediate rungs are walked), and only a backward or unknown move is
# refused as malformed. The ceiling gate is applied whenever the call lands the
# program on ACTIVE.
ALLOWED_ADVANCES = {
    "DRAFT": ("DRAFT", "PENDING_ACTIVATION", "ACTIVE"),
    "PENDING_ACTIVATION": ("PENDING_ACTIVATION", "ACTIVE"),
    "ACTIVE": ("ACTIVE", "TERMINATED"),
    "TERMINATED": ("TERMINATED",),
}


def pack_target_ceiling(program):
    """landed_cost_target_ceiling — pinned multiplication order, then floor."""
    price_point = db.price_points.get(program["price_point_id"])
    if price_point is None:
        return 0
    product = dec(price_point["shelf_price_cents"]) * dec(price_point["target_landed_cost_ratio"])
    buffered = product * (Decimal(1) - TARGET_MARGIN_BUFFER_PCT)
    return int(floor_at_cent(buffered))


def derive_pack(program, mint=True):
    ceiling = pack_target_ceiling(program)
    if program.get("target_landed_cost_cents") == ceiling:
        return False
    program["target_landed_cost_cents"] = ceiling
    if mint:
        touch(program)
    return True


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@route("/_clock/set_current_utc", ["POST"], ["PlatformAdmin"])
def set_current_utc():
    data = body()
    require(data, ["to_iso8601"])
    parsed = parse_dt(data.get("to_iso8601"))
    if parsed is None:
        raise_invalid("'to_iso8601' must be an ISO 8601 instant.")
    db.set_clock(parsed)
    item_count, window_count = clock_sweep()
    return ok_object(
        {
            "current_utc": iso(db.logical_clock),
            "recomputed_item_count": item_count,
            "recomputed_season_window_count": window_count,
        }
    )


# ---------------------------------------------------------------------------
# PricePoint
# ---------------------------------------------------------------------------

@route("/merchandise/price-points", ["POST"], ["MerchandiseBuyer"])
def create_price_point():
    data = body()
    require(data, ["label", "shelf_price_cents", "target_landed_cost_ratio"])
    shelf_price_cents = as_int_opt(data, "shelf_price_cents")
    ratio = as_number(data, "target_landed_cost_ratio")
    if shelf_price_cents is None or shelf_price_cents <= 0:
        raise_invalid("shelf_price_cents must be greater than zero.")
    if ratio is None or not (0 < ratio <= 1):
        raise_invalid("target_landed_cost_ratio must be greater than zero and at most one.")

    row = new_row("price_point", {
        "label": data["label"],
        "shelf_price_cents": shelf_price_cents,
        "target_landed_cost_ratio": ratio,
        "status": "DRAFT",
        "issued_store_count": 0,
    })
    insert("price_point", row)
    refresh_after_config_change()
    return ok_object(serialize_price_point(row), 201)


@route("/merchandise/price-points", ["GET"],
       ["MerchandiseBuyer", "StoreOperationsManager", "MerchandiseAnalyst"])
def list_price_points():
    status = query("status")
    rows = [r for r in db.creation_order(db.price_points) if not status or r["status"] == status]
    return paginate([serialize_price_point(r) for r in rows])


@route("/merchandise/price-points/<price_point_id>", ["GET"],
       ["MerchandiseBuyer", "StoreOperationsManager", "MerchandiseAnalyst"])
def read_price_point(price_point_id):
    return get_ok("price_point", price_point_id)


@route("/merchandise/price-points/<price_point_id>/activate", ["POST"], ["MerchandiseBuyer"])
def activate_price_point(price_point_id):
    row = get_row("price_point", price_point_id)
    if row["status"] not in ("DRAFT", "ACTIVE"):
        raise_invalid("A price point may only be activated from DRAFT.")
    row["status"] = "ACTIVE"
    touch(row)
    refresh_price_point(row)
    return ok_object(serialize_price_point(row))


@route("/merchandise/price-points/<price_point_id>/aisle-resets", ["GET"],
       ["MerchandiseBuyer", "ResetCalendarPlanner", "MerchandiseAnalyst"])
def price_point_aisle_resets(price_point_id):
    get_row("price_point", price_point_id)
    rows = [r for r in db.creation_order(db.aisle_resets) if r["price_point_id"] == price_point_id]
    rows = apply_eq(rows, "status", query("status"))
    rows = apply_eq(rows, "store_id", query("store_id"))
    return paginate([serialize("aisle_reset", r) for r in rows])


@route("/merchandise/price-points/<price_point_id>/conversion-projects", ["GET"],
       ["MerchandiseBuyer", "StoreOperationsManager", "MerchandiseAnalyst"])
def price_point_conversion_projects(price_point_id):
    get_row("price_point", price_point_id)
    rows = [
        r for r in db.creation_order(db.conversion_projects)
        if r.get("from_price_point_id") == price_point_id or r.get("to_price_point_id") == price_point_id
    ]
    rows = apply_eq(rows, "status", query("status"))
    return paginate([serialize("conversion_project", r) for r in rows])


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------

@route("/merchandise/vendors", ["POST"], ["MerchandiseBuyer"])
def create_vendor():
    data = body()
    require(data, ["vendor_name", "country_of_origin", "import_flag"])
    import_flag = as_bool(data, "import_flag")
    if import_flag is None:
        raise_invalid("'import_flag' must be a boolean.")
    vendor_name = data["vendor_name"]
    if any(v["vendor_name"] == vendor_name for v in db.vendors.values()):
        raise ApiError(ERR_DUPLICATE_SKU, "vendor_name is already held by another vendor.")

    row = new_row("vendor", {
        "vendor_name": vendor_name,
        "country_of_origin": data["country_of_origin"],
        "import_flag": import_flag,
        "exclusivity_program_count": 0,
    })
    insert("vendor", row)
    refresh_after_config_change()
    return ok_object(serialize_vendor(row), 201)


@route("/merchandise/vendors", ["GET"], ["MerchandiseBuyer", "MerchandiseAnalyst"])
def list_vendors():
    rows = db.creation_order(db.vendors)
    flag = query("import_flag")
    if flag is not None:
        wanted = str(flag).strip().lower() == "true"
        rows = [r for r in rows if bool(r["import_flag"]) is wanted]
    return paginate([serialize_vendor(r) for r in rows])


@route("/merchandise/vendors/<vendor_id>", ["GET"], ["MerchandiseBuyer", "MerchandiseAnalyst"])
def read_vendor(vendor_id):
    return get_ok("vendor", vendor_id)


@route("/merchandise/vendors/<vendor_id>/exclusive-pack-programs", ["GET"],
       ["MerchandiseBuyer", "MerchandiseAnalyst"])
def vendor_pack_programs(vendor_id):
    get_row("vendor", vendor_id)
    rows = [r for r in db.creation_order(db.pack_programs) if r["vendor_id"] == vendor_id]
    rows = apply_eq(rows, "status", query("status"))
    return paginate([serialize_pack(r) for r in rows])


# ---------------------------------------------------------------------------
# ExclusivePackProgram
# ---------------------------------------------------------------------------

@route("/merchandise/exclusive-pack-programs", ["POST"], ["MerchandiseBuyer"])
def create_pack_program():
    data = body()
    require(data, ["vendor_id", "price_point_id", "pack_qty", "case_pack_qty",
                   "formulation_code", "quoted_landed_cost_cents"])
    # body FK resolution, in declared order
    get_row("vendor", data["vendor_id"])
    get_row("price_point", data["price_point_id"])

    pack_qty = as_int_opt(data, "pack_qty")
    case_pack_qty = as_int_opt(data, "case_pack_qty")
    quoted = as_int_opt(data, "quoted_landed_cost_cents")
    if pack_qty is None or pack_qty < 1:
        raise_invalid("pack_qty must be at least one.")
    if case_pack_qty is None or case_pack_qty < 1:
        raise_invalid("case_pack_qty must be at least one.")
    if quoted is None or quoted < 0:
        raise_invalid("quoted_landed_cost_cents must not be negative.")

    row = new_row("pack_program", {
        "vendor_id": data["vendor_id"],
        "price_point_id": data["price_point_id"],
        "pack_qty": pack_qty,
        "case_pack_qty": case_pack_qty,
        "formulation_code": data["formulation_code"],
        "quoted_landed_cost_cents": quoted,
        "target_landed_cost_cents": 0,
        "status": "DRAFT",
    })
    insert("pack_program", row)
    # Creation is not a modification: settle the ceiling while the row still
    # reports its initial version.
    derive_pack(row, mint=False)
    refresh_after_config_change()
    return ok_object(serialize_pack(row), 201)


@route("/merchandise/exclusive-pack-programs", ["GET"],
       ["MerchandiseBuyer", "MerchandiseAnalyst"])
def list_pack_programs():
    rows = db.creation_order(db.pack_programs)
    rows = apply_eq(rows, "vendor_id", query("vendor_id"))
    rows = apply_eq(rows, "price_point_id", query("price_point_id"))
    rows = apply_eq(rows, "status", query("status"))
    return paginate([serialize_pack(r) for r in rows])


@route("/merchandise/exclusive-pack-programs/<program_id>", ["GET"],
       ["MerchandiseBuyer", "MerchandiseAnalyst"])
def read_pack_program(program_id):
    return get_ok("pack_program", program_id)


@route("/merchandise/exclusive-pack-programs/<program_id>", ["PATCH"], ["MerchandiseBuyer"])
def patch_pack_program(program_id):
    row = get_row("pack_program", program_id)
    data = body()
    require(data, ["status"])
    status = as_enum(data, "status", PACK_STATUSES)
    if status not in ALLOWED_ADVANCES.get(row["status"], ()):
        raise_invalid("A program may not advance from %s to %s." % (row["status"], status))
    if "quoted_landed_cost_cents" in data and data["quoted_landed_cost_cents"] is not None:
        quoted = as_int_opt(data, "quoted_landed_cost_cents")
        if quoted is None or quoted < 0:
            raise_invalid("quoted_landed_cost_cents must not be negative.")
        row["quoted_landed_cost_cents"] = quoted

    price_point = get_row("price_point", row["price_point_id"])
    if price_point["status"] != "ACTIVE":
        raise ApiError(ERR_PRICE_POINT_NOT_ACTIVE)

    derive_pack(row)
    if status == "ACTIVE" and int(row["quoted_landed_cost_cents"]) > int(row["target_landed_cost_cents"]):
        raise ApiError(ERR_PACK_COST_TARGET_MISSED)

    row["status"] = status
    touch(row)
    derive_pack(row)
    refresh_after_config_change()
    return ok_object(serialize_pack(row))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def raise_invalid(message):
    raise ApiError(ERR_INVALID_REQUEST, message)