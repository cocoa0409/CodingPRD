"""Branches, trucks, customers, catalog parts, the copper market feed and the
logical clock (PRD Sections 3.1, 3.2 and 2.5)."""
from flask import Blueprint, g

import clock
import constants as C
import db
import listing
import response
import serializers as ser
import validation as v
from errors import ApiError
from middleware import endpoint
from services import credit, index_shock, lookup

bp = Blueprint("catalog", __name__)


# --------------------------------------------------------------- Branch ----

@bp.post("/branches")
@endpoint(["PlatformAdmin"])
def create_branch():
    body = v.body()
    name = v.req_str(body, "name")
    region_code = v.req_str(body, "region_code")
    capacity = v.opt_int(body, "concurrent_cut_capacity", 1, minimum=1)
    surcharge = v.opt_int(body, "delivery_surcharge_cents", 0, minimum=0)

    rec = db.base_record()
    rec.update({
        "name": name,
        "region_code": region_code,
        "concurrent_cut_capacity": capacity,
        "delivery_surcharge_cents": surcharge,
        "scrap_ft_ytd": 0,
    })
    db.branches.add(rec)
    return response.object_response(ser.branch(rec), 201)


@bp.get("/branches/<branch_id>")
@endpoint(["PlatformAdmin", "SalesRep", "BranchOps", "CreditManager"])
def get_branch(branch_id):
    return response.object_response(ser.branch(lookup.branch(branch_id)))


# ---------------------------------------------------------------- Truck ----

@bp.post("/trucks")
@endpoint(["PlatformAdmin"])
def create_truck():
    body = v.body()
    branch_id = v.req_str(body, "branch_id")
    truck_code = v.req_str(body, "truck_code")
    has_boom_lift = v.opt_bool(body, "has_boom_lift", False)
    max_reel_slots = v.opt_int(body, "max_reel_slots", 6, minimum=1)

    lookup.branch(branch_id)

    rec = db.base_record()
    rec.update({
        "branch_id": branch_id,
        "truck_code": truck_code,
        "has_boom_lift": has_boom_lift,
        "max_reel_slots": max_reel_slots,
    })
    db.trucks.add(rec)
    return response.object_response(ser.truck(rec), 201)


@bp.get("/trucks/<truck_id>")
@endpoint(["PlatformAdmin", "BranchOps", "Driver"])
def get_truck(truck_id):
    return response.object_response(ser.truck(lookup.truck(truck_id)))


@bp.get("/trucks")
@endpoint(["PlatformAdmin", "BranchOps", "Driver"])
def list_trucks():
    v.pagination()
    branch_id = v.query_str("branch_id")
    rows = db.trucks.values_ordered()
    if branch_id:
        rows = [r for r in rows if r["branch_id"] == branch_id]
    return listing.respond(rows, ser.truck)


# ------------------------------------------------------------- Customer ----

@bp.post("/customers")
@endpoint(["PlatformAdmin", "CreditManager"])
def create_customer():
    body = v.body()
    name = v.req_str(body, "name")
    credit_limit_cents = v.req_int(body, "credit_limit_cents", minimum=0)

    rec = db.base_record()
    rec.update({
        "name": name,
        "credit_limit_cents": credit_limit_cents,
        "open_balance_cents": 0,
        "deposit_liability_cents": 0,
        "credit_status": "ACTIVE",
    })
    db.customers.add(rec)
    return response.object_response(ser.customer(rec), 201)


@bp.get("/customers/<customer_id>")
@endpoint(["PlatformAdmin", "CreditManager", "SalesRep", "Customer"])
def get_customer(customer_id):
    return response.object_response(ser.customer(lookup.customer(customer_id)))


@bp.post("/customers/<customer_id>/credit-adjustments")
@endpoint(["CreditManager"])
def create_credit_adjustment(customer_id):
    body = v.body()
    delta_limit = v.opt_int(body, "delta_credit_limit_cents", 0)
    delta_balance = v.opt_int(body, "delta_open_balance_cents", 0)
    v.req_str(body, "reason")

    customer = lookup.customer(customer_id)
    customer["credit_limit_cents"] += delta_limit
    customer["open_balance_cents"] += delta_balance
    db.touch(customer)
    credit.apply_posture(customer)
    return response.object_response(ser.customer(customer))


# ---------------------------------------------------------- CableProduct ----

@bp.post("/products")
@endpoint(["PlatformAdmin"])
def create_product():
    body = v.body()
    part_number = v.req_str(body, "part_number")
    conductor_metal = v.req_enum(body, "conductor_metal", C.CONDUCTOR_METALS)
    copper_lbs = v.opt_num(body, "copper_lbs_per_1000ft", 0, minimum=0)
    base_price = v.req_int(body, "base_price_cents_per_ft", minimum=0)
    min_cut = v.req_int(body, "min_cut_length_ft", minimum=C.ABSOLUTE_MIN_CUT_FT)
    cut_charge = v.req_int(body, "cut_charge_cents", minimum=0)
    reel_deposit = v.req_int(body, "reel_deposit_cents", minimum=0)
    master_len = v.req_int(body, "master_reel_length_ft", minimum=1)
    reel_weight = v.req_num(body, "reel_weight_lbs", exclusive_min=0)
    allowed_put_ups = v.req_enum_array(body, "allowed_put_ups", C.PUT_UPS)

    if conductor_metal == "ALUMINUM" and copper_lbs != 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "copper_lbs_per_1000ft must be 0 when conductor_metal is ALUMINUM.")

    if any(p["part_number"] == part_number for p in db.products.values()):
        raise ApiError("ERR_DUPLICATE_PART_NUMBER")

    rec = db.base_record()
    rec.update({
        "part_number": part_number,
        "conductor_metal": conductor_metal,
        "copper_lbs_per_1000ft": copper_lbs,
        "base_price_cents_per_ft": base_price,
        "min_cut_length_ft": min_cut,
        "cut_charge_cents": cut_charge,
        "reel_deposit_cents": reel_deposit,
        "master_reel_length_ft": master_len,
        "reel_weight_lbs": reel_weight,
        "allowed_put_ups": allowed_put_ups,
    })
    db.products.add(rec)
    return response.object_response(ser.product(rec), 201)


@bp.get("/products/<product_id>")
@endpoint(["PlatformAdmin", "SalesRep", "BranchOps"])
def get_product(product_id):
    return response.object_response(ser.product(lookup.product(product_id)))


# ----------------------------------------------------- CopperIndexEntry ----

@bp.post("/copper-index-entries")
@endpoint(["PlatformAdmin"])
def create_copper_index_entry():
    body = v.body()
    effective_date = v.req_date(body, "effective_date")
    price = v.req_int(body, "price_cents_per_lb", minimum=1)

    if any(e["effective_date"] == effective_date for e in db.copper_index_entries.values()):
        raise ApiError("ERR_DUPLICATE_INDEX_DATE")

    rec = db.base_record(versioned=False)
    rec.update({
        "effective_date": effective_date,
        "price_cents_per_lb": price,
        "published_by_user_id": g.user_id,
        "voided_quote_count": 0,
    })
    db.copper_index_entries.add(rec)

    index_shock.run_index_shock(rec)
    return response.object_response(ser.copper_index_entry(rec), 201)


@bp.get("/copper-index-entries/<entry_id>")
@endpoint(["PlatformAdmin", "SalesRep", "BranchOps", "CreditManager"])
def get_copper_index_entry(entry_id):
    return response.object_response(ser.copper_index_entry(lookup.copper_index_entry(entry_id)))


@bp.get("/copper-index-entries")
@endpoint(["PlatformAdmin", "SalesRep", "BranchOps", "CreditManager"])
def list_copper_index_entries():
    v.pagination()
    date_from = v.query_date("effective_date_from")
    date_to = v.query_date("effective_date_to")
    rows = list(db.copper_index_entries.values())
    if date_from:
        rows = [r for r in rows if r["effective_date"] >= date_from]
    if date_to:
        rows = [r for r in rows if r["effective_date"] <= date_to]
    rows.sort(key=lambda r: r["effective_date"], reverse=True)
    return listing.respond(rows, ser.copper_index_entry)


# ------------------------------------------------------------ the clock ----

@bp.post("/_clock/set_current_utc")
@endpoint(["PlatformAdmin"])
def set_clock():
    body = v.body()
    instant = v.req_datetime(body, "to_iso8601")
    clock.set_now(instant)
    return response.object_response({"current_utc": clock.iso_now()})
