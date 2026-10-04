"""Foundation entities: brands, plants (incl. closure ritual), retailers."""

from flask import Blueprint, request

import storage
from calculations import new_record, bump, COMMITTED_ITEM_STATES
from envelope import success, paginate, sorted_by_created
from errors import fail
from rbac import guard, synchronized, ALL_ROLES
from serializers import brand_out, plant_out, retailer_out
from validation import body_json, f_str, f_int, f_bool, f_enum, f_dt

bp = Blueprint("foundation", __name__, url_prefix="/portfolio")


# ---------------- brands ----------------

@bp.post("/brands")
@synchronized
def create_brand():
    guard(["PortfolioManager"])
    body = body_json(required=True)
    name = f_str(body, "name")
    category_name = f_str(body, "category_name")
    core_flag = f_bool(body, "core_flag")
    pl_share = f_int(body, "private_label_share_pct", 0, 100)
    annual_rev = f_int(body, "annual_net_revenue_cents", 0)
    # step 11: scalar uniqueness (brand name unique across all brands)
    if any(b["name"] == name for b in storage.brands.values()):
        fail("ERR_DUPLICATE", f"brand name '{name}' already exists")
    rec = new_record()
    rec.update({
        "name": name,
        "category_name": category_name,
        "core_flag": core_flag,
        "private_label_share_pct": pl_share,
        "annual_net_revenue_cents": annual_rev,
        "brand_status": "ACTIVE",
    })
    storage.brands[rec["id"]] = rec
    return success(brand_out(rec), status=201)


@bp.get("/brands")
@synchronized
def list_brands():
    guard(ALL_ROLES)
    records = list(storage.brands.values())
    status = request.args.get("brand_status")
    if status is not None:
        records = [b for b in records if b["brand_status"] == status]
    category = request.args.get("category_name")
    if category is not None:
        records = [b for b in records if b["category_name"] == category]
    page, meta = paginate(sorted_by_created(records))
    return success([brand_out(b) for b in page], response_type="array",
                   pagination=meta)


# ---------------- plants ----------------

@bp.post("/plants")
@synchronized
def create_plant():
    guard(["PortfolioManager"])
    body = body_json(required=True)
    name = f_str(body, "name")
    capacity = f_int(body, "quarterly_capacity_units", 1)
    if any(p["name"] == name for p in storage.plants.values()):
        fail("ERR_DUPLICATE", f"plant name '{name}' already exists")
    rec = new_record()
    rec.update({
        "name": name,
        "quarterly_capacity_units": capacity,
        "plant_status": "OPERATING",
        "closure_date": None,
    })
    storage.plants[rec["id"]] = rec
    return success(plant_out(rec), status=201)


@bp.get("/plants")
@synchronized
def list_plants():
    guard(ALL_ROLES)
    records = list(storage.plants.values())
    status = request.args.get("plant_status")
    if status is not None:
        records = [p for p in records if p["plant_status"] == status]
    page, meta = paginate(sorted_by_created(records))
    return success([plant_out(p) for p in page], response_type="array",
                   pagination=meta)


@bp.post("/plants/<pid>/announce-closure")
@synchronized
def announce_closure(pid):
    guard(["PortfolioManager"])
    body = body_json(required=True)
    closure_date = f_dt(body, "closure_date")
    plant = storage.plants.get(pid)
    if plant is None:
        fail("ERR_NOT_FOUND", f"plant {pid} not found")
    if plant["plant_status"] != "OPERATING":
        fail("ERR_INVALID_STATE", "announce-closure requires plant OPERATING")
    plant["plant_status"] = "CLOSING"
    plant["closure_date"] = closure_date
    bump(plant)
    return success(plant_out(plant))


@bp.post("/plants/<pid>/complete-closure")
@synchronized
def complete_closure(pid):
    guard(["PortfolioManager"])
    plant = storage.plants.get(pid)
    if plant is None:
        fail("ERR_NOT_FOUND", f"plant {pid} not found")
    if plant["plant_status"] != "CLOSING":
        fail("ERR_INVALID_STATE", "complete-closure requires plant CLOSING")
    # emptiness guards, both checked at completion time
    live_items = any(
        i["primary_plant_id"] == pid and i["item_status"] in COMMITTED_ITEM_STATES
        for i in storage.items.values()
    )
    if live_items:
        fail("ERR_INVALID_STATE",
             "plant still hosts items in LISTED/CUT_PROPOSED/SELL_THROUGH")
    open_transfers = any(
        t["source_plant_id"] == pid and t["transfer_status"] in ("PLANNED", "QUALIFYING")
        for t in storage.transfers.values()
    )
    if open_transfers:
        fail("ERR_INVALID_STATE",
             "plant still sources open transfers (PLANNED/QUALIFYING)")
    plant["plant_status"] = "CLOSED"
    bump(plant)
    return success(plant_out(plant))


# ---------------- retailers ----------------

@bp.post("/retailers")
@synchronized
def create_retailer():
    guard(["PortfolioManager"])
    body = body_json(required=True)
    name = f_str(body, "name")
    risk_rating = f_enum(body, "risk_rating", ("LOW", "MEDIUM", "HIGH"))
    if any(r["name"] == name for r in storage.retailers.values()):
        fail("ERR_DUPLICATE", f"retailer name '{name}' already exists")
    rec = new_record()
    rec.update({"name": name, "risk_rating": risk_rating})
    storage.retailers[rec["id"]] = rec
    return success(retailer_out(rec), status=201)
