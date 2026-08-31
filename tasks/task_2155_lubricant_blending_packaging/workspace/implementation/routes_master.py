"""Master data: logical clock, customers, component lots, product specs, tanks, lines."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import core
import enums
import store
import views
from core import (authenticate, body, caller_id, fail, is_customer_caller, iso, now,
                  opt_bool, opt_enum, opt_int, opt_num, opt_str, pagination, q_enum,
                  q_str, req_dt, req_enum, req_int, req_num, req_str, rhu)

bp = Blueprint("master", __name__)


# ==========================================================================
# Logical clock
# ==========================================================================
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["PlatformAdmin"])
    b = body()
    target = req_dt(b, "to_iso8601")
    core.CLOCK.set(target)
    return core.ok({"current_utc": iso(core.CLOCK.now())})


# ==========================================================================
# Customer
# ==========================================================================
@bp.post("/customers")
def create_customer():
    authenticate(["PlatformAdmin"])
    b = body()
    record = {
        "name": req_str(b, "name"),
        "customer_type": req_enum(b, "customer_type", enums.CUSTOMER_TYPES),
        "contract_tier": req_enum(b, "contract_tier", enums.CONTRACT_TIERS),
        "credit_limit_cents": req_int(b, "credit_limit_cents", ge=0),
        "takeback_agreement_status": opt_enum(
            b, "takeback_agreement_status", enums.AGREEMENT_STATUSES, "NONE"),
        "takeback_credit_balance_cents": 0,
        "last_credit_event_at": None,
    }
    return views.one(store.insert("Customer", record), 201)


@bp.get("/customers/<cid>")
def read_customer(cid):
    authenticate(["PlatformAdmin", "SalesRep", "ComplianceOfficer", "Customer"])
    customer = store.must_get("Customer", cid)
    if is_customer_caller() and caller_id() != customer["id"]:
        fail("ERR_CUSTOMER_SCOPE_VIOLATION")
    return views.one(customer)


@bp.post("/customers/<cid>/takeback-agreement")
def set_takeback_agreement(cid):
    authenticate(["PlatformAdmin", "SalesRep"])
    b = body()
    status = req_enum(b, "agreement_status", enums.AGREEMENT_STATUSES)
    customer = store.must_get("Customer", cid)
    customer["takeback_agreement_status"] = status
    store.touch(customer)
    return views.one(customer)


# ==========================================================================
# ComponentLot
# ==========================================================================
@bp.post("/component-lots")
def create_lot():
    authenticate(["PlatformAdmin"])
    b = body()
    received = req_num(b, "received_kg", gt=0)
    record = {
        "component_type": req_enum(b, "component_type", enums.COMPONENT_TYPES),
        "component_code": req_str(b, "component_code"),
        "additive_family": opt_enum(b, "additive_family", enums.ADDITIVE_FAMILIES_OPT,
                                    "NONE"),
        "received_kg": received,
        "available_kg": rhu(received, 3),
        "unit_cost_cents_per_kg": req_int(b, "unit_cost_cents_per_kg", gt=0),
        "kv100_cst": req_num(b, "kv100_cst", gt=0),
        "density_kg_per_l": req_num(b, "density_kg_per_l", gt=0),
        "coa_viscosity_verified": opt_bool(b, "coa_viscosity_verified", True),
        "status": "AVAILABLE",
        "quarantine_reason": None,
    }
    return views.one(store.insert("ComponentLot", record), 201)


@bp.get("/component-lots/<lid>")
def read_lot(lid):
    authenticate(views.STAFF_ALL)
    return views.one(store.must_get("ComponentLot", lid))


@bp.get("/component-lots")
def list_lots():
    authenticate(views.STAFF_ALL)
    limit, offset = pagination()
    component_code = q_str("component_code")
    component_type = q_enum("component_type", enums.COMPONENT_TYPES)
    status = q_enum("status", enums.LOT_STATUSES)
    rows = store.where("ComponentLot", component_code=component_code,
                       component_type=component_type, status=status)
    return views.listing(views.by_created_desc(rows), limit, offset)


@bp.post("/component-lots/<lid>/quarantine")
def quarantine_lot(lid):
    authenticate(["QualityManager"])
    b = body()
    reason = req_str(b, "reason")
    lot = store.must_get("ComponentLot", lid)
    if lot["status"] != "AVAILABLE":
        fail("ERR_INVALID_STATE")
    lot["status"] = "QUARANTINED"
    lot["quarantine_reason"] = reason
    store.touch(lot)
    return views.one(lot)


@bp.get("/component-lots/<lid>/draws")
def list_lot_draws(lid):
    authenticate(views.STAFF_OPS)
    limit, offset = pagination()
    status = q_enum("status", enums.DRAW_STATUSES)
    store.must_get("ComponentLot", lid)
    rows = store.where("ComponentDraw", component_lot_id=lid, status=status)
    return views.listing(views.by_created_asc(rows), limit, offset)


# ==========================================================================
# ProductSpec
# ==========================================================================
@bp.post("/product-specs")
def create_spec():
    authenticate(["ProductManager"])
    b = body()
    record = {
        "product_code": req_str(b, "product_code"),
        "sae_grade": req_str(b, "sae_grade"),
        "revision": 1,
        "status": "DRAFT",
        "target_kv100_cst": req_num(b, "target_kv100_cst", gt=0),
        "kv100_tolerance_pct": req_num(b, "kv100_tolerance_pct", gt=0, le=25),
        "min_additive_treat_pct": req_num(b, "min_additive_treat_pct", ge=0, le=100),
        "base_stock_group": req_enum(b, "base_stock_group", enums.BASE_STOCK_GROUPS),
        "additive_family": req_enum(b, "additive_family", enums.ADDITIVE_FAMILIES),
        "effective_from": None,
    }
    for existing in store.all_rows("ProductSpec"):
        if existing["product_code"] == record["product_code"]:
            fail("ERR_DUPLICATE_CODE")
    return views.one(store.insert("ProductSpec", record), 201)


@bp.get("/product-specs/<sid>")
def read_spec(sid):
    authenticate(views.STAFF_ALL)
    return views.one(store.must_get("ProductSpec", sid))


@bp.get("/product-specs")
def list_specs():
    authenticate(views.STAFF_ALL)
    limit, offset = pagination()
    status = q_enum("status", enums.SPEC_STATUSES)
    product_code = q_str("product_code")
    rows = store.where("ProductSpec", status=status, product_code=product_code)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.post("/product-specs/<sid>/activate")
def activate_spec(sid):
    authenticate(["ProductManager"])
    spec = store.must_get("ProductSpec", sid)
    if spec["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    spec["status"] = "ACTIVE"
    spec["effective_from"] = now()
    store.touch(spec)
    return views.one(spec)


@bp.post("/product-specs/<sid>/withdraw")
def withdraw_spec(sid):
    authenticate(["ProductManager"])
    b = body()
    req_str(b, "reason")
    spec = store.must_get("ProductSpec", sid)
    if spec["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    for claim in store.where("ApprovalClaim", product_spec_id=spec["id"]):
        if claim["status"] == "ACTIVE":
            fail("ERR_INVALID_STATE",
                 "An ACTIVE approval claim still stands on this specification.")
    for recipe in store.where("BlendRecipe", product_spec_id=spec["id"]):
        if recipe["status"] == "ACTIVE":
            recipe["status"] = "RETIRED"
            store.touch(recipe)
    spec["status"] = "WITHDRAWN"
    store.touch(spec)
    return views.one(spec)


@bp.post("/product-specs/<sid>/change-requests")
def create_change_request(sid):
    authenticate(["ProductManager"])
    b = body()
    record = {
        "product_spec_id": None,
        "requested_kv100_cst": req_num(b, "requested_kv100_cst", gt=0),
        "requested_kv100_tolerance_pct": req_num(
            b, "requested_kv100_tolerance_pct", gt=0, le=25),
        "requested_min_additive_treat_pct": req_num(
            b, "requested_min_additive_treat_pct", ge=0, le=100),
        "requested_additive_family": req_enum(
            b, "requested_additive_family", enums.ADDITIVE_FAMILIES),
        "status": "DRAFT",
        "viscosity_review": "PENDING",
        "approval_review": "PENDING",
        "claims_to_suspend_count": 0,
        "effective_revision": None,
    }
    expected = req_int(b, "expected_product_spec_version")
    spec = store.must_get("ProductSpec", sid)
    if expected != spec["version"]:
        fail("ERR_STALE_SPEC_VERSION")
    record["product_spec_id"] = spec["id"]
    store.touch(spec)
    return views.one(store.insert("SpecChangeRequest", record), 201)


# ==========================================================================
# BlendTank
# ==========================================================================
@bp.post("/blend-tanks")
def create_tank():
    authenticate(["PlatformAdmin"])
    b = body()
    record = {
        "tank_code": req_str(b, "tank_code"),
        "capacity_l": req_num(b, "capacity_l", gt=0),
        "status": "AVAILABLE",
        "heel_volume_l": opt_num(b, "heel_volume_l", Decimal("0.0"), ge=0),
        "heel_additive_family": opt_enum(
            b, "heel_additive_family", enums.ADDITIVE_FAMILIES_OPT, "NONE"),
        "heel_product_code": opt_str(b, "heel_product_code"),
        "last_flush_at": None,
    }
    for existing in store.all_rows("BlendTank"):
        if existing["tank_code"] == record["tank_code"]:
            fail("ERR_DUPLICATE_CODE")
    return views.one(store.insert("BlendTank", record), 201)


@bp.get("/blend-tanks/<tid>")
def read_tank(tid):
    authenticate(views.STAFF_OPS)
    return views.one(store.must_get("BlendTank", tid))


@bp.get("/blend-tanks")
def list_tanks():
    authenticate(views.STAFF_OPS)
    limit, offset = pagination()
    status = q_enum("status", enums.TANK_STATUSES)
    rows = store.where("BlendTank", status=status)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.post("/blend-tanks/<tid>/flush")
def flush_tank(tid):
    authenticate(["BlendOperator"])
    tank = store.must_get("BlendTank", tid)
    if tank["status"] not in ("AVAILABLE", "QUARANTINED"):
        fail("ERR_INVALID_STATE")
    for batch in store.where("BlendBatch", blend_tank_id=tank["id"]):
        if batch["production_status"] in ("CHARGING", "BLENDED"):
            fail("ERR_INVALID_STATE",
                 "A batch on this vessel is still CHARGING or BLENDED.")
    tank["status"] = "AVAILABLE"
    tank["heel_volume_l"] = Decimal("0.0")
    tank["heel_additive_family"] = "NONE"
    tank["heel_product_code"] = None
    tank["last_flush_at"] = now()
    store.touch(tank)
    return views.one(tank)


# ==========================================================================
# PackagingLine
# ==========================================================================
@bp.post("/packaging-lines")
def create_line():
    authenticate(["PlatformAdmin"])
    b = body()
    record = {
        "line_code": req_str(b, "line_code"),
        "max_concurrent_runs": opt_int(b, "max_concurrent_runs", 2, ge=1),
        "status": "AVAILABLE",
        "scheduled_run_count": 0,
    }
    for existing in store.all_rows("PackagingLine"):
        if existing["line_code"] == record["line_code"]:
            fail("ERR_DUPLICATE_CODE")
    return views.one(store.insert("PackagingLine", record), 201)


@bp.get("/packaging-lines/<lid>")
def read_line(lid):
    authenticate(views.STAFF_OPS)
    return views.one(store.must_get("PackagingLine", lid))


@bp.get("/packaging-lines")
def list_lines():
    authenticate(["PlatformAdmin", "ProductManager", "BlendOperator", "QualityManager",
                  "ComplianceOfficer"])
    limit, offset = pagination()
    status = q_enum("status", enums.LINE_STATUSES)
    rows = store.where("PackagingLine", status=status)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.post("/packaging-lines/<lid>/service-status")
def set_line_service_status(lid):
    authenticate(["PlatformAdmin"])
    b = body()
    target = req_enum(b, "target_status", enums.LINE_STATUSES)
    line = store.must_get("PackagingLine", lid)
    if target == line["status"]:
        fail("ERR_INVALID_STATE")
    line["status"] = target
    store.touch(line)
    return views.one(line)
