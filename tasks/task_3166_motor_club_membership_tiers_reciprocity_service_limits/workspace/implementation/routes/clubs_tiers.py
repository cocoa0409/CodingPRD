"""Clubs and membership tiers."""

from flask import Blueprint, request

from db import DB, new_id, stamp_new, touch
from errors import not_found, invalid_request
from middleware import require_auth
from response import ok_obj
from routes._common import list_response
from services.serialize import public
from services.validate import (
    body_json, req_string, req_int, req_list, opt_enum, opt_int, opt_string,
)

bp = Blueprint("clubs_tiers", __name__)

CLUB_ROLES_READ = {"ClubAdmin", "Dispatcher", "MemberServicesRep", "SettlementClerk", "FederationFinance"}
TIER_ROLES_READ = {"ClubAdmin", "MemberServicesRep", "Dispatcher", "Agent"}
TIER_CODES = {"CLASSIC", "PLUS", "PREMIER"}


# ------------------------------------------------------------------ clubs ---

@bp.post("/motor-club/clubs")
def create_club():
    require_auth({"ClubAdmin"})
    data = body_json()
    club_code = req_string(data, "club_code")
    name = req_string(data, "name")
    territories = req_list(data, "territory_state_codes", item_type=str)
    target = req_int(data, "default_arrival_target_minutes", min_value=1)
    billing_policy = opt_enum(data, "billing_policy", {"SCHEDULE", "ACTUAL"}, "SCHEDULE")
    for c in DB.clubs.values():
        if c["club_code"] == club_code:
            raise invalid_request("club_code must be unique")
    club = {
        "id": new_id(),
        "club_code": club_code,
        "name": name,
        "territory_state_codes": territories,
        "default_arrival_target_minutes": target,
        "billing_policy": billing_policy,
        "status": "ACTIVE",
    }
    stamp_new(club)
    DB.clubs[club["id"]] = club
    return ok_obj(public(club), 201)


@bp.get("/motor-club/clubs")
def list_clubs():
    require_auth(CLUB_ROLES_READ)
    return list_response(list(DB.clubs.values()))


@bp.get("/motor-club/clubs/<clubId>")
def get_club(clubId):
    require_auth(CLUB_ROLES_READ)
    club = DB.clubs.get(clubId)
    if club is None:
        raise not_found("club not found")
    return ok_obj(public(club))


@bp.put("/motor-club/clubs/<clubId>")
def update_club(clubId):
    require_auth({"ClubAdmin"})
    club = DB.clubs.get(clubId)
    if club is None:
        raise not_found("club not found")
    data = body_json()
    if "name" in data and data["name"] is not None:
        if not isinstance(data["name"], str) or not data["name"]:
            raise invalid_request("name must be a non-empty string")
        club["name"] = data["name"]
    if "territory_state_codes" in data and data["territory_state_codes"] is not None:
        v = data["territory_state_codes"]
        if not isinstance(v, list) or any(not isinstance(s, str) for s in v):
            raise invalid_request("territory_state_codes must be an array of strings")
        club["territory_state_codes"] = v
    if "default_arrival_target_minutes" in data and data["default_arrival_target_minutes"] is not None:
        v = data["default_arrival_target_minutes"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise invalid_request("default_arrival_target_minutes must be an integer >= 1")
        club["default_arrival_target_minutes"] = v
    if "billing_policy" in data and data["billing_policy"] is not None:
        v = data["billing_policy"]
        if v not in {"SCHEDULE", "ACTUAL"}:
            raise invalid_request("billing_policy must be SCHEDULE or ACTUAL")
        club["billing_policy"] = v
    if "status" in data and data["status"] is not None:
        v = data["status"]
        if v not in {"ACTIVE", "SUSPENDED"}:
            raise invalid_request("status must be ACTIVE or SUSPENDED")
        club["status"] = v
    touch(club)
    return ok_obj(public(club))


# ------------------------------------------------------------------ tiers ---

@bp.post("/motor-club/tiers")
def create_tier():
    require_auth({"ClubAdmin"})
    data = body_json()
    code = req_string(data, "code")
    if code not in TIER_CODES:
        raise invalid_request("code must be CLASSIC, PLUS or PREMIER")
    dues = req_int(data, "annual_dues_cents", min_value=0)
    included = req_int(data, "included_tow_miles", min_value=0)
    cap = req_int(data, "annual_call_cap", min_value=1)
    lockout = req_int(data, "lockout_benefit_cents", min_value=0)
    battery_incl = data.get("battery_service_included")
    if battery_incl is None:
        raise invalid_request("missing required field: battery_service_included")
    if not isinstance(battery_incl, bool):
        raise invalid_request("battery_service_included must be a boolean")
    household_price = req_int(data, "household_member_price_cents", min_value=0)
    overage_rate = req_int(data, "overage_rate_cents_per_mile", min_value=0)
    waiting_days = req_int(data, "upgrade_waiting_days", min_value=0)
    rank = req_int(data, "rank", min_value=1)
    for t in DB.tiers.values():
        if t["code"] == code:
            raise invalid_request("tier code must be unique")
        if t["rank"] == rank:
            raise invalid_request("tier rank must be unique")
    tier = {
        "id": new_id(),
        "code": code,
        "annual_dues_cents": dues,
        "included_tow_miles": included,
        "annual_call_cap": cap,
        "lockout_benefit_cents": lockout,
        "battery_service_included": battery_incl,
        "household_member_price_cents": household_price,
        "overage_rate_cents_per_mile": overage_rate,
        "upgrade_waiting_days": waiting_days,
        "rank": rank,
    }
    stamp_new(tier)
    DB.tiers[tier["id"]] = tier
    return ok_obj(public(tier), 201)


@bp.get("/motor-club/tiers")
def list_tiers():
    require_auth(TIER_ROLES_READ)
    return list_response(list(DB.tiers.values()))


@bp.get("/motor-club/tiers/<tierId>")
def get_tier(tierId):
    require_auth(TIER_ROLES_READ)
    tier = DB.tiers.get(tierId)
    if tier is None:
        raise not_found("tier not found")
    return ok_obj(public(tier))


@bp.put("/motor-club/tiers/<tierId>")
def update_tier(tierId):
    require_auth({"ClubAdmin"})
    tier = DB.tiers.get(tierId)
    if tier is None:
        raise not_found("tier not found")
    data = body_json()
    int_fields = {
        "annual_dues_cents": 0,
        "included_tow_miles": 0,
        "annual_call_cap": 1,
        "lockout_benefit_cents": 0,
        "household_member_price_cents": 0,
        "overage_rate_cents_per_mile": 0,
        "upgrade_waiting_days": 0,
    }
    for f, minv in int_fields.items():
        if f in data and data[f] is not None:
            v = data[f]
            if isinstance(v, bool) or not isinstance(v, int) or v < minv:
                raise invalid_request(f"{f} must be an integer >= {minv}")
            tier[f] = v
    if "battery_service_included" in data and data["battery_service_included"] is not None:
        if not isinstance(data["battery_service_included"], bool):
            raise invalid_request("battery_service_included must be a boolean")
        tier["battery_service_included"] = data["battery_service_included"]
    if "rank" in data and data["rank"] is not None:
        v = data["rank"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise invalid_request("rank must be an integer >= 1")
        for t in DB.tiers.values():
            if t["id"] != tier["id"] and t["rank"] == v:
                raise invalid_request("tier rank must be unique")
        tier["rank"] = v
    touch(tier)
    return ok_obj(public(tier))
