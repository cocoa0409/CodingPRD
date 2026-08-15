"""Reference data: suppliers, customers, warehouses, products, yield specs."""

from flask import Blueprint, request

from store import TABLES
from helpers import (
    auth, success, err, get_body, req_str, req_int, req_num, req_enum,
    req_nonneg_int, req_positive_int, paginate, sorted_by_created, stamp_new,
    touch, path_get, num_out, dec, q2,
)

bp = Blueprint("reference", __name__)

ADMIN = ["DeskAdmin"]
ALL = ["DeskAdmin", "Trader", "RiskOfficer", "QualityGrader",
       "WarehouseOperator", "ClaimsAdjuster", "CustomerRep"]


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

def supplier_public(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "establishment_number": s["establishment_number"],
        "contact_email": s["contact_email"],
        "status": s["status"],
        "suspension_reason": s["suspension_reason"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/api/suppliers", methods=["POST"])
def create_supplier():
    auth(ADMIN)
    body = get_body()
    name = req_str(body, "name")
    est = req_str(body, "establishment_number")
    email = req_str(body, "contact_email")
    for s in TABLES["suppliers"].values():
        if s["establishment_number"] == est:
            err("ERR_DUPLICATE_CODE", 409,
                f"establishment_number already exists: {est}")
    rec = {
        "name": name,
        "establishment_number": est,
        "contact_email": email,
        "status": "ACTIVE",
        "suspension_reason": None,
    }
    stamp_new(rec)
    TABLES["suppliers"][rec["id"]] = rec
    return success(supplier_public(rec), code=201)


@bp.route("/api/suppliers", methods=["GET"])
def list_suppliers():
    auth(ALL)
    items = sorted_by_created(TABLES["suppliers"].values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items)
    return success([supplier_public(s) for s in page], response_type="array",
                   pagination=meta)


@bp.route("/api/suppliers/<supplierId>", methods=["GET"])
def get_supplier(supplierId):
    auth(ALL)
    s = path_get("suppliers", supplierId, "ERR_SUPPLIER_NOT_FOUND")
    return success(supplier_public(s))


@bp.route("/api/suppliers/<supplierId>/status", methods=["PUT"])
def set_supplier_status(supplierId):
    auth(ADMIN)
    body = get_body()
    target = req_enum(body, "status", {"ACTIVE", "SUSPENDED"})
    reason = req_str(body, "reason", optional=True)
    s = path_get("suppliers", supplierId, "ERR_SUPPLIER_NOT_FOUND")
    if target == "SUSPENDED":
        if s["status"] != "ACTIVE":
            err("ERR_INVALID_STATE", 409, "Supplier must be ACTIVE to suspend")
        s["status"] = "SUSPENDED"
        s["suspension_reason"] = reason
        touch(s)
        # Cascade: cancel every BOOKED purchase order of this supplier.
        for po in sorted_by_created(TABLES["purchase_orders"].values()):
            if po["supplier_id"] == s["id"] and po["status"] == "BOOKED":
                po["status"] = "CANCELLED"
                po["cancel_reason"] = "SUPPLIER_SUSPENDED"
                touch(po)
    else:  # target ACTIVE: reinstate
        if s["status"] != "SUSPENDED":
            err("ERR_INVALID_STATE", 409, "Supplier must be SUSPENDED to reinstate")
        s["status"] = "ACTIVE"
        s["suspension_reason"] = None
        touch(s)
        # Cancelled purchase orders are NOT reinstated.
    return success(supplier_public(s))


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

def customer_public(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "customer_code": c["customer_code"],
        "credit_limit_cents": c["credit_limit_cents"],
        "allocation_tier": c["allocation_tier"],
        "status": c["status"],
        "outstanding_exposure_cents": c["outstanding_exposure_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("/api/customers", methods=["POST"])
def create_customer():
    auth(ADMIN)
    body = get_body()
    name = req_str(body, "name")
    code = req_str(body, "customer_code")
    limit = req_nonneg_int(body, "credit_limit_cents")
    tier = req_enum(body, "allocation_tier", {"TIER_1", "TIER_2", "TIER_3"})
    for c in TABLES["customers"].values():
        if c["customer_code"] == code:
            err("ERR_DUPLICATE_CODE", 409, f"customer_code already exists: {code}")
    rec = {
        "name": name,
        "customer_code": code,
        "credit_limit_cents": limit,
        "allocation_tier": tier,
        "status": "ACTIVE",
        "outstanding_exposure_cents": 0,
    }
    stamp_new(rec)
    TABLES["customers"][rec["id"]] = rec
    return success(customer_public(rec), code=201)


@bp.route("/api/customers", methods=["GET"])
def list_customers():
    auth(ALL)
    items = sorted_by_created(TABLES["customers"].values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success([customer_public(c) for c in page], response_type="array",
                   pagination=meta)


@bp.route("/api/customers/<customerId>", methods=["GET"])
def get_customer(customerId):
    auth(ALL)
    c = path_get("customers", customerId, "ERR_CUSTOMER_NOT_FOUND")
    return success(customer_public(c))


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------

def warehouse_public(w):
    return {
        "id": w["id"],
        "name": w["name"],
        "zone": w["zone"],
        "capacity_lbs": w["capacity_lbs"],
        "occupied_lbs": num_out(w["occupied_lbs"]),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


@bp.route("/api/warehouses", methods=["POST"])
def create_warehouse():
    auth(ADMIN)
    body = get_body()
    name = req_str(body, "name")
    zone = req_enum(body, "zone", {"CHILLER", "FROZEN"})
    capacity = req_positive_int(body, "capacity_lbs")
    rec = {
        "name": name,
        "zone": zone,
        "capacity_lbs": capacity,
        "occupied_lbs": q2(dec(0)),
    }
    stamp_new(rec)
    TABLES["warehouses"][rec["id"]] = rec
    return success(warehouse_public(rec), code=201)


@bp.route("/api/warehouses", methods=["GET"])
def list_warehouses():
    auth(ALL)
    items = sorted_by_created(TABLES["warehouses"].values())
    page, meta = paginate(items)
    return success([warehouse_public(w) for w in page], response_type="array",
                   pagination=meta)


@bp.route("/api/warehouses/<warehouseId>", methods=["GET"])
def get_warehouse(warehouseId):
    auth(ALL)
    w = path_get("warehouses", warehouseId, "ERR_WAREHOUSE_NOT_FOUND")
    return success(warehouse_public(w))


# ---------------------------------------------------------------------------
# Products (immutable; no updated_at / version)
# ---------------------------------------------------------------------------

def product_public(p):
    return {
        "id": p["id"],
        "product_code": p["product_code"],
        "kind": p["kind"],
        "species": p["species"],
        "max_fat_pct": num_out(p["max_fat_pct"]),
        "shelf_life_days": p["shelf_life_days"],
        "required_temp_max_f": num_out(p["required_temp_max_f"]),
        "created_at": p["created_at"],
    }


@bp.route("/api/products", methods=["POST"])
def create_product():
    auth(ADMIN)
    body = get_body()
    code = req_str(body, "product_code")
    kind = req_enum(body, "kind", {"CARCASS", "PRIMAL", "SUBPRIMAL"})
    species = req_enum(body, "species", {"BEEF", "PORK"})
    max_fat = req_num(body, "max_fat_pct", optional=True)
    shelf = req_positive_int(body, "shelf_life_days")
    temp_max = req_num(body, "required_temp_max_f")
    if kind == "CARCASS":
        max_fat = None  # carcasses carry no fat spec and are always compliant
    elif max_fat is None:
        err("ERR_INVALID_REQUEST", 400,
            "max_fat_pct is required for PRIMAL and SUBPRIMAL products")
    for p in TABLES["products"].values():
        if p["product_code"] == code:
            err("ERR_DUPLICATE_CODE", 409, f"product_code already exists: {code}")
    rec = {
        "product_code": code,
        "kind": kind,
        "species": species,
        "max_fat_pct": max_fat,
        "shelf_life_days": shelf,
        "required_temp_max_f": temp_max,
    }
    stamp_new(rec, common=False)
    TABLES["products"][rec["id"]] = rec
    return success(product_public(rec), code=201)


@bp.route("/api/products", methods=["GET"])
def list_products():
    auth(ALL)
    items = sorted_by_created(TABLES["products"].values())
    kind = request.args.get("kind")
    if kind is not None:
        items = [p for p in items if p["kind"] == kind]
    page, meta = paginate(items)
    return success([product_public(p) for p in page], response_type="array",
                   pagination=meta)


@bp.route("/api/products/<productId>", methods=["GET"])
def get_product(productId):
    auth(ALL)
    p = path_get("products", productId, "ERR_PRODUCT_NOT_FOUND")
    return success(product_public(p))


# ---------------------------------------------------------------------------
# Yield specs (immutable; no updated_at / version)
# ---------------------------------------------------------------------------

def yield_spec_public(y):
    return {
        "id": y["id"],
        "carcass_product_id": y["carcass_product_id"],
        "output_product_id": y["output_product_id"],
        "expected_yield_pct": num_out(y["expected_yield_pct"]),
        "min_yield_pct": num_out(y["min_yield_pct"]),
        "max_yield_pct": num_out(y["max_yield_pct"]),
        "created_at": y["created_at"],
    }


@bp.route("/api/yield-specs", methods=["POST"])
def create_yield_spec():
    auth(ADMIN)
    body = get_body()
    carcass_id = req_str(body, "carcass_product_id")
    output_id = req_str(body, "output_product_id")
    expected = req_num(body, "expected_yield_pct")
    min_y = req_num(body, "min_yield_pct")
    max_y = req_num(body, "max_yield_pct")
    # Body FK existence (priority 6)
    from helpers import require_ref
    carcass = require_ref("products", carcass_id, "carcass_product_id")
    output = require_ref("products", output_id, "output_product_id")
    # Kind compatibility (priority 13)
    if carcass["kind"] != "CARCASS":
        err("ERR_PRODUCT_KIND_MISMATCH", 422,
            "carcass_product_id must reference a CARCASS product")
    if output["kind"] not in ("PRIMAL", "SUBPRIMAL"):
        err("ERR_PRODUCT_KIND_MISMATCH", 422,
            "output_product_id must reference a PRIMAL or SUBPRIMAL product")
    rec = {
        "carcass_product_id": carcass_id,
        "output_product_id": output_id,
        "expected_yield_pct": expected,
        "min_yield_pct": min_y,
        "max_yield_pct": max_y,
    }
    stamp_new(rec, common=False)
    TABLES["yield_specs"][rec["id"]] = rec
    return success(yield_spec_public(rec), code=201)


@bp.route("/api/yield-specs", methods=["GET"])
def list_yield_specs():
    auth(ALL)
    items = sorted_by_created(TABLES["yield_specs"].values())
    cp = request.args.get("carcass_product_id")
    op = request.args.get("output_product_id")
    if cp is not None:
        items = [y for y in items if y["carcass_product_id"] == cp]
    if op is not None:
        items = [y for y in items if y["output_product_id"] == op]
    page, meta = paginate(items)
    return success([yield_spec_public(y) for y in page], response_type="array",
                   pagination=meta)


@bp.route("/api/yield-specs/<yieldSpecId>", methods=["GET"])
def get_yield_spec(yieldSpecId):
    auth(ALL)
    y = path_get("yield_specs", yieldSpecId, "ERR_YIELD_SPEC_NOT_FOUND")
    return success(yield_spec_public(y))
