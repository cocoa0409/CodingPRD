"""Logical clock, athlete roster and brand registration."""

from flask import Blueprint, request

import calc
import domain
import validation as V
from auth import ALL_ROLES, require
from envelope import created, ok, paginated, read_pagination
from errors import ApiError
from store import db, fmt_dt, new_record, set_clock, stamp, touch

bp = Blueprint("core", __name__)


@bp.post("/_clock/set_current_utc")
def clock_set():
    require(ALL_ROLES)
    payload = V.body()
    _, parsed = V.datetime_field(payload, "to_iso8601")
    set_clock(parsed)
    return ok({"current_utc": fmt_dt(parsed)})


# ---------------------------------------------------------------- athletes
@bp.post("/athletes")
def create_athlete():
    require("TalentAgent")
    payload = V.body()
    full_name = V.str_field(payload, "full_name")
    sport = V.str_field(payload, "sport")
    market_tier = V.enum_field(payload, "market_tier", calc.MARKET_TIERS)
    base_rate = V.int_field(payload, "base_appearance_rate_cents", minimum=1)
    commission_pct = V.number_field(payload, "commission_pct", gt=0, maximum=0.50)
    home_market = V.str_field(payload, "home_market", required=False, default="US")

    athlete = new_record({
        "full_name": full_name,
        "sport": sport,
        "market_tier": market_tier,
        "base_appearance_rate_cents": base_rate,
        "commission_pct": commission_pct,
        "home_market": home_market,
        "status": "ACTIVE",
        "active_exclusivity_count": 0,
        "exposure_risk_snapshot_score": 0,
        "no_show_count": 0,
    })
    db.athletes[athlete["id"]] = athlete
    return created(athlete)


@bp.get("/athletes/<athlete_id>")
def get_athlete(athlete_id):
    require(ALL_ROLES)
    return ok(domain.must_get("athletes", athlete_id))


@bp.post("/athletes/<athlete_id>/status")
def set_athlete_status(athlete_id):
    require("ComplianceOfficer")
    athlete = domain.must_get("athletes", athlete_id)
    payload = V.body()
    status = V.enum_field(payload, "status", calc.ROSTER_STATUSES)
    V.str_field(payload, "reason", required=False)
    athlete["status"] = status
    touch(athlete)
    return ok(athlete)


@bp.get("/athletes/<athlete_id>/exposure-summary")
def athlete_exposure(athlete_id):
    require("TalentAgent", "ComplianceOfficer", "FinanceManager")
    athlete = domain.must_get("athletes", athlete_id)
    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = "ROSTER_SNAPSHOT"
    if variant not in calc.EXPOSURE_VARIANTS:
        raise ApiError("ERR_INVALID_REQUEST", "variant must be ROSTER_SNAPSHOT or PIPELINE_PROJECTED")
    return ok(domain.exposure(athlete, variant))


@bp.get("/athletes/<athlete_id>/exclusivity-grants")
def athlete_grants(athlete_id):
    require(ALL_ROLES)
    athlete = domain.must_get("athletes", athlete_id)
    limit, offset = read_pagination()
    rows = domain.athlete_grants(athlete["id"])
    status = request.args.get("status")
    category = request.args.get("category")
    if status:
        rows = [g for g in rows if g["status"] == status]
    if category:
        rows = [g for g in rows if g["category"] == category]
    return paginated(rows, limit, offset)


# ------------------------------------------------------------------ brands
@bp.post("/brands")
def create_brand():
    require("BrandRep")
    payload = V.body()
    name = V.str_field(payload, "name")
    category = V.enum_field(payload, "category", calc.CATEGORIES)
    legal_entity_name = V.str_field(payload, "legal_entity_name")
    compliance_rating = V.int_field(payload, "compliance_rating", minimum=0, maximum=100)

    brand = new_record({
        "name": name,
        "category": category,
        "legal_entity_name": legal_entity_name,
        "compliance_rating": compliance_rating,
        "sanctioned": False,
        "sanction_reason": None,
    })
    db.brands[brand["id"]] = brand
    return created(brand)


@bp.get("/brands/<brand_id>")
def get_brand(brand_id):
    require(ALL_ROLES)
    return ok(domain.must_get("brands", brand_id))


@bp.post("/brands/<brand_id>/sanction")
def sanction_brand(brand_id):
    require("ComplianceOfficer")
    brand = domain.must_get("brands", brand_id)
    payload = V.body()
    sanctioned = V.bool_field(payload, "sanctioned")
    reason = V.str_field(payload, "reason", required=False)
    brand["sanctioned"] = sanctioned
    brand["sanction_reason"] = reason if sanctioned else None
    touch(brand)
    return ok(brand)
