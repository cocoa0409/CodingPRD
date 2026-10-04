"""Catalog governance: equipment models, parts, supersession graph; courses."""
from flask import Blueprint

import helpers
from helpers import as_array, as_enum, as_int, as_str, auth, body, fail, ok, req, require_role
import storage
from storage import STORES, new_record, public, sort_created, touch

bp = Blueprint("catalog", __name__)

TURF_PROFILES = ("BENTGRASS", "BERMUDA", "POA_ANNUA", "MIXED")
CUT_STANDARDS = ("CHAMPIONSHIP", "CLUB", "MAINTENANCE")
MODEL_CATEGORIES = ("MOWER", "UTILITY_VEHICLE", "AERATOR", "IRRIGATION_CONTROLLER")
MODEL_TIERS = ("TOURNAMENT", "PRO", "STANDARD")

READ_ROLES = ("CorporateAdmin", "DistributorManager", "CourseManager", "IrrigationDealer")


# ---------------------------------------------------------------------------
# Golf courses
# ---------------------------------------------------------------------------

@bp.post("/courses")
def create_course():
    role, uid = auth()
    require_role(role, ("CorporateAdmin",))
    b = body()
    name = as_str(req(b, "name"), "name")
    turf = as_enum(req(b, "turf_profile"), "turf_profile", TURF_PROFILES)
    cut = as_enum(req(b, "cut_quality_standard"), "cut_quality_standard", CUT_STANDARDS)
    credit = as_int(req(b, "credit_limit_cents"), "credit_limit_cents")
    dist_id = as_str(req(b, "assigned_distributor_id"), "assigned_distributor_id")
    d = helpers.get_or_404("distributors", dist_id, "distributor")
    if d["channel"] != "EQUIPMENT":
        fail("ERR_WRONG_CHANNEL", "assigned_distributor_id must reference an EQUIPMENT distributor")
    rec = new_record("courses", {
        "name": name,
        "turf_profile": turf,
        "cut_quality_standard": cut,
        "credit_limit_cents": credit,
        "assigned_distributor_id": dist_id,
        "status": "PROSPECT",
    })
    return ok(public(rec), 201)


@bp.get("/courses/<cid>")
def get_course(cid):
    role, uid = auth()
    require_role(role, READ_ROLES)
    c = helpers.get_or_404("courses", cid, "course")
    return ok(public(c))


@bp.get("/courses")
def list_courses():
    role, uid = auth()
    require_role(role, READ_ROLES)
    recs = helpers.apply_filters(sort_created(STORES["courses"].values()),
                                 {"assigned_distributor_id": "assigned_distributor_id", "status": "status"})
    return helpers.paginate(recs)


# ---------------------------------------------------------------------------
# Equipment models
# ---------------------------------------------------------------------------

@bp.post("/models")
def create_model():
    role, uid = auth()
    require_role(role, ("CorporateAdmin",))
    b = body()
    model_code = as_str(req(b, "model_code"), "model_code")
    category = as_enum(req(b, "category"), "category", MODEL_CATEGORIES)
    tier = as_enum(req(b, "tier"), "tier", MODEL_TIERS)
    list_price = as_int(req(b, "list_price_cents"), "list_price_cents")
    eligible = as_array(req(b, "eligible_turf_types"), "eligible_turf_types")
    for t in eligible:
        as_enum(t, "eligible_turf_types[]", TURF_PROFILES)
    warranty_months = as_int(req(b, "factory_warranty_months"), "factory_warranty_months")
    labor_cap = as_int(req(b, "warranty_labor_hourly_cap_cents"), "warranty_labor_hourly_cap_cents")
    support_years = as_int(req(b, "parts_support_years"), "parts_support_years")
    rec = new_record("models", {
        "model_code": model_code,
        "category": category,
        "tier": tier,
        "list_price_cents": list_price,
        "eligible_turf_types": eligible,
        "factory_warranty_months": warranty_months,
        "warranty_labor_hourly_cap_cents": labor_cap,
        "parts_support_years": support_years,
        "lifecycle_status": "CATALOG_ACTIVE",
    })
    return ok(public(rec), 201)


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------

@bp.post("/parts")
def create_part():
    role, uid = auth()
    require_role(role, ("CorporateAdmin",))
    b = body()
    sku = as_str(req(b, "sku"), "sku")
    name = as_str(req(b, "name"), "name")
    model_id = as_str(req(b, "primary_model_id"), "primary_model_id")
    helpers.get_or_404("models", model_id, "model")
    unit_cost = as_int(req(b, "unit_cost_cents"), "unit_cost_cents")
    min_stock = as_int(req(b, "min_stock_qty"), "min_stock_qty")
    rec = new_record("parts", {
        "sku": sku,
        "name": name,
        "primary_model_id": model_id,
        "unit_cost_cents": unit_cost,
        "min_stock_qty": min_stock,
        "support_status": "ACTIVE",
        "superseded_by_part_id": None,
    })
    return ok(public(rec), 201)


@bp.get("/parts/<pid>")
def get_part(pid):
    role, uid = auth()
    require_role(role, READ_ROLES)
    p = helpers.get_or_404("parts", pid, "part")
    return ok(public(p))


@bp.get("/parts")
def list_parts():
    role, uid = auth()
    require_role(role, READ_ROLES)
    recs = helpers.apply_filters(sort_created(STORES["parts"].values()), {
        "primary_model_id": "primary_model_id",
        "superseded_by_part_id": "superseded_by_part_id",
        "support_status": "support_status",
    })
    return helpers.paginate(recs)


@bp.post("/parts/<pid>/transition")
def transition_part(pid):
    role, uid = auth()
    require_role(role, ("CorporateAdmin",))
    p = helpers.get_or_404("parts", pid, "part")
    b = body()
    to = as_str(req(b, "to"), "to")
    declared = {
        ("ACTIVE", "LAST_BUY"),
        ("LAST_BUY", "DISCONTINUED"),
        ("ACTIVE", "SUPERSEDED"),
    }
    if (p["support_status"], to) not in declared:
        fail("ERR_INVALID_STATE", "part cannot move from " + p["support_status"] + " to " + str(to))
    if to == "SUPERSEDED":
        succ_id = as_str(req(b, "successor_part_id"), "successor_part_id")
        succ = helpers.get_or_404("parts", succ_id, "successor part")
        if succ["support_status"] != "ACTIVE":
            fail("ERR_SUPERSESSION_CYCLE", "successor part must be in ACTIVE support")
        # Supersession graph must stay acyclic: walking superseded_by_part_id
        # forward from the successor must never reach this part.
        cur = succ
        while cur is not None:
            if cur["id"] == p["id"]:
                fail("ERR_SUPERSESSION_CYCLE", "supersession would create a cycle")
            nxt = cur.get("superseded_by_part_id")
            cur = STORES["parts"].get(nxt) if nxt else None
        p["superseded_by_part_id"] = succ_id
    p["support_status"] = to
    touch(p)
    return ok(public(p))
