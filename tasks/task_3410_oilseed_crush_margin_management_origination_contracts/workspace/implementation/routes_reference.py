"""Reference data: farmers, quality discount schedules, sustainability
programs, market quotes, crush plants, buyers."""
from flask import Blueprint

from auth import require_roles
from envelope import success_list, success_obj
from errors import fail
from store import db, new_id, stamp_append_only, stamp_new, to_jsonable, touch
from validate import (body_dict, get_int, get_str, paginate, req_datetime,
                      req_decimal, req_int, req_month, req_str, sort_created)

bp = Blueprint("reference", __name__)

CERT_STANDARDS = ("ISCC", "REGEN", "ORGANIC")
COMMODITIES = ("BEAN", "OIL", "MEAL")
PLANT_STATUSES = ("ACTIVE", "MAINTENANCE")


# ---------------------------------------------------------------------------
# Farmers
# ---------------------------------------------------------------------------

@bp.post("/api/farmers")
def create_farmer():
    require_roles("PlatformAdmin")
    body = body_dict()
    rec = {
        "id": new_id(),
        "legal_name": req_str(body, "legal_name"),
        "county": req_str(body, "county"),
    }
    stamp_new(rec)
    db["farmers"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


# ---------------------------------------------------------------------------
# Quality discount schedules
# ---------------------------------------------------------------------------

_SCHEDULE_DECIMAL_FIELDS = (
    "moisture_base_pct", "moisture_shrink_pct_per_point",
    "damage_free_pct", "fm_free_pct", "reject_moisture_pct",
)
_SCHEDULE_INT_FIELDS = (
    "moisture_discount_cents_per_point", "damage_discount_cents_per_point",
    "fm_discount_cents_per_point",
)


@bp.post("/api/quality-discount-schedules")
def create_schedule():
    require_roles("PlatformAdmin")
    body = body_dict()
    rec = {"id": new_id(), "name": req_str(body, "name")}
    for f in _SCHEDULE_DECIMAL_FIELDS:
        rec[f] = req_decimal(body, f)
    for f in _SCHEDULE_INT_FIELDS:
        rec[f] = req_int(body, f)
    rec["status"] = "DRAFT"
    stamp_new(rec)
    db["schedules"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


@bp.post("/api/quality-discount-schedules/<sid>/publish")
def publish_schedule(sid):
    require_roles("PlatformAdmin")
    rec = db["schedules"].get(sid)
    if rec is None:
        fail("ERR_SCHEDULE_NOT_FOUND", "quality discount schedule not found")
    if rec["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "schedule is not in DRAFT")
    rec["status"] = "PUBLISHED"
    touch(rec)
    return success_obj(to_jsonable(rec))


# ---------------------------------------------------------------------------
# Sustainability programs
# ---------------------------------------------------------------------------

@bp.post("/api/sustainability-programs")
def create_program():
    require_roles("PlatformAdmin")
    body = body_dict()
    cert = req_str(body, "cert_standard")
    if cert not in CERT_STANDARDS:
        fail("ERR_INVALID_REQUEST", "cert_standard must be ISCC, REGEN or ORGANIC")
    premium = req_int(body, "premium_cents_per_bushel")
    if premium < 0:
        fail("ERR_INVALID_REQUEST", "premium_cents_per_bushel must be >= 0")
    rec = {
        "id": new_id(),
        "name": req_str(body, "name"),
        "cert_standard": cert,
        "premium_cents_per_bushel": premium,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db["programs"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


@bp.post("/api/sustainability-programs/<pid>/close")
def close_program(pid):
    require_roles("SustainabilityAuditor")
    rec = db["programs"].get(pid)
    if rec is None:
        fail("ERR_PROGRAM_NOT_FOUND", "sustainability program not found")
    if rec["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "program is not ACTIVE")
    rec["status"] = "CLOSED"
    touch(rec)
    return success_obj(to_jsonable(rec))


# ---------------------------------------------------------------------------
# Market quotes (append-only: id + created_at only)
# ---------------------------------------------------------------------------

@bp.post("/api/market-quotes")
def create_quote():
    require_roles("PlatformAdmin")
    body = body_dict()
    commodity = req_str(body, "commodity")
    if commodity not in COMMODITIES:
        fail("ERR_INVALID_REQUEST", "commodity must be BEAN, OIL or MEAL")
    rec = {
        "id": new_id(),
        "commodity": commodity,
        "quote_month": req_month(body, "quote_month"),
        "price_cents": req_int(body, "price_cents"),
        "quote_date": req_datetime(body, "quote_date"),
    }
    stamp_append_only(rec)
    db["quotes"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


@bp.get("/api/market-quotes")
def list_quotes():
    require_roles("PlatformAdmin", "OriginationMerchandiser", "CrushTrader",
                  "PlantScheduler")
    items = sort_created(list(db["quotes"].values()))
    commodity = request_args().get("commodity")
    month = request_args().get("quote_month")
    if commodity is not None:
        items = [q for q in items if q["commodity"] == commodity]
    if month is not None:
        items = [q for q in items if q["quote_month"] == month]
    page, limit, offset, total = paginate(items)
    return success_list([to_jsonable(q) for q in page], limit, offset, total)


def request_args():
    from flask import request
    return request.args


# ---------------------------------------------------------------------------
# Crush plants
# ---------------------------------------------------------------------------

@bp.post("/api/crush-plants")
def create_plant():
    require_roles("PlatformAdmin")
    body = body_dict()
    crush_cap = req_int(body, "daily_crush_capacity_bushels")
    refinery_cap = req_int(body, "daily_refinery_capacity_lbs")
    if crush_cap <= 0 or refinery_cap <= 0:
        fail("ERR_INVALID_REQUEST", "plant capacities must be > 0")
    share = req_decimal(body, "biodiesel_feedstock_share_pct")
    if share < 0 or share > 100:
        fail("ERR_INVALID_REQUEST", "biodiesel_feedstock_share_pct must be in 0..100")
    status = get_str(body, "status") or "ACTIVE"
    if status not in PLANT_STATUSES:
        fail("ERR_INVALID_REQUEST", "status must be ACTIVE or MAINTENANCE")
    from decimal import Decimal
    rec = {
        "id": new_id(),
        "name": req_str(body, "name"),
        "daily_crush_capacity_bushels": crush_cap,
        "daily_refinery_capacity_lbs": refinery_cap,
        "biodiesel_feedstock_share_pct": share,
        "bean_inventory_bushels": Decimal(0),
        "status": status,
    }
    stamp_new(rec)
    db["plants"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


@bp.get("/api/crush-plants/<pid>")
def get_plant(pid):
    require_roles("PlatformAdmin", "PlantScheduler", "LogisticsCoordinator")
    rec = db["plants"].get(pid)
    if rec is None:
        fail("ERR_PLANT_NOT_FOUND", "crush plant not found")
    return success_obj(to_jsonable(rec))


# ---------------------------------------------------------------------------
# Buyers
# ---------------------------------------------------------------------------

@bp.post("/api/buyers")
def create_buyer():
    require_roles("PlatformAdmin")
    body = body_dict()
    rec = {
        "id": new_id(),
        "company_name": req_str(body, "company_name"),
        "status": "ACTIVE",
        "open_claims_count": 0,
    }
    stamp_new(rec)
    db["buyers"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


@bp.get("/api/buyers/<bid>")
def get_buyer(bid):
    require_roles("PlatformAdmin", "ProductMerchandiser")
    rec = db["buyers"].get(bid)
    if rec is None:
        fail("ERR_BUYER_NOT_FOUND", "buyer not found")
    return success_obj(to_jsonable(rec))
